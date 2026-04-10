#!/usr/bin/env python3
import asyncio
import base64
import hashlib
import hmac
import inspect
import json
import logging
import time
import secrets
import urllib.parse as _up
import uuid as _uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone as _utc
from pathlib import Path
from typing import Dict, List, Optional, Any
import sys

# Monkey-patch: asyncio.iscoroutinefunction is deprecated in Python 3.14+
# and slated for removal in 3.16. slowapi 0.1.9 still uses it; redirect to
# inspect.iscoroutinefunction until slowapi ships a fix.
asyncio.iscoroutinefunction = inspect.iscoroutinefunction  # type: ignore[attr-defined]

import httpx
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import StreamingResponse, JSONResponse, Response, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field, ConfigDict, field_validator
import uvicorn
import slowapi as _slowapi
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

# Expose protected handler under a public name to avoid SLF001 / PyProtectedMember warnings
rate_limit_exceeded_handler = getattr(_slowapi, "_rate_limit_exceeded_handler")

from config import get_settings, Settings

# ==================== LOGGING SETUP ====================

def setup_logging(cfg: Settings):
    """Configure logging based on settings."""
    log_config = cfg.logging_config

    root = logging.getLogger()
    # Clear any handlers the service wrapper already attached via basicConfig()
    # so that we don't end up with duplicate log lines in journald.
    root.handlers.clear()
    root.setLevel(getattr(logging, log_config.level))

    fmt = logging.Formatter(log_config.format)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(getattr(logging, log_config.level))
    console_handler.setFormatter(fmt)
    root.addHandler(console_handler)

    if log_config.file_path:
        try:
            Path(log_config.file_path).parent.mkdir(parents=True, exist_ok=True)
            from logging.handlers import RotatingFileHandler
            file_handler = RotatingFileHandler(
                log_config.file_path,
                maxBytes=log_config.max_file_size,
                backupCount=log_config.backup_count,
            )
            file_handler.setLevel(getattr(logging, log_config.level))
            if log_config.enable_json_logging:
                import json_log_formatter
                file_handler.setFormatter(json_log_formatter.JSONFormatter())
            else:
                file_handler.setFormatter(fmt)
            root.addHandler(file_handler)
        except Exception as e:  # noqa: BLE001 – logging setup must never crash the app
            logging.warning(f"Could not set up file logging: {e}")



# ==================== GLOBAL SETTINGS ====================

settings = get_settings()
setup_logging(settings)
logger = logging.getLogger(__name__)

# ==================== RATE LIMITING ====================

limiter = Limiter(key_func=get_remote_address)


# ==================== LIFESPAN ====================

@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Startup and shutdown logic replacing deprecated @app.on_event."""
    logger.info(f"[+] Starting {settings.app_name} v{settings.version}")
    logger.info(f"[+] Environment: {settings.environment} | Server mode: {settings.server.mode}")
    await token_manager.load_tokens()
    if settings.storage.cleanup_expired_tokens:
        asyncio.create_task(periodic_cleanup())
    logger.info(f"[+] Service ready - {len(TOKENS)} tokens loaded | Grok backend enabled")
    yield
    logger.info("[-] Shutting down...")
    await token_manager.save_tokens()


# ==================== FASTAPI APP SETUP ====================

app = FastAPI(
    title=settings.app_name,
    description="Production-ready OpenAI-compatible API proxy for GitHub Copilot + xAI Grok",
    version=settings.version,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json" if settings.debug else None,
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)  # type: ignore[arg-type]
app.add_middleware(SlowAPIMiddleware)

if settings.security.enable_cors:
    # noinspection PyTypeChecker
    app.add_middleware(  # type: ignore[arg-type]
        CORSMiddleware,
        allow_origins=settings.security.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

if settings.environment == "production":
    allowed_hosts = ["localhost", "127.0.0.1", "::1"]

    parsed_url = _up.urlparse(settings.base_url)
    if parsed_url.hostname:
        allowed_hosts.append(str(parsed_url.hostname))

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)  # type: ignore[arg-type]

templates_path = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_path))

security = HTTPBearer(auto_error=False)


# ==================== DATA MODELS ====================

def _flatten_content_blocks(v: Any) -> str:
    """Normalize Anthropic-style content-block arrays → plain string.

    Claude Code (and other Anthropic clients) sometimes sends:
        "content": [{"type": "text", "text": "..."}, ...]
    Instead of a plain string.  We join all text-type blocks with newlines.
    """
    if isinstance(v, list):
        parts = []
        for block in v:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return v


class ChatMessage(BaseModel):
    role: str = Field(..., description="Role of the message sender")
    content: str = Field(..., description="Content of the message")

    @field_validator("content", mode="before")
    @classmethod
    def normalize_content(cls, v: Any) -> str:
        return _flatten_content_blocks(v)


class ChatRequest(BaseModel):
    model: str = Field(default="gpt-4", description="The model to use")
    messages: List[ChatMessage] = Field(..., description="List of messages")
    stream: bool = Field(default=False, description="Whether to stream the response")
    max_tokens: Optional[int] = Field(None, description="Maximum tokens to generate")
    temperature: Optional[float] = Field(None, description="Temperature for sampling")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Write a Python function to calculate fibonacci numbers"}],
            "stream": False,
            "max_tokens": 2000000,
            "temperature": 0.7
        }
    })


class ClaudeMessage(BaseModel):
    role: str = Field(..., description="user | assistant")
    content: str = Field(..., description="Message content")

    @field_validator("content", mode="before")
    @classmethod
    def normalize_content(cls, v: Any) -> str:
        return _flatten_content_blocks(v)


class ClaudeRequest(BaseModel):
    model: str = Field(default="gpt-4", description="The model to use (mapped internally)")
    messages: List[ClaudeMessage] = Field(...)
    system: Optional[str] = None
    max_tokens: Optional[int] = Field(None, ge=1, le=200000)

    @field_validator("system", mode="before")
    @classmethod
    def normalize_system(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        return _flatten_content_blocks(v) if isinstance(v, list) else str(v)
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    stream: bool = False

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "model": "claude-3-opus-20240229",
            "messages": [{"role": "user", "content": "Write a fast Fibonacci function"}],
            "system": "You are a world-class Python engineer.",
            "stream": True
        }
    })


class TokenData(BaseModel):
    github_token: str
    created: float
    last_used: Optional[float] = None
    user_info: Optional[Dict[str, Any]] = None
    expires_at: Optional[float] = None


class HealthResponse(BaseModel):
    status: str
    timestamp: str
    version: str
    active_tokens: int
    service: str
    uptime_seconds: float
    environment: str


class AuthResponse(BaseModel):
    message: str
    token: str
    expires_in: Optional[int] = None
    expires_at: Optional[str] = None


class DeviceFlowResponse(BaseModel):
    message: str
    verification_uri: str
    user_code: str
    device_code: str
    expires_in: int
    interval: int
    poll_url: str



class TwitterLoginRequest(BaseModel):
    oauth_token: str = Field(..., description="Twitter/X.com OAuth token")
    oauth_token_secret: str = Field(..., description="Twitter/X.com OAuth token secret")


class TwitterBearerLoginRequest(BaseModel):
    bearer_token: Optional[str] = Field(
        default=None,
        description="Twitter/X.com Bearer token (OAuth 2.0). Omit to use the server-configured TWITTER__BEARER_TOKEN.",
    )


class GrokWebLoginRequest(BaseModel):
    """
    X.com browser cookies for the unofficial Grok web backend (grok.x.com).
    How to get them: x.com → DevTools → Application → Cookies → https://x.com
    Requires an active Grok Pro / SuperGrok subscription.
    ⚠ Unofficial API — may break and violate xAI/X ToS if overused.
    """
    auth_token: str = Field(..., description="auth_token cookie value from x.com")
    ct0: str = Field(..., description="ct0 cookie value from x.com (CSRF token)")
    user_agent: Optional[str] = Field(
        None,
        description=(
            "Your browser User-Agent string. Overrides the global BROWSER__USER_AGENT "
            "for this session. Get it from: x.com → DevTools → Network → any request → "
            "User-Agent header."
        ),
    )
    x_com_cookies: Optional[str] = Field(
        None,
        description=(
            "Full Cookie header value from an authenticated X.com browser session. "
            "If provided, replaces the minimal auth_token+ct0 cookie with the complete "
            "browser cookie string — helps bypass bot-detection. "
            "Get it from: x.com → DevTools → Network → any request → Cookie header."
        ),
    )


class GrokComLoginRequest(BaseModel):
    """
    Browser cookie string for the unofficial grok.com web backend.
    How to get it: log in at grok.com → DevTools → Network tab →
    any request → Headers → copy the full value of the 'Cookie:' header.
    Requires an active xAI / Grok subscription.
    ⚠ Unofficial API — may break and violate xAI ToS if overused.
    """
    cookie: str = Field(..., description="Full Cookie header value from an authenticated grok.com browser session")
    user_agent: Optional[str] = Field(
        None,
        description=(
            "Your browser User-Agent string. Overrides the global BROWSER__USER_AGENT "
            "for this session."
        ),
    )


# ==================== TOKEN MANAGEMENT ====================

TOKENS: Dict[str, TokenData] = {}
SERVICE_START_TIME = time.time()


class TokenManager:
    def __init__(self):
        self.encryption_key = self._get_or_create_encryption_key()
        # Set to True once load_tokens() completes without error.
        # save_tokens() uses this to guard against overwriting a non-empty
        # token file with an empty TOKENS dict (e.g., when the first load
        # failed due to a permission error).
        self._load_succeeded: bool = False

    @staticmethod
    def _get_or_create_encryption_key() -> Optional[str]:
        if not settings.storage.encrypt_tokens:
            return None
        key = settings.storage.token_encryption_key
        if not key:
            key = secrets.token_urlsafe(32)
            logger.warning(
                "Generated new token encryption key. Set STORAGE__TOKEN_ENCRYPTION_KEY in config to persist across restarts.")
        return key

    async def save_tokens(self) -> None:
        # Guard: never overwrite an existing token file with an empty dict
        # if we never successfully loaded from it.  This prevents silent data
        # loss when, for example, the initial load failed with Permission Denied
        # and the service later shuts down with TOKENS still empty.
        token_file = settings.storage.get_token_file_path()
        if not TOKENS and not self._load_succeeded and token_file.exists():
            logger.warning(
                "Skipping token save: TOKENS is empty and the token file was never "
                "loaded successfully — preserving existing file to prevent data loss."
            )
            return
        try:
            token_file = settings.storage.get_token_file_path()
            token_file.parent.mkdir(parents=True, exist_ok=True)

            data = {}
            for token_id, token_data in TOKENS.items():
                serialized = token_data.model_dump()
                if self.encryption_key:
                    serialized['github_token'] = self._encrypt(serialized['github_token'])
                data[token_id] = serialized

            temp_file = token_file.with_suffix('.tmp')
            with open(temp_file, 'w') as f:
                json.dump(data, f, indent=2)
            temp_file.replace(token_file)

            logger.debug(f"Saved {len(TOKENS)} tokens to {token_file}")
        except Exception as e:  # noqa: BLE001 – token persistence must not crash the service
            logger.error(f"Error saving tokens: {e}")

    async def load_tokens(self) -> None:
        try:
            token_file = settings.storage.get_token_file_path()
            if not token_file.exists():
                logger.info("No existing token file found, starting fresh")
                return

            with open(token_file, 'r') as f:
                data = json.load(f)

            loaded_tokens = {}
            for token_id, token_data in data.items():
                try:
                    if self.encryption_key and 'github_token' in token_data:
                        token_data['github_token'] = self._decrypt(token_data['github_token'])
                    loaded_tokens[token_id] = TokenData(**token_data)
                except Exception as e:  # noqa: BLE001 – skip corrupt individual token entries
                    logger.warning(f"Failed to load token {token_id[:10]}...: {e}")

            TOKENS.clear()
            TOKENS.update(loaded_tokens)
            logger.info(f"Loaded {len(TOKENS)} tokens from {token_file}")
        except Exception as e:  # noqa: BLE001 – token load failure must not crash startup
            logger.error(f"Error loading tokens: {e}")
            # _load_succeeded remains False, so save_tokens() will not overwrite the
            # existing file on shutdown (prevents data loss on e.g., Permission Denied).
        else:
            self._load_succeeded = True

    @staticmethod
    def _encrypt(data: str) -> str:
        import base64
        return base64.b64encode(data.encode()).decode()

    @staticmethod
    def _decrypt(data: str) -> str:
        import base64
        return base64.b64decode(data.encode()).decode()

    async def cleanup_expired_tokens(self) -> int:
        if not settings.storage.cleanup_expired_tokens:
            return 0
        current_time = time.time()
        expired_tokens = [token_id for token_id, token_data in TOKENS.items() if
                          token_data.expires_at and token_data.expires_at < current_time]
        for token_id in expired_tokens:
            del TOKENS[token_id]
        if expired_tokens:
            await self.save_tokens()
            logger.info(f"Cleaned up {len(expired_tokens)} expired tokens")
        return len(expired_tokens)


token_manager = TokenManager()

# ==================== COPILOT TOKEN EXCHANGE ====================
# api.githubcopilot.com requires a short-lived Copilot API token, NOT a raw
# GitHub OAuth/PAT token. We exchange once and cache until near-expiry.

_copilot_token_cache: Dict[str, tuple] = {}  # github_token → (copilot_token, expires_at)


async def _get_copilot_token(github_token: str) -> str:
    """
    Exchange a GitHub OAuth/PAT token for a short-lived Copilot API token.
    Tries multiple endpoint + auth-prefix combinations for maximum compatibility.
    Tokens are cached for up to 25 minutes (they expire after ~30 min).
    """
    cached = _copilot_token_cache.get(github_token)
    if cached:
        copilot_token, exp = cached
        if exp > time.time() + 60:  # 60-second safety buffer
            return copilot_token

    # Try several (endpoint, auth-prefix) combinations.
    # PATs work with the "token" prefix; OAuth App tokens may need "Bearer".
    # The v2 endpoint requires Copilot permission; v1 is a fallback.
    _COPILOT_TOKEN_ENDPOINTS = [
        ("https://api.github.com/copilot_internal/v2/token", "token"),
        ("https://api.github.com/copilot_internal/v2/token", "Bearer"),
        ("https://api.github.com/copilot_internal/v1/token", "token"),
        ("https://api.github.com/copilot_internal/v1/token", "Bearer"),
    ]
    _COPILOT_TOKEN_HEADERS = {
        "Accept": "application/json",
        "Editor-Version": "vscode/1.96.0",
        "Editor-Plugin-Version": "copilot-chat/0.24.0",
        "Copilot-Integration-Id": "vscode-chat",
        "User-Agent": "GithubCopilot/1.155.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    last_status = 0
    last_text = ""
    async with httpx.AsyncClient(timeout=15.0) as hc:
        for url, prefix in _COPILOT_TOKEN_ENDPOINTS:
            hdrs = {**_COPILOT_TOKEN_HEADERS, "Authorization": f"{prefix} {github_token}"}
            try:
                resp = await hc.get(url, headers=hdrs)
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"Copilot token exchange {url} failed: {exc}")
                continue
            last_status, last_text = resp.status_code, resp.text
            if resp.status_code == 401:
                raise HTTPException(
                    status_code=401,
                    detail="GitHub token rejected. Re-authenticate via /login/device.",
                )
            if resp.status_code == 200:
                data = resp.json()
                copilot_token: str = data.get("token", "")
                if copilot_token:
                    exp_raw = data.get("expires_at", "")
                    try:
                        if isinstance(exp_raw, (int, float)):
                            exp_ts = float(exp_raw)
                        elif isinstance(exp_raw, str) and exp_raw:
                            exp_ts = datetime.fromisoformat(exp_raw.replace("Z", "+00:00")).timestamp()
                        else:
                            exp_ts = time.time() + 25 * 60
                    except (ValueError, TypeError):
                        exp_ts = time.time() + 25 * 60
                    _copilot_token_cache[github_token] = (copilot_token, exp_ts)
                    logger.debug(f"Copilot token exchanged via {url} ({prefix}), expires at {exp_ts}")
                    return copilot_token
            logger.debug(f"Copilot token exchange {url} ({prefix}): HTTP {resp.status_code}")

    # All attempts failed – fall back to raw token (GPT models still work).
    logger.warning(
        f"Copilot token exchange failed (last HTTP {last_status}: "
        f"{last_text[:120].strip()!r}); falling back to raw token. "
        "Use Device Flow at /login/device to obtain a valid GitHub OAuth token."
    )
    return github_token


# ==================== BACKEND ROUTING HELPERS ====================

async def get_backend_headers(token: str, is_grok: bool) -> Dict[str, str]:
    """Return the correct headers depending on the backend (Copilot vs. Grok)."""
    if is_grok:
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "OpenClaude-Grok-Proxy/2.1",
        }
    # GitHub Copilot chat completions — token must already be a Copilot API token
    # obtained via _get_copilot_token() (NOT a raw GitHub OAuth/PAT token).
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Editor-Version": "vscode/1.95.3",
        "Editor-Plugin-Version": "copilot-chat/0.24.0",
        "Copilot-Integration-Id": "vscode-chat",
        "openai-intent": "conversation-panel",
        "User-Agent": settings.proxy.user_agent,
        "X-Request-Id": secrets.token_hex(16),
    }


def is_grok_model(model: str) -> bool:
    """Check whether the requested model is an official xAI Grok API model (not grok-web-*)."""
    m = model.lower()
    return m.startswith("grok-") and not m.startswith("grok-web")


def normalize_model_name(model: str) -> str:
    """Pass model name through — resolution is handled by resolve_copilot_model()."""
    return model


# Maps user-facing / alias model IDs → real GitHub Copilot model IDs.
# api.githubcopilot.com/models uses DOTS for version suffixes (claude-sonnet-4.5).
# Clients often send dashes or legacy names — map them all here.
_COPILOT_MODEL_ALIASES: Dict[str, str] = {
    # Legacy Claude 3.x names → nearest Claude 4 equivalent on Copilot
    "claude-3-5-sonnet":            "claude-sonnet-4.5",
    "claude-3-5-sonnet-latest":     "claude-sonnet-4.5",
    "claude-3-7-sonnet":            "claude-sonnet-4.5",
    "claude-3-7-sonnet-latest":     "claude-sonnet-4.5",
    "claude-3-opus":                "claude-opus-4.5",
    # Dash variants → dot variants (real Copilot API model IDs)
    "claude-sonnet-4-5":            "claude-sonnet-4.5",
    "claude-sonnet-4-6":            "claude-sonnet-4.6",
    "claude-opus-4-5":              "claude-opus-4.5",
    "claude-opus-4-6":              "claude-opus-4.6",
    "claude-haiku-4-5":             "claude-haiku-4.5",
}


def resolve_copilot_model(model: str) -> str:
    """Resolve a (possibly aliased) model name to the real Copilot model ID."""
    return _COPILOT_MODEL_ALIASES.get(model.lower(), model)


ANTHROPIC_API_BASE = "https://api.anthropic.com/v1"

# ==================== GROK WEB BACKEND (grok.x.com) ====================
# Unofficial reverse-engineered endpoint — requires X.com Grok Pro cookies.

GROK_WEB_API_URL = "https://grok.x.com/2/grok/add_response.json"
GROK_WEB_TOKEN_PREFIX = "grokweb::"

# Maps proxy-facing model IDs → grokModelOptionId sent to grok.x.com
GROK_WEB_MODEL_MAP: Dict[str, str] = {
    "grok-web": "grok-latest",
    "grok-web-latest": "grok-latest",
    "grok-web-3": "grok-3",
    "grok-web-3-mini": "grok-3-mini",
    "grok-web-2": "grok-2",
    "grok-web-beta": "grok-beta",
}

# Browser-like headers required by grok.x.com
# NOTE: The User-Agent is sourced dynamically from settings.browser.user_agent
#       so that it can be overridden via BROWSER__USER_AGENT in config.env.
_GROK_WEB_BROWSER_STATIC = {
    "Origin": "https://grok.x.com",
    "Referer": "https://grok.x.com/",
    "Accept": "text/event-stream, application/json",
    "X-Twitter-Active-User": "yes",
    "X-Twitter-Client-Language": "en",
}


def is_grok_web_model(model: str) -> bool:
    """Return True for grok-web-* models (unofficial web backend)."""
    return model.lower().startswith("grok-web")


def _build_grok_web_headers(
    auth_token: str,
    ct0: str,
    user_agent: Optional[str] = None,
    x_com_cookies: Optional[str] = None,
) -> Dict[str, str]:
    """
    Build headers for grok.x.com requests.

    :param auth_token:    X.com auth_token cookie value (also used for Authorization header).
    :param ct0:           X.com ct0 cookie value (CSRF token).
    :param user_agent:    Per-session UA override; falls back to settings.browser.user_agent.
    :param x_com_cookies: Full X.com Cookie header string (replaces the minimal
                          auth_token+ct0 cookie). If None, the cookie is built from
                          auth_token + ct0 + any BROWSER__X_COM_COOKIES config extras.
    """
    ua: str = user_agent if user_agent is not None else (settings.browser.user_agent or "")
    if x_com_cookies:
        # Use the complete browser cookie string as-is.
        # Ensure auth_token and ct0 are present (some endpoints need them for the
        # Authorization / X-Csrf-Token headers; the Cookie header is separate).
        cookie_str = x_com_cookies
        if "auth_token=" not in x_com_cookies:
            cookie_str = f"auth_token={auth_token}; {cookie_str}"
        if "ct0=" not in x_com_cookies:
            cookie_str = f"ct0={ct0}; {cookie_str}"
    else:
        # Build minimal cookie and merge in any globally configured extra cookies.
        cookie_parts: List[str] = [f"auth_token={auth_token}", f"ct0={ct0}"]
        used_keys = {"auth_token", "ct0"}
        if settings.browser.x_com_cookies:
            for part in settings.browser.x_com_cookies.split(";"):
                part = part.strip()
                if not part:
                    continue
                key = part.split("=", 1)[0].strip() if "=" in part else part
                if key and key not in used_keys:
                    cookie_parts.append(part)
                    used_keys.add(key)
        cookie_str = "; ".join(cookie_parts)

    return {
        **_GROK_WEB_BROWSER_STATIC,
        "User-Agent": ua,
        "Authorization": f"Bearer {auth_token}",
        "X-Csrf-Token": ct0,
        "Cookie": cookie_str,
        "Content-Type": "application/json",
    }


def _messages_to_grok_web(messages: List[ChatMessage]) -> tuple:
    """
    Convert OpenAI-style messages to Grok web format.
    Returns (current_user_message: str, history: list).
    System prompts are prepended to the first user message.
    """
    if not messages:
        return "", []

    history: List[Dict[str, Any]] = []
    pending_system = ""

    for msg in messages[:-1]:
        if msg.role == "system":
            pending_system = f"[System]: {msg.content}\n\n"
        elif msg.role == "user":
            history.append({
                "message": pending_system + msg.content,
                "sender": 1,
                "promptSource": "",
                "fileAttachments": [],
            })
            pending_system = ""
        elif msg.role == "assistant":
            history.append({
                "message": msg.content,
                "sender": 2,
                "promptSource": "",
                "fileAttachments": [],
            })

    last = messages[-1]
    current_msg = pending_system + last.content
    return current_msg, history


def _build_grok_web_payload(
        current_message: str,
        history: List[Dict[str, Any]],
        grok_model_id: str,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "message": current_message,
        "grokModelOptionId": grok_model_id,
        "conversationId": secrets.token_hex(16),
        "returnSearchResults": False,
        "returnCitations": False,
        "promptSource": "Chat",
        "imageGenerationCount": 1,
        "responseMode": "text",
        "isDeepsearch": False,
        "isSuggested": False,
        "fileAttachments": [],
        "requestFeatures": {"eagerTweetFetching": False, "serverHistory": bool(history)},
    }
    if history:
        payload["responses"] = history
    return payload


def _grok_web_error_from_status(status_code: int) -> str:
    if status_code == 401:
        return "Grok web auth failed — X.com cookies expired. POST /login/grok-web with fresh auth_token and ct0."
    if status_code == 403:
        return "Grok Pro / SuperGrok subscription required for web backend access."
    return f"Grok web API returned HTTP {status_code}."


async def _grok_web_chat(
        chat_request: ChatRequest,
        grokweb_token: str,
        model: str,
) -> Any:
    """Route an OpenAI-compatible request to the unofficial grok.x.com web backend."""
    parts = grokweb_token.split("::", 2)
    if len(parts) != 3 or parts[0] != "grokweb":
        raise HTTPException(
            status_code=401,
            detail="Invalid Grok web credentials. Use POST /login/grok-web to register.",
        )
    auth_token, ct0 = parts[1], parts[2]

    session_ua, session_x_com_cookies = _get_session_browser_info(grokweb_token)
    grok_model_id = GROK_WEB_MODEL_MAP.get(model.lower(), "grok-3")
    current_message, hist = _messages_to_grok_web(chat_request.messages)
    web_payload = _build_grok_web_payload(current_message, hist, grok_model_id)
    web_headers = _build_grok_web_headers(
        auth_token, ct0,
        user_agent=session_ua,
        x_com_cookies=session_x_com_cookies,
    )
    web_timeout = httpx.Timeout(settings.proxy.request_timeout, connect=10.0)
    cid = f"chatcmpl-grokweb-{int(time.time())}-{secrets.token_hex(4)}"

    if chat_request.stream:
        return await _grok_web_stream(web_payload, web_headers, web_timeout, cid, model)
    return await _grok_web_sync(web_payload, web_headers, web_timeout, cid, model, grok_model_id)


async def _grok_web_stream(
        web_payload: Dict[str, Any],
        web_headers: Dict[str, str],
        web_timeout: httpx.Timeout,
        cid: str,
        model: str,
) -> StreamingResponse:
    """Streaming path for the Grok web backend → OpenAI SSE format."""

    async def _generate():  # noqa: ANN202
        try:
            async with httpx.AsyncClient(timeout=web_timeout) as hc:
                async with hc.stream("POST", GROK_WEB_API_URL, json=web_payload, headers=web_headers) as sr:
                    if sr.status_code != 200:
                        err_msg = _grok_web_error_from_status(sr.status_code)
                        yield f"data: {json.dumps({'error': {'message': err_msg}})}\n\ndata: [DONE]\n\n".encode()
                        return

                    open_chunk = json.dumps({
                        "id": cid, "object": "chat.completion.chunk",
                        "created": int(time.time()), "model": model,
                        "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}],
                    })
                    yield f"data: {open_chunk}\n\n".encode()

                    async for raw_line in sr.aiter_lines():
                        stripped = raw_line.strip()
                        if not stripped:
                            continue
                        try:
                            obj = json.loads(stripped)
                            gres = obj.get("result", {})
                            rt = gres.get("responseType", "")
                            dtxt = gres.get("message", "")

                            if rt == "final_response" or gres.get("isSoftStop", False):
                                stop_chunk = json.dumps({
                                    "id": cid, "object": "chat.completion.chunk",
                                    "created": int(time.time()), "model": model,
                                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                                })
                                yield f"data: {stop_chunk}\n\n".encode()
                                break

                            if dtxt and rt == "partial_response":
                                delta_chunk = json.dumps({
                                    "id": cid, "object": "chat.completion.chunk",
                                    "created": int(time.time()), "model": model,
                                    "choices": [{"index": 0, "delta": {"content": dtxt}, "finish_reason": None}],
                                })
                                yield f"data: {delta_chunk}\n\n".encode()
                        except (json.JSONDecodeError, KeyError):
                            continue

                    yield b"data: [DONE]\n\n"

        except httpx.TimeoutException:
            yield b"data: {\"error\":{\"message\":\"Grok web timed out\"}}\n\ndata: [DONE]\n\n"
        except httpx.RequestError as req_err:  # noqa: BLE001
            err_body = json.dumps({"error": {"message": f"Grok web connection error: {req_err}"}})
            yield f"data: {err_body}\n\ndata: [DONE]\n\n".encode()

    return StreamingResponse(_generate(), media_type="text/event-stream")


async def _grok_web_sync(
        web_payload: Dict[str, Any],
        web_headers: Dict[str, str],
        web_timeout: httpx.Timeout,
        cid: str,
        model: str,
        grok_model_id: str,
) -> Dict[str, Any]:
    """Non-streaming path for the Grok web backend → OpenAI JSON format."""
    try:
        async with httpx.AsyncClient(timeout=web_timeout) as hc:
            wr = await hc.post(GROK_WEB_API_URL, json=web_payload, headers=web_headers)
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Grok web API timed out")
    except httpx.RequestError as req_err:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Grok web connection error: {req_err}")

    if wr.status_code != 200:
        raise HTTPException(
            status_code=wr.status_code if wr.status_code in (401, 403) else 502,
            detail=_grok_web_error_from_status(wr.status_code),
        )

    full_text = ""
    for raw_line in wr.text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        try:
            obj = json.loads(stripped)
            gres = obj.get("result", {})
            rt = gres.get("responseType", "")
            if rt == "final_response":
                full_text = gres.get("message", full_text)
                break
            if rt == "partial_response":
                full_text += gres.get("message", "")
        except (json.JSONDecodeError, KeyError):  # noqa: BLE001
            continue

    logger.info(f"[grok-web] model={grok_model_id} response_len={len(full_text)}")
    return {
        "id": cid, "object": "chat.completion",
        "created": int(time.time()), "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": full_text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


# ==================== GROK.COM BACKEND (grok.com) ====================
# Unofficial reverse-engineered endpoint — requires grok.com browser cookies.

GROK_COM_API_URL = "https://grok.com/rest/app-chat/conversations/new"
GROK_COM_TOKEN_PREFIX = "grokcom::"

# Maps proxy-facing model IDs → modelName sent to grok.com
GROK_COM_MODEL_MAP: Dict[str, str] = {
    "grok-com": "grok-3",
    "grok-com-latest": "grok-3",
    "grok-com-3": "grok-3",
    "grok-com-3-mini": "grok-3-mini",
    "grok-com-2": "grok-2",
    "grok-com-beta": "grok-beta",
}

_GROK_COM_BROWSER_STATIC = {
    "Origin": "https://grok.com",
    "Referer": "https://grok.com/chat",
    "Accept": "text/event-stream, application/json",
}


def is_grok_com_model(model: str) -> bool:
    """Return True for grok-com-* models (unofficial grok.com backend)."""
    return model.lower().startswith("grok-com")


def _build_grok_com_headers(cookie: str, user_agent: Optional[str] = None) -> Dict[str, str]:
    """
    Build headers for grok.com requests.

    :param cookie:     Full Cookie header value from an authenticated grok.com session.
    :param user_agent: Per-session UA override; falls back to settings.browser.user_agent.
    """
    ua: str = user_agent if user_agent is not None else (settings.browser.user_agent or "")
    return {
        **_GROK_COM_BROWSER_STATIC,
        "User-Agent": ua,
        "Content-Type": "application/json",
        "Cookie": cookie,
    }


def _build_grok_com_payload(
        messages: List[ChatMessage],
        grok_model_id: str,
) -> Dict[str, Any]:
    """Convert OpenAI messages to a grok.com REST payload (single-turn, temporary conversation)."""
    # Collect system prompt and merge into first user message
    system_parts: List[str] = []
    user_parts: List[str] = []
    for msg in messages:
        if msg.role == "system":
            system_parts.append(msg.content)
        else:
            user_parts.append(msg.content)

    query = "\n\n".join(filter(None, system_parts + user_parts)) or "(empty)"

    msg_id = str(_uuid.uuid4())
    tmp_id = str(_uuid.uuid4())
    create_time = datetime.now(tz=_utc.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    return {
        "temporary": True,
        "modelName": grok_model_id,
        "message": {
            "id": msg_id,
            "temporaryId": tmp_id,
            "createTime": create_time,
            "messageType": "query",
            "query": query,
            "sender": "human",
            "fileAttachmentIds": [],
            "imageAttachments": [],
        },
        "fileAttachments": [],
        "imageAttachments": [],
        "disableSearch": False,
        "enableImageGeneration": False,
        "returnImageUrl": False,
        "enableTextToSpeech": False,
        "sendFinalMetadata": True,
    }


def _grok_com_error_from_status(status_code: int) -> str:
    if status_code == 401:
        return "grok.com auth failed — cookies expired. POST /login/grok-com with a fresh Cookie header."
    if status_code == 403:
        return "grok.com subscription required or cookies invalid."
    if status_code == 429:
        return "grok.com rate limit hit."
    return f"grok.com API returned HTTP {status_code}."


async def _grok_com_chat(
        chat_request: ChatRequest,
        grokcom_token: str,
        model: str,
) -> Any:
    """Route an OpenAI-compatible request to the unofficial grok.com web backend."""
    # Token stored as grokcom::<full-cookie-string>
    if not grokcom_token.startswith(GROK_COM_TOKEN_PREFIX):
        raise HTTPException(
            status_code=401,
            detail=(
                "grok-com-* models require grok.com cookies. "
                "POST {\"cookie\": \"...\"} to /login/grok-com first."
            ),
        )
    cookie = grokcom_token[len(GROK_COM_TOKEN_PREFIX):]

    session_ua, _ = _get_session_browser_info(grokcom_token)
    grok_model_id = GROK_COM_MODEL_MAP.get(model.lower(), "grok-3")
    payload = _build_grok_com_payload(chat_request.messages, grok_model_id)
    headers: Dict[str, str] = _build_grok_com_headers(cookie, user_agent=session_ua)
    timeout = httpx.Timeout(settings.proxy.request_timeout, connect=10.0)
    cid = f"chatcmpl-grokcom-{int(time.time())}-{secrets.token_hex(4)}"

    if chat_request.stream:
        return await _grok_com_stream(payload, headers, timeout, cid, model)
    return await _grok_com_sync(payload, headers, timeout, cid, model, grok_model_id)


async def _grok_com_stream(
        payload: Dict[str, Any],
        headers: Dict[str, str],
        timeout: httpx.Timeout,
        cid: str,
        model: str,
) -> StreamingResponse:
    """Streaming path for the grok.com backend → OpenAI SSE format."""

    async def _generate():  # noqa: ANN202
        try:
            async with httpx.AsyncClient(timeout=timeout) as hc:
                async with hc.stream("POST", GROK_COM_API_URL, json=payload, headers=headers) as sr:
                    if sr.status_code != 200:
                        err = _grok_com_error_from_status(sr.status_code)
                        yield f"data: {json.dumps({'error': {'message': err}})}\n\ndata: [DONE]\n\n".encode()
                        return

                    # Opening delta
                    open_chunk = json.dumps({
                        "id": cid, "object": "chat.completion.chunk",
                        "created": int(time.time()), "model": model,
                        "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}],
                    })
                    yield f"data: {open_chunk}\n\n".encode()

                    async for raw_line in sr.aiter_lines():
                        line = raw_line.strip()
                        if not line:
                            continue
                        # SSE lines may start with "data:" or be raw JSON — handle both
                        if line.startswith("data:"):
                            line = line[5:].strip()
                        elif line.startswith("{"):
                            obj = json.loads(line)
                        if line == "[DONE]":
                            break
                        try:
                            if "result" in obj:
                                result = obj["result"]
                                token = result.get("token", "")
                                is_end = result.get("isSoftStop", False) or result.get("isFinished", False)

                            if is_end:
                                stop_chunk = json.dumps({
                                    "id": cid, "object": "chat.completion.chunk",
                                    "created": int(time.time()), "model": model,
                                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                                })
                                yield f"data: {stop_chunk}\n\n".encode()
                                break

                            if token:
                                delta_chunk = json.dumps({
                                    "id": cid, "object": "chat.completion.chunk",
                                    "created": int(time.time()), "model": model,
                                    "choices": [{"index": 0, "delta": {"content": token}, "finish_reason": None}],
                                })
                                yield f"data: {delta_chunk}\n\n".encode()
                        except (json.JSONDecodeError, KeyError):
                            continue

                    yield b"data: [DONE]\n\n"

        except httpx.TimeoutException:
            yield b"data: {\"error\":{\"message\":\"grok.com timed out\"}}\n\ndata: [DONE]\n\n"
        except httpx.RequestError as exc:  # noqa: BLE001
            err_body = json.dumps({"error": {"message": f"grok.com connection error: {exc}"}})
            yield f"data: {err_body}\n\ndata: [DONE]\n\n".encode()

    return StreamingResponse(_generate(), media_type="text/event-stream")


async def _grok_com_sync(
        payload: Dict[str, Any],
        headers: Dict[str, str],
        timeout: httpx.Timeout,
        cid: str,
        model: str,
        grok_model_id: str,
) -> Dict[str, Any]:
    """Non-streaming path for the grok.com backend → OpenAI JSON format."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as hc:
            resp = await hc.post(GROK_COM_API_URL, json=payload, headers=headers)
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="grok.com API timed out")
    except httpx.RequestError as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"grok.com connection error: {exc}")

    if resp.status_code != 200:
        raise HTTPException(
            status_code=resp.status_code if resp.status_code in (401, 403, 429) else 502,
            detail=_grok_com_error_from_status(resp.status_code),
        )

    full_text = ""
    for raw_line in resp.text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("data:"):
            line = line[5:].strip()
        if line == "[DONE]":
            break
        try:
            obj = json.loads(line)
            result = obj.get("result", {})
            if result.get("isSoftStop") or result.get("isFinished"):
                break
            tok = result.get("token", "")
            if tok:
                full_text += tok
        except (json.JSONDecodeError, KeyError):
            continue

    logger.info(f"[grok-com] model={grok_model_id} response_len={len(full_text)}")
    return {
        "id": cid, "object": "chat.completion",
        "created": int(time.time()), "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": full_text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


async def _proxy_chat_to_anthropic(chat_request: ChatRequest, api_key: str) -> Any:
    """
    Convert an OpenAI ChatRequest (from /chat/completions) to Anthropic /v1/messages format
    and proxy it directly to api.anthropic.com.
    Used when Claude Code / OpenClaude sends claude-* models to /chat/completions with
    a real sk-ant-* key while ANTHROPIC_BASE_URL points to this proxy.
    """
    system_parts: List[str] = []
    anthropic_messages: List[Dict[str, str]] = []
    for msg in chat_request.messages:
        if msg.role == "system":
            system_parts.append(msg.content)
        else:
            anthropic_messages.append({"role": msg.role, "content": msg.content})

    # Anthropic requires at least one message
    if not anthropic_messages:
        anthropic_messages = [{"role": "user", "content": "(empty)"}]

    model = normalize_model_name(chat_request.model)
    anthropic_body: Dict[str, Any] = {
        "model": model,
        "messages": anthropic_messages,
        "max_tokens": chat_request.max_tokens or 8096,
        "stream": chat_request.stream,
    }
    if system_parts:
        anthropic_body["system"] = "\n\n".join(system_parts)
    if chat_request.temperature is not None:
        anthropic_body["temperature"] = chat_request.temperature

    fwd_headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    timeout = httpx.Timeout(settings.proxy.request_timeout, connect=10.0)
    logger.info(f"Routing /chat/completions→Anthropic (sk-ant-*, model={model}, stream={chat_request.stream})")

    if chat_request.stream:
        async def _stream() -> Any:
            async with httpx.AsyncClient(timeout=timeout) as ac:
                async with ac.stream(
                    "POST", f"{ANTHROPIC_API_BASE}/messages",
                    json=anthropic_body, headers=fwd_headers,
                ) as sr:
                    async for chunk in sr.aiter_bytes():
                        yield chunk
        return StreamingResponse(_stream(), media_type="text/event-stream")

    async with httpx.AsyncClient(timeout=timeout) as ac:
        ar = await ac.post(f"{ANTHROPIC_API_BASE}/messages", json=anthropic_body, headers=fwd_headers)

    if ar.status_code != 200:
        raise HTTPException(
            status_code=ar.status_code,
            detail=f"Anthropic API error: {ar.text[:300]}",
        )

    # Convert Anthropic response → OpenAI response format
    anth = ar.json()
    content_blocks = anth.get("content", [])
    text = "".join(b.get("text", "") for b in content_blocks if b.get("type") == "text")
    usage = anth.get("usage", {})
    return {
        "id": anth.get("id", f"chatcmpl-{int(time.time())}"),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": anth.get("model", model),
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": text},
            "finish_reason": anth.get("stop_reason", "stop"),
        }],
        "usage": {
            "prompt_tokens": usage.get("input_tokens", 0),
            "completion_tokens": usage.get("output_tokens", 0),
            "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
        },
    }


async def _proxy_to_anthropic_messages(request: Request, api_key: str) -> Response:
    """Forward /v1/messages raw to Anthropic's API (supports streaming)."""
    body = await request.body()

    fwd_headers: Dict[str, str] = {
        "x-api-key": api_key,
        "anthropic-version": request.headers.get("anthropic-version", "2023-06-01"),
        "content-type": "application/json",
    }
    for k, v in request.headers.items():
        kl = k.lower()
        if kl.startswith("anthropic-") and kl not in fwd_headers:
            fwd_headers[kl] = v

    try:
        req_json: Dict[str, Any] = json.loads(body)
        is_streaming: bool = bool(req_json.get("stream", False))
    except (json.JSONDecodeError, ValueError):
        is_streaming = False

    timeout = httpx.Timeout(settings.proxy.request_timeout, connect=10.0)

    try:
        if is_streaming:
            async def _stream() -> Any:
                async with httpx.AsyncClient(timeout=timeout) as _ac:
                    async with _ac.stream(
                            "POST",
                            f"{ANTHROPIC_API_BASE}/messages",
                            content=body,
                            headers=fwd_headers,
                    ) as sr:
                        async for chunk in sr.aiter_bytes():
                            yield chunk

            return StreamingResponse(_stream(), media_type="text/event-stream")

        async with httpx.AsyncClient(timeout=timeout) as ac:
            ar = await ac.post(
                f"{ANTHROPIC_API_BASE}/messages",
                content=body,
                headers=fwd_headers,
            )
        return Response(
            content=ar.content,
            status_code=ar.status_code,
            media_type=ar.headers.get("content-type", "application/json"),
        )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Anthropic API timed out")
    except httpx.RequestError as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Error communicating with Anthropic: {exc}")


_PLACEHOLDER_IDS = {"", "your_client_id_here", "your_github_client_id", "changeme", "none"}
_PLACEHOLDER_KEYS = {
    "", "your_xai_api_key_here", "your_twitter_consumer_key_here",
    "your_twitter_consumer_secret_here", "changeme", "none",
}

# ── Twitter / X.com OAuth 1.0a helpers ──────────────────────────────────────

TWITTER_OAUTH_TOKEN_PREFIX = "twitter::"

# Temporary in-memory store for OAuth 1.0a request tokens
# oauth_token → (oauth_token_secret, expires_at)
_twitter_request_tokens: Dict[str, tuple] = {}


def _oauth1_auth_header(
    method: str,
    url: str,
    consumer_key: str,
    consumer_secret: str,
    token: str = "",
    token_secret: str = "",
    extra_params: Optional[Dict[str, str]] = None,
) -> str:
    """
    Build an OAuth 1.0a HMAC-SHA1 Authorization header per RFC 5849.

    :param method:          HTTP method (GET/POST).
    :param url:             Base URL (no query string).
    :param consumer_key:    App consumer key.
    :param consumer_secret: App consumer secret.
    :param token:           OAuth token (empty for a request_token step).
    :param token_secret:    OAuth token secret (empty for a request_token step).
    :param extra_params:    Extra OAuth params to include in the signature
                            (e.g. {"oauth_callback": "...", "oauth_verifier": "..."}).
    :return:                Full OAuth ... header value.
    """
    def _pct(s: str) -> str:
        return _up.quote(str(s), safe="")

    oauth_params: Dict[str, str] = {
        "oauth_consumer_key":     consumer_key,
        "oauth_nonce":            secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp":        str(int(time.time())),
        "oauth_version":          "1.0",
    }
    if token:
        oauth_params["oauth_token"] = token
    if extra_params:
        oauth_params.update(extra_params)

    # Build the parameter string (RFC 5849 §3.4.1.3)
    sorted_pairs = sorted((_pct(k), _pct(v)) for k, v in oauth_params.items())
    param_str = "&".join(f"{k}={v}" for k, v in sorted_pairs)

    # Build the signature base string
    base_str = "&".join([_pct(method.upper()), _pct(url), _pct(param_str)])
    signing_key = f"{_pct(consumer_secret)}&{_pct(token_secret)}"

    sig = base64.b64encode(
        hmac.new(signing_key.encode("ascii"), base_str.encode("ascii"), hashlib.sha1).digest()
    ).decode("ascii")
    oauth_params["oauth_signature"] = sig

    # Only oauth_* params go into the Authorization header
    header_parts = ", ".join(
        f'{_pct(k)}="{_pct(v)}"'
        for k, v in sorted(oauth_params.items())
        if k.startswith("oauth_")
    )
    return f"OAuth {header_parts}"


def _get_session_browser_info(credential: str) -> tuple:
    """
    Return (user_agent, x_com_cookies) stored in the TokenData for *credential*.

    Both values default to None when not found; callers fall back to
    settings.browser.user_agent / settings.browser.x_com_cookies.
    O(n) over active tokens — fine for the small numbers expected in practice.
    """
    for td in TOKENS.values():
        if td.github_token == credential and td.user_info:
            return (
                td.user_info.get("user_agent"),
                td.user_info.get("x_com_cookies"),
            )
    return (None, None)


def _github_configured() -> bool:
    """Return True only when a real (non-placeholder) GitHub OAuth Client ID is set."""
    cid = (settings.github.client_id or "").strip().lower()
    return bool(cid and cid not in _PLACEHOLDER_IDS)


def _github_device_flow_help() -> str:
    """Return a human-friendly hint for GitHub Device Flow configuration issues."""
    return (
        "GitHub Device Flow is not configured correctly. Set GITHUB__CLIENT_ID to a real client ID "
        "(not a placeholder like 'your_client_id_here') and use a GitHub OAuth/OAuth-enabled app "
        "that supports Device Flow."
    )


def _xai_configured() -> bool:
    """Return True when a server-side xAI API key is configured."""
    key = (settings.xai.api_key or "").strip().lower()
    return bool(key and key not in _PLACEHOLDER_KEYS)


def _twitter_configured() -> bool:
    """Return True when Twitter/X.com app credentials are configured."""
    ck = (settings.twitter.consumer_key or "").strip().lower()
    cs = (settings.twitter.consumer_secret or "").strip().lower()
    return bool(ck and ck not in _PLACEHOLDER_KEYS and cs and cs not in _PLACEHOLDER_KEYS)


# ==================== WEB ROUTES ====================

@app.get("/", response_class=HTMLResponse)
@limiter.limit("30/minute")
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {"base_url": settings.base_url})


@app.head("/")
async def index_head():
    """Cleanly handle HEAD / — avoids 405 noises from health check probes."""
    return Response(status_code=200)


@app.head("/v1")
@app.head("/v1/")
@app.get("/v1/")
async def v1_root():
    """
    Handle HEAD/GET /v1/ probes sent by Claude Code and other OpenAI-compatible
    clients.  Returns 200 so the client knows the service is alive.
    """
    return Response(status_code=200)


@app.get("/dashboard", response_class=HTMLResponse)
@limiter.limit("30/minute")
async def dashboard(request: Request):
    return templates.TemplateResponse(
        request, "dashboard.html",
        {"base_url": settings.base_url, "tokens": len(TOKENS)},
    )


@app.get("/login", response_class=HTMLResponse)
@limiter.limit("20/minute")
async def login_page(request: Request):
    """Render the login page with all available auth methods."""
    login_url: Optional[str] = None
    if _github_configured():
        state = secrets.token_urlsafe(32)
        scopes = "+".join(settings.github.oauth_scopes)
        login_url = (
            f"https://github.com/login/oauth/authorize"
            f"?client_id={settings.github.client_id}"
            f"&redirect_uri={settings.github.redirect_uri}"
            f"&scope={scopes}"
            f"&state={state}"
        )
    return templates.TemplateResponse(
        request, "login.html",
        {
            "base_url": settings.base_url,
            "login_url": login_url,
            "twitter_configured": _twitter_configured(),
        },
    )


@app.get("/logout")
async def logout():
    """
    Server-side logout stub — clears the token from localStorage via JS redirect.
    The real work is done client-side in base.html's doLogout(); this endpoint
    just serves as a safe fallback when the user navigates directly to /logout.
    """
    # Token lives only in the browser's localStorage — nothing to invalidate server-side
    # here unless the caller passes a Bearer token (optional future enhancement).
    return RedirectResponse(url="/login", status_code=302)


@app.get("/login/success", response_class=HTMLResponse)
@limiter.limit("30/minute")
async def login_success(
    request: Request,
    message: str = "Authentication successful",
    token: str = "",
    expires_at: str = "",
    expires_in: Optional[int] = None,
):
    """Show the auth-success page (driven by query-string params set by the JS in login.html)."""
    if not token:
        raise HTTPException(status_code=400, detail="token query parameter is required")
    return templates.TemplateResponse(
        request, "auth_success.html",
        {
            "base_url": settings.base_url,
            "message": message,
            "token": token,
            "expires_at": expires_at or "never",
            "expires_in": expires_in,
        },
    )


@app.get("/auth/callback")
@limiter.limit("10/minute")
async def auth_callback(request: Request, code: str, state: str):
    """GitHub OAuth Web Flow callback — exchanges code for token and redirects to /login/success."""
    if not settings.github.client_id or not settings.github.client_secret:
        raise HTTPException(status_code=503, detail="Authentication service not configured")
    token_payload = {
        "client_id": settings.github.client_id,
        "client_secret": settings.github.client_secret,
        "code": code,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "https://github.com/login/oauth/access_token",
            data=token_payload,
            headers={"Accept": "application/json"},
        )
        if response.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to exchange code for token")
        result = response.json()
    if "access_token" not in result:
        raise HTTPException(status_code=400, detail="Authentication failed")

    # Fetch GitHub user info for display purposes
    user_info: Dict[str, Any] = {}
    try:
        async with httpx.AsyncClient(timeout=10.0) as uc:
            ur = await uc.get(
                "https://api.github.com/user",
                headers={"Authorization": f"Bearer {result['access_token']}", "Accept": "application/json"},
            )
            if ur.status_code == 200:
                user_info = ur.json()
    except Exception:  # noqa: BLE001
        pass

    api_token = f"cp-{int(time.time())}-{secrets.token_urlsafe(16)}"
    # Use the larger of GitHub's expires_in and our configured minimum.
    # GitHub Copilot OAuth tokens often expire after only 8h (28800s) — too short for daily use.
    github_expires_in = result.get("expires_in") or 0
    config_expires_in = settings.security.token_expiry_hours * 3600
    expires_in = max(github_expires_in, config_expires_in)
    expires_at_ts = time.time() + expires_in
    TOKENS[api_token] = TokenData(
        github_token=result["access_token"],
        created=time.time(),
        expires_at=expires_at_ts,
        user_info=user_info,
    )
    await token_manager.save_tokens()
    expires_at_str = datetime.fromtimestamp(expires_at_ts).isoformat()
    params = f"message=Authentication+successful&token={api_token}&expires_at={expires_at_str}&expires_in={expires_in}"
    return RedirectResponse(url=f"/login/success?{params}", status_code=302)


# ==================== LOGIN API ENDPOINTS ====================


@app.post("/login/twitter/bearer", response_model=AuthResponse)
@limiter.limit("10/minute")
async def login_twitter_bearer(request: Request, body: TwitterBearerLoginRequest) -> AuthResponse:
    """
    Handles Twitter login using a bearer token. This endpoint allows clients to register and
    authenticate using a bearer token that represents access to the Twitter API. The token
    provided is stored temporarily and is used for managing authenticated sessions.

    :param request: The incoming HTTP request object.
    :type request: Request
    :param body: The request body containing the Twitter bearer token.
    :type body: TwitterBearerLoginRequest
    :return: An AuthResponse object containing a success message, the generated
             API token, its expiration duration in seconds, and the timestamp when
             the token will expire.
    :rtype: AuthResponse
    :raises HTTPException: If neither a bearer token is provided by the client in
                           the request body nor a server-side default Twitter bearer
                           token is configured.
    """
    bearer = (body.bearer_token or "").strip() or (settings.twitter.bearer_token or "").strip()
    if not bearer:
        raise HTTPException(status_code=400, detail="No bearer token provided and no server-side TWITTER__BEARER_TOKEN configured.")

    api_token = f"cp-{int(time.time())}-{secrets.token_urlsafe(16)}"
    expires_in = settings.security.token_expiry_hours * 3600
    expires_at_ts = time.time() + expires_in
    TOKENS[api_token] = TokenData(
        github_token=bearer,
        created=time.time(),
        expires_at=expires_at_ts,
        user_info={"provider": "twitter_bearer"},
    )
    await token_manager.save_tokens()
    return AuthResponse(
        message="Twitter Bearer token registered",
        token=api_token,
        expires_in=expires_in,
        expires_at=datetime.fromtimestamp(expires_at_ts).isoformat(),
    )


@app.post("/login/grok-web", response_model=AuthResponse)
@limiter.limit("10/minute")
async def login_grok_web(
    request: Request,
    body: GrokWebLoginRequest,
    skip_validation: bool = False,
):
    """Register X.com cookies for the unofficial Grok Web backend."""
    auth_token = body.auth_token.strip()
    ct0 = body.ct0.strip()
    if not auth_token or not ct0:
        raise HTTPException(status_code=400, detail="Both auth_token and ct0 are required")

    # Resolve per-session UA and cookie overrides
    session_ua = (body.user_agent or "").strip() or None
    session_x_com_cookies = (body.x_com_cookies or "").strip() or None

    if not skip_validation:
        # Probe grok.x.com with a minimal payload to verify the cookies work
        probe_headers = _build_grok_web_headers(
            auth_token, ct0,
            user_agent=session_ua,
            x_com_cookies=session_x_com_cookies,
        )
        probe_payload = {
            "responses": [{"message": "hi", "sender": 1}],
            "grokModelOptionId": "grok-latest",
            "isDeepsearchEnabled": False,
            "isReasoningEnabled": False,
            "returnSearchResults": False,
            "returnCitations": False,
            "promptMetadata": {"promptSource": "NATURAL", "action": "INPUT"},
            "imageGenerationCount": 4,
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as hc:
                probe = await hc.post(
                    GROK_WEB_API_URL,
                    json=probe_payload,
                    headers=probe_headers,
                )
            if probe.status_code == 401:
                raise HTTPException(
                    status_code=401,
                    detail="Invalid X.com cookies — grok.x.com returned 401. Re-copy auth_token and ct0 from a fresh browser session, or use skip_validation=true.",
                )
            if probe.status_code not in (200, 400):
                raise HTTPException(
                    status_code=502,
                    detail=f"grok.x.com probe returned HTTP {probe.status_code}",
                )
        except HTTPException:
            raise
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=f"Could not reach grok.x.com: {exc}") from exc

    grokweb_token = f"{GROK_WEB_TOKEN_PREFIX}{auth_token}::{ct0}"
    api_token = f"cp-{int(time.time())}-{secrets.token_urlsafe(16)}"
    expires_in = settings.security.token_expiry_hours * 3600
    expires_at_ts = time.time() + expires_in
    grokweb_user_info: Dict[str, Any] = {
        "provider": "grok_web",
        "skip_validation": skip_validation,
    }
    if session_ua:
        grokweb_user_info["user_agent"] = session_ua
    if session_x_com_cookies:
        grokweb_user_info["x_com_cookies"] = session_x_com_cookies
    TOKENS[api_token] = TokenData(
        github_token=grokweb_token,
        created=time.time(),
        expires_at=expires_at_ts,
        user_info=grokweb_user_info,
    )
    await token_manager.save_tokens()
    logger.info(f"Grok Web login: token issued (skip_validation={skip_validation})")
    return AuthResponse(
        message="Grok Web cookies registered",
        token=api_token,
        expires_in=expires_in,
        expires_at=datetime.fromtimestamp(expires_at_ts).isoformat(),
    )


@app.post("/login/grok-com", response_model=AuthResponse)
@limiter.limit("10/minute")
async def login_grok_com(
    request: Request,
    body: GrokComLoginRequest,
    skip_validation: bool = False,
):
    """Register a grok.com Cookie header for the unofficial Grok.com backend."""
    cookie_str = body.cookie.strip()
    if not cookie_str:
        raise HTTPException(status_code=400, detail="cookie is required")

    session_ua = (body.user_agent or "").strip() or None

    if not skip_validation:
        probe_headers = _build_grok_com_headers(cookie_str, user_agent=session_ua)
        probe_payload = _build_grok_com_payload(
            [ChatMessage(role="user", content="hi")],
            "grok-3",
        )
        try:
            async with httpx.AsyncClient(timeout=15.0) as hc:
                probe = await hc.post(GROK_COM_API_URL, json=probe_payload, headers=probe_headers)
            if probe.status_code == 401:
                raise HTTPException(
                    status_code=401,
                    detail="Invalid grok.com cookies — returned 401. Re-copy the Cookie header from a fresh browser session, or use skip_validation=true.",
                )
            if probe.status_code not in (200, 400):
                raise HTTPException(
                    status_code=502,
                    detail=f"grok.com probe returned HTTP {probe.status_code}",
                )
        except HTTPException:
            raise
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=f"Could not reach grok.com: {exc}") from exc

    grokcom_token = f"{GROK_COM_TOKEN_PREFIX}{cookie_str}"
    api_token = f"cp-{int(time.time())}-{secrets.token_urlsafe(16)}"
    expires_in = settings.security.token_expiry_hours * 3600
    expires_at_ts = time.time() + expires_in
    grokcom_user_info: Dict[str, Any] = {
        "provider": "grok_com",
        "skip_validation": skip_validation,
    }
    if session_ua:
        grokcom_user_info["user_agent"] = session_ua
    TOKENS[api_token] = TokenData(
        github_token=grokcom_token,
        created=time.time(),
        expires_at=expires_at_ts,
        user_info=grokcom_user_info,
    )
    await token_manager.save_tokens()
    logger.info(f"Grok.com login: token issued (skip_validation={skip_validation})")
    return AuthResponse(
        message="grok-com cookies registered",
        token=api_token,
        expires_in=expires_in,
        expires_at=datetime.fromtimestamp(expires_at_ts).isoformat(),
    )


# ==================== X.COM / TWITTER OAUTH 1.0a WEB FLOW ====================

@app.get("/login/twitter")
@limiter.limit("10/minute")
async def login_twitter_oauth(request: Request):  # noqa: ARG001
    """
    Initiate X.com OAuth 1.0a web flow.

    Step 1: Exchange consumer credentials for a request token, then redirect
    the user to https://api.twitter.com/oauth/authenticate to authorize.

    Requires TWITTER__CONSUMER_KEY and TWITTER__CONSUMER_SECRET in config.env.
    """
    if not _twitter_configured():
        raise HTTPException(
            status_code=503,
            detail=(
                "X.com OAuth is not configured. "
                "Set TWITTER__CONSUMER_KEY and TWITTER__CONSUMER_SECRET in "
                "/etc/copilot-api-proxy/config.env, then register "
                f"{settings.twitter.callback_uri} as the OAuth callback URL "
                "in your Twitter App settings."
            ),
        )

    callback_uri = settings.twitter.callback_uri
    auth_header = _oauth1_auth_header(
        method="POST",
        url="https://api.twitter.com/oauth/request_token",
        consumer_key=settings.twitter.consumer_key or "",
        consumer_secret=settings.twitter.consumer_secret or "",
        extra_params={"oauth_callback": callback_uri},
    )

    try:
        async with httpx.AsyncClient(timeout=15.0) as hc:
            _tw_req_headers: Dict[str, str] = {
                "Authorization": auth_header,
                "User-Agent": settings.browser.user_agent,
            }
            if settings.browser.x_com_cookies:
                _tw_req_headers["Cookie"] = settings.browser.x_com_cookies
            resp = await hc.post(
                "https://api.twitter.com/oauth/request_token",
                headers=_tw_req_headers,
                data={"oauth_callback": callback_uri},
            )
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Could not reach Twitter API: {exc}") from exc

    if resp.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Twitter request_token failed (HTTP {resp.status_code}): {resp.text[:200]}",
        )

    resp_params = dict(_up.parse_qsl(resp.text))
    if resp_params.get("oauth_callback_confirmed") != "true":
        raise HTTPException(
            status_code=502,
            detail="Twitter did not confirm the OAuth callback URL. "
                   "Verify the callback URI matches the one registered in the Twitter App.",
        )

    oauth_token = resp_params.get("oauth_token", "")
    oauth_token_secret = resp_params.get("oauth_token_secret", "")
    if not oauth_token or not oauth_token_secret:
        raise HTTPException(status_code=502, detail="Twitter did not return a request token.")

    # Store request token secret for the callback (15-minute TTL)
    _twitter_request_tokens[oauth_token] = (oauth_token_secret, time.time() + 900)

    # Redirect user to Twitter for authorization
    auth_url = f"https://api.twitter.com/oauth/authenticate?oauth_token={_up.quote(oauth_token, safe='')}"
    logger.info(f"Twitter OAuth: redirecting to {auth_url}")
    return RedirectResponse(url=auth_url, status_code=302)


@app.get("/auth/twitter/callback")
@limiter.limit("10/minute")
async def auth_twitter_callback(
    request: Request,  # noqa: ARG001
    oauth_token: str,
    oauth_verifier: str,
):
    """
    X.com OAuth 1.0a callback — exchange the temporary verifier for a
    permanent access token and issue a cp-*`` proxy token.
    """
    if not _twitter_configured():
        raise HTTPException(status_code=503, detail="X.com OAuth is not configured.")

    # Retrieve the request token secret (needed to sign the access_token request)
    stored = _twitter_request_tokens.pop(oauth_token, None)
    if stored is None:
        raise HTTPException(
            status_code=400,
            detail="OAuth request token not found or expired. Please start the login flow again.",
        )
    token_secret, exp = stored
    if time.time() > exp:
        raise HTTPException(
            status_code=400,
            detail="OAuth request token expired. Please start the login flow again.",
        )

    # Purge other stale request tokens opportunistically
    now = time.time()
    stale = [k for k, (_, e) in _twitter_request_tokens.items() if e < now]
    for k in stale:
        del _twitter_request_tokens[k]

    auth_header = _oauth1_auth_header(
        method="POST",
        url="https://api.twitter.com/oauth/access_token",
        consumer_key=settings.twitter.consumer_key or "",
        consumer_secret=settings.twitter.consumer_secret or "",
        token=oauth_token,
        token_secret=token_secret,
        extra_params={"oauth_verifier": oauth_verifier},
    )

    try:
        async with httpx.AsyncClient(timeout=15.0) as hc:
            _tw_acc_headers: Dict[str, str] = {
                "Authorization": auth_header,
                "User-Agent": settings.browser.user_agent,
            }
            if settings.browser.x_com_cookies:
                _tw_acc_headers["Cookie"] = settings.browser.x_com_cookies
            resp = await hc.post(
                "https://api.twitter.com/oauth/access_token",
                headers=_tw_acc_headers,
                data={"oauth_verifier": oauth_verifier},
            )
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Could not reach Twitter API: {exc}") from exc

    if resp.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail=f"Twitter access_token exchange failed (HTTP {resp.status_code}): {resp.text[:200]}",
        )

    access_params = dict(_up.parse_qsl(resp.text))
    access_token = access_params.get("oauth_token", "")
    access_token_secret = access_params.get("oauth_token_secret", "")
    screen_name = access_params.get("screen_name", "unknown")
    user_id = access_params.get("user_id", "")

    if not access_token or not access_token_secret:
        raise HTTPException(status_code=400, detail="Twitter did not return an access token.")

    # Store as twitter::<token>::<secret> in the github_token field
    stored_credential = f"{TWITTER_OAUTH_TOKEN_PREFIX}{access_token}::{access_token_secret}"
    api_token = f"cp-{int(time.time())}-{secrets.token_urlsafe(16)}"
    expires_in = settings.security.token_expiry_hours * 3600
    expires_at_ts = time.time() + expires_in
    TOKENS[api_token] = TokenData(
        github_token=stored_credential,
        created=time.time(),
        expires_at=expires_at_ts,
        user_info={
            "provider": "twitter_oauth",
            "screen_name": screen_name,
            "user_id": user_id,
        },
    )
    await token_manager.save_tokens()
    logger.info(f"Twitter OAuth login: token issued (screen_name=@{screen_name})")

    expires_at_str = datetime.fromtimestamp(expires_at_ts).isoformat()
    qs = _up.urlencode({
        "message": f"X.com OAuth successful — welcome @{screen_name}!",
        "token": api_token,
        "expires_at": expires_at_str,
        "expires_in": str(expires_in),
    })
    return RedirectResponse(url=f"/login/success?{qs}", status_code=302)

@app.get("/login/device", response_class=HTMLResponse)
@limiter.limit("10/minute")
async def login_device_flow(request: Request):
    """Initiate GitHub Device Flow and render the device_flow.html page."""
    if not _github_configured():
        raise HTTPException(status_code=503, detail=_github_device_flow_help())
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            "https://github.com/login/device/code",
            data={"client_id": settings.github.client_id, "scope": " ".join(settings.github.oauth_scopes)},
            headers={"Accept": "application/json"},
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="GitHub Device Flow initiation failed")
    data = resp.json()
    if "error" in data:
        raise HTTPException(status_code=400, detail=data.get("error_description", data["error"]))
    poll_url = f"/login/device/poll?device_code={data['device_code']}"
    return templates.TemplateResponse(
        request, "device_flow.html",
        {
            "base_url": settings.base_url,
            "verification_uri": data.get("verification_uri", "https://github.com/login/device"),
            "user_code": data.get("user_code", ""),
            "device_code": data.get("device_code", ""),
            "expires_in": data.get("expires_in", 900),
            "interval": data.get("interval", 5),
            "poll_url": poll_url,
        },
    )


@app.get("/login/device/poll")
@limiter.limit("60/minute")
async def device_flow_poll(request: Request, device_code: str):
    """Poll GitHub Device Flow endpoint — returns {token, status}.
    :type request: Request
    :type device_code: str
    """
    if not _github_configured():
        raise HTTPException(status_code=503, detail=_github_device_flow_help())
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            "https://github.com/login/oauth/access_token",
            data={
                "client_id": settings.github.client_id,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
            headers={"Accept": "application/json"},
        )
    if resp.status_code != 200:
        return {"status": "error", "detail": f"GitHub returned {resp.status_code}"}
    result = resp.json()

    if "error" in result:
        err = result["error"]
        if err in ("authorization_pending", "slow_down"):
            return {"status": err}
        return JSONResponse(status_code=400, content={"error": {"message": result.get("error_description", err)}})

    if "access_token" not in result:
        return {"status": "pending"}

    # Token granted — store it
    user_info: Dict[str, Any] = {}
    try:
        async with httpx.AsyncClient(timeout=10.0) as uc:
            ur = await uc.get(
                "https://api.github.com/user",
                headers={"Authorization": f"Bearer {result['access_token']}", "Accept": "application/json"},
            )
            if ur.status_code == 200:
                user_info = ur.json()
    except Exception as e:  # noqa: BLE001
        print(e.with_traceback(e.__traceback__))
        pass

    api_token = f"cp-{int(time.time())}-{secrets.token_urlsafe(16)}"
    # Use the larger of GitHub's expires_in and our configured minimum.
    # GitHub Copilot OAuth tokens often expire after only 8h (28800s) — too short for daily use.
    github_expires_in = result.get("expires_in") or 0
    config_expires_in = settings.security.token_expiry_hours * 3600
    expires_in = max(github_expires_in, config_expires_in)
    expires_at_ts = time.time() + expires_in
    TOKENS[api_token] = TokenData(
        github_token=result["access_token"],
        created=time.time(),
        expires_at=expires_at_ts,
        user_info=user_info,
    )
    await token_manager.save_tokens()
    logger.info(f"Device Flow login: token issued (user={user_info.get('login', '?')})")
    return {
        "token": api_token,
        "expires_in": expires_in,
        "expires_at": datetime.fromtimestamp(expires_at_ts).isoformat(),
    }


# ==================== AUTH DEPENDENCY ====================

# All raw-credential prefixes that are accepted without a TOKENS lookup.
_raw_prefixes = (
    "xai-", "gsk_",        # xAI / Grok API keys
    "sk-ant-",             # Anthropic API keys
    "gho_",                # GitHub OAuth tokens (from Device Flow / Web OAuth)
    GROK_WEB_TOKEN_PREFIX,
    GROK_COM_TOKEN_PREFIX,
    TWITTER_OAUTH_TOKEN_PREFIX,
)

@limiter.limit(f"{settings.security.rate_limit_requests}/minute")
async def verify_token(
        request: Request,
        http_auth: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> str:
    """Extract and validate a token from Authorization: Bearer OR x-api-key header.
    Returns the backend credential string (github_token for cp-* tokens, raw token otherwise).
    """
    token: Optional[str] = None
    if http_auth is not None:
        token = http_auth.credentials  # credentials attr is str per HTTPAuthorizationCredentials
    if not token:
        token = request.headers.get("x-api-key") or None
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Authorization required (Authorization: Bearer <token> or x-api-key: <token>)",
        )

    # Raw credentials accepted without TOKENS lookup
    if token.startswith(_raw_prefixes):
        return token

    # Proxy cp-* token: look up in token store
    if token not in TOKENS:
        logger.warning(f"Invalid token attempt from {get_remote_address(request)}")
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token — get a fresh token at /login",
            headers={"WWW-Authenticate": f'Bearer realm="{settings.base_url}/login"'},
        )

    token_data = TOKENS[token]
    if token_data.expires_at and token_data.expires_at < time.time():
        del TOKENS[token]
        await token_manager.save_tokens()
        raise HTTPException(
            status_code=401,
            detail="Token has expired — re-authenticate at /login",
            headers={"WWW-Authenticate": f'Bearer realm="{settings.base_url}/login"'},
        )

    token_data.last_used = time.time()
    if int(time.time()) % 300 == 0:
        await token_manager.save_tokens()

    return token_data.github_token

# ==================== TOKEN MANAGEMENT ENDPOINTS ====================

class TokenListItem(BaseModel):
    token_id: str
    provider: str
    created: str
    last_used: Optional[str]
    expires_at: Optional[str]
    expired: bool


class TokenListResponse(BaseModel):
    total: int
    tokens: List[TokenListItem]


class ClearResult(BaseModel):
    cleared: int
    remaining: int
    message: str


def _token_list_item(token_id: str, data: TokenData) -> TokenListItem:
    now = time.time()
    provider = "github"
    gh = data.github_token or ""
    if gh.startswith(GROK_WEB_TOKEN_PREFIX):
        provider = "grok-web"
    elif gh.startswith(GROK_COM_TOKEN_PREFIX):
        provider = "grok-com"
    elif gh.startswith(TWITTER_OAUTH_TOKEN_PREFIX):
        provider = "twitter_oauth"
    elif gh.startswith("xai-") or gh.startswith("gsk_"):
        provider = "xai"
    elif gh.startswith("sk-ant-"):
        provider = "anthropic"
    elif data.user_info:
        provider = data.user_info.get("provider", "github")
    return TokenListItem(
        token_id=token_id,
        provider=provider,
        created=datetime.fromtimestamp(data.created).isoformat(),
        last_used=datetime.fromtimestamp(data.last_used).isoformat() if data.last_used else None,
        expires_at=datetime.fromtimestamp(data.expires_at).isoformat() if data.expires_at else None,
        expired=bool(data.expires_at and data.expires_at < now),
    )


@app.get("/admin/tokens", response_model=TokenListResponse)
@limiter.limit("30/minute")
async def list_tokens(
        request: Request,  # noqa: ARG001
        _auth: Optional[str] = Depends(verify_token),
):
    """List all stored proxy tokens (no raw credentials exposed)."""
    items = [_token_list_item(tid, td) for tid, td in TOKENS.items()]
    return TokenListResponse(total=len(items), tokens=items)


@app.delete("/admin/tokens", response_model=ClearResult)
@limiter.limit("10/minute")
async def clear_all_tokens(
        request: Request,  # noqa: ARG001
        _auth: Optional[str] = Depends(verify_token),
):
    """Revoke and delete ALL stored proxy tokens."""
    count = len(TOKENS)
    TOKENS.clear()
    await token_manager.save_tokens()
    logger.warning(f"All {count} tokens cleared by authenticated request")
    return ClearResult(cleared=count, remaining=0, message=f"✅ Cleared {count} token(s).")


@app.delete("/admin/tokens/expired", response_model=ClearResult)
@limiter.limit("10/minute")
async def clear_expired_tokens(
        request: Request,  # noqa: ARG001
        _auth: Optional[str] = Depends(verify_token),
):
    """Delete only tokens that have already expired."""
    now = time.time()
    expired = [tid for tid, td in TOKENS.items() if td.expires_at and td.expires_at < now]
    for tid in expired:
        del TOKENS[tid]
    if expired:
        await token_manager.save_tokens()
    logger.info(f"Cleared {len(expired)} expired token(s)")
    return ClearResult(
        cleared=len(expired),
        remaining=len(TOKENS),
        message=f"✅ Cleared {len(expired)} expired token(s). {len(TOKENS)} active remaining.",
    )


@app.delete("/admin/tokens/{token_id}", response_model=ClearResult)
@limiter.limit("30/minute")
async def revoke_token(
        request: Request,  # noqa: ARG001
        token_id: str,
        _auth: Optional[str] = Depends(verify_token),
) -> ClearResult:
    """Revoke a single token by its cp-* ID."""
    if token_id not in TOKENS:
        raise HTTPException(status_code=404, detail=f"Token '{token_id}' not found.")
    del TOKENS[token_id]
    await token_manager.save_tokens()
    logger.info(f"Token {token_id[:20]}… revoked")
    return ClearResult(cleared=1, remaining=len(TOKENS), message="✅ Token revoked.")


@app.post("/v1/chat/completions")
@limiter.limit(f"{settings.security.rate_limit_requests}/minute")
async def chat_completions(
        request: Request,
        chat_request: ChatRequest,
        raw_token: Optional[str] = Depends(verify_token)
):
    """OpenAI-compatible endpoint that routes to Copilot, xAI Grok, Grok web, or Grok.com backend."""
    if raw_token is None:
        raise HTTPException(status_code=401, detail="Authorization required")

    model = normalize_model_name(chat_request.model)

    # ── Anthropic sk-ant-* key → convert OpenAI format → Anthropic /v1/messages ──
    # Claude Code / OpenClaude may send claude-* models to /chat/completions with the
    # real sk-ant-* key when ANTHROPIC_BASE_URL points to this proxy.
    if raw_token.startswith("sk-ant-"):
        return await _proxy_chat_to_anthropic(chat_request, raw_token)

    # ── Grok.com backend (unofficial, grok.com) ────────────────────────────
    if is_grok_com_model(model):
        if not raw_token.startswith(GROK_COM_TOKEN_PREFIX):
            raise HTTPException(
                status_code=401,
                detail=(
                    "grok-com-* models require grok.com cookies. "
                    "POST {\"cookie\": \"...\"} to /login/grok-com first."
                ),
            )
        return await _grok_com_chat(chat_request, raw_token, model)

    # ── Grok web backend (unofficial, grok.x.com) ─────────────────────────
    if is_grok_web_model(model):
        if not raw_token.startswith(GROK_WEB_TOKEN_PREFIX):
            raise HTTPException(
                status_code=401,
                detail=(
                    "grok-web-* models require Grok web cookies. "
                    "POST {\"auth_token\": \"...\", \"ct0\": \"...\"} to /login/grok-web first."
                ),
            )
        return await _grok_web_chat(chat_request, raw_token, model)

    is_grok = is_grok_model(model)

    # For Grok routes: prefer client-supplied xAI key, fall back to server-side key
    effective_token = raw_token
    if is_grok and not (raw_token.startswith("xai-") or raw_token.startswith("gsk_")):
        if _xai_configured():
            effective_token = settings.xai.api_key or ""
        else:
            raise HTTPException(
                status_code=503,
                detail=(
                    f"Model '{model}' requires an xAI API key. "
                    "Set XAI__API_KEY in /etc/copilot-api-proxy/config.env "
                    "(get yours at https://console.x.ai) or pass your own xai-… key as the Bearer token."
                ),
            )

    # Validate request size
    content_length = len(json.dumps(chat_request.model_dump()))
    if content_length > settings.security.max_request_size:
        raise HTTPException(status_code=413,
                            detail=f"Request too large: {content_length} bytes (max: {settings.security.max_request_size})")

    if chat_request.max_tokens and chat_request.max_tokens > settings.security.max_tokens_per_request:
        raise HTTPException(status_code=400,
                            detail=f"max_tokens too large: {chat_request.max_tokens} (max: {settings.security.max_tokens_per_request})")

    # Copilot backend: exchange raw GitHub OAuth/PAT token → short-lived Copilot API token
    if not is_grok:
        effective_token = await _get_copilot_token(effective_token)

    headers = await get_backend_headers(effective_token, is_grok)

    # Resolve alias model names (e.g. claude-sonnet-4-6) → real Copilot model IDs
    copilot_model = resolve_copilot_model(model) if not is_grok else model
    if copilot_model != model:
        logger.info(f"Model alias resolved: {model} → {copilot_model}")

    copilot_request: Dict[str, Any] = {
        "model": copilot_model,
        "messages": [msg.model_dump() for msg in chat_request.messages],
        "stream": chat_request.stream,
    }
    if chat_request.max_tokens:
        copilot_request["max_tokens"] = chat_request.max_tokens
    if chat_request.temperature is not None:
        copilot_request["temperature"] = chat_request.temperature

    timeout = httpx.Timeout(settings.proxy.request_timeout, connect=10.0)

    base_url = settings.xai.api_base if is_grok else settings.proxy.copilot_api_base

    start_time = time.time()

    # ── Streaming path ─────────────────────────────────────────────────────────
    if chat_request.stream:
        async def _generate():  # noqa: ANN202
            try:
                async with httpx.AsyncClient(timeout=timeout) as sc:
                    async with sc.stream(
                        "POST",
                        f"{base_url}/chat/completions",
                        json=copilot_request,
                        headers=headers,
                    ) as sr:
                        if sr.status_code != 200:
                            err_text = await sr.aread()
                            error_body = json.dumps({
                                "error": {
                                    "message": f"Backend error: {err_text[:200].decode(errors='replace')}",
                                    "type": "backend_error",
                                    "code": sr.status_code,
                                }
                            })
                            yield f"data: {error_body}\n\n".encode()
                            yield b"data: [DONE]\n\n"
                            return
                        async for chunk in sr.aiter_bytes():
                            yield chunk
            except httpx.TimeoutException:
                yield b"data: {\"error\":{\"message\":\"Backend timed out\"}}\n\ndata: [DONE]\n\n"
            except httpx.RequestError as exc:  # noqa: BLE001
                err = json.dumps({"error": {"message": f"Backend connection error: {exc}"}})
                yield f"data: {err}\n\ndata: [DONE]\n\n".encode()

        if settings.logging_config.log_requests:
            logger.info(f"Streaming request: model={model}, backend={'xAI Grok' if is_grok else 'GitHub Copilot'}")
        return StreamingResponse(_generate(), media_type="text/event-stream")

    # ── Non-streaming path ─────────────────────────────────────────────────────
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                json=copilot_request,
                headers=headers,
            )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Request to backend timed out")
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="Error communicating with backend")

    request_duration = time.time() - start_time
    if settings.logging_config.log_requests:
        logger.info(
            f"Request completed: status={response.status_code}, duration={request_duration:.2f}s, "
            f"model={model}, backend={'xAI Grok' if is_grok else 'GitHub Copilot'}"
        )

    if response.status_code != 200:
        if response.status_code == 401:
            raise HTTPException(status_code=401, detail="Invalid or expired token. Please re-authenticate.")
        if response.status_code == 429:
            raise HTTPException(status_code=429, detail="Rate limit exceeded.")
        raise HTTPException(status_code=response.status_code, detail=f"Backend error: {response.text[:200]}")

    return response.json()


@app.post("/v1/messages")
@limiter.limit(f"{settings.security.rate_limit_requests}/minute")
async def claude_messages(
        request: Request,
        claude_req: ClaudeRequest,
        raw_token: Optional[str] = Depends(verify_token)
):
    """
    Anthropic /v1/messages endpoint.
    - sk-ant-* tokens → forwarded raw to api.anthropic.com (Claude Code / ANTHROPIC_AUTH_TOKEN)
    - cp-* / xai-* tokens → converted to OpenAI format and routed via chat_completions
    """
    # Anthropic direct pass-through (e.g., Claude Code with ANTHROPIC_AUTH_TOKEN)
    if raw_token and raw_token.startswith("sk-ant-"):
        logger.info(f"Forwarding /v1/messages to Anthropic API (sk-ant-* token, model={claude_req.model})")
        return await _proxy_to_anthropic_messages(request, raw_token)

    openai_messages = []
    if claude_req.system:
        openai_messages.append({"role": "system", "content": claude_req.system})
    openai_messages.extend([{"role": msg.role, "content": msg.content} for msg in claude_req.messages])

    openai_req = ChatRequest(
        model=normalize_model_name(claude_req.model),
        messages=openai_messages,
        stream=claude_req.stream,
        max_tokens=claude_req.max_tokens,
        temperature=claude_req.temperature,
    )
    return await chat_completions(request, openai_req, raw_token)


@app.get("/v1/models")
@limiter.limit("60/minute")
async def list_models(
        request: Request,  # noqa: ARG001 - required by @limiter.limit
        http_auth: Optional[HTTPAuthorizationCredentials] = Depends(security),
):
    """
    List available models.
    - With a valid cp-* token → live fetch from GitHub Copilot API and static Grok models
    - With a xai-*/gsk_* token → live fetch from xAI + static Copilot fallback
    - Without a token → returns a comprehensive static list
    """
    static_copilot_models: List[Dict[str, Any]] = [
        {"id": "gpt-4o", "object": "model", "created": 1715367049, "owned_by": "openai"},
        {"id": "gpt-4o-mini", "object": "model", "created": 1721172717, "owned_by": "openai"},
        {"id": "gpt-4", "object": "model", "created": 1677610602, "owned_by": "openai"},
        {"id": "gpt-3.5-turbo", "object": "model", "created": 1677610602, "owned_by": "openai"},
        {"id": "o1-preview", "object": "model", "created": 1725648897, "owned_by": "openai"},
        {"id": "o1-mini", "object": "model", "created": 1725648897, "owned_by": "openai"},
        {"id": "claude-sonnet-4", "object": "model", "created": 1746057600, "owned_by": "anthropic"},
        {"id": "claude-sonnet-4.5", "object": "model", "created": 1748736000, "owned_by": "anthropic"},
        {"id": "claude-sonnet-4.6", "object": "model", "created": 1756512000, "owned_by": "anthropic"},
        {"id": "claude-opus-4.5", "object": "model", "created": 1748736000, "owned_by": "anthropic"},
        {"id": "claude-opus-4.6", "object": "model", "created": 1756512000, "owned_by": "anthropic"},
        {"id": "claude-haiku-4.5", "object": "model", "created": 1748736000, "owned_by": "anthropic"},
    ]
    static_grok_models: List[Dict[str, Any]] = [
        {"id": "grok-beta", "object": "model", "created": 1735689600, "owned_by": "xai"},
        {"id": "grok-2-1212", "object": "model", "created": 1735689600, "owned_by": "xai"},
        {"id": "grok-3", "object": "model", "created": 1743552000, "owned_by": "xai"},
        {"id": "grok-3-mini", "object": "model", "created": 1743552000, "owned_by": "xai"},
        # Grok web backend (unofficial — requires X.com Grok Pro cookies via /login/grok-web)
        {"id": "grok-web", "object": "model", "created": 1743552000, "owned_by": "xai-web"},
        {"id": "grok-web-3", "object": "model", "created": 1743552000, "owned_by": "xai-web"},
        {"id": "grok-web-3-mini", "object": "model", "created": 1743552000, "owned_by": "xai-web"},
        {"id": "grok-web-2", "object": "model", "created": 1735689600, "owned_by": "xai-web"},
        # Grok.com backend (unofficial — requires grok.com browser cookies via /login/grok-com)
        {"id": "grok-com", "object": "model", "created": 1743552000, "owned_by": "xai-com"},
        {"id": "grok-com-3", "object": "model", "created": 1743552000, "owned_by": "xai-com"},
        {"id": "grok-com-3-mini", "object": "model", "created": 1743552000, "owned_by": "xai-com"},
        {"id": "grok-com-2", "object": "model", "created": 1735689600, "owned_by": "xai-com"},
    ]

    models: List[Dict[str, Any]] = []
    token: Optional[str] = http_auth.credentials if http_auth else None
    timeout = httpx.Timeout(10.0, connect=5.0)

    if token and (token.startswith("xai-") or token.startswith("gsk_")):
        # xAI token: fetch live Grok models
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(
                    f"{settings.xai.api_base}/models",
                    headers={"Authorization": f"Bearer {token}"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    models = data.get("data", [])
                    logger.info(f"Fetched {len(models)} Grok models live from xAI")
        except Exception as exc:  # noqa: BLE001 – live xAI fetch is best-effort
            logger.warning(f"xAI live models fetch failed ({exc}), using static Grok list")
        if not models:
            models = static_grok_models
        models += static_copilot_models

    elif token and token in TOKENS:
        # Copilot token: exchange GitHub OAuth → Copilot API token, then fetch live models
        github_token = TOKENS[token].github_token
        try:
            copilot_api_token = await _get_copilot_token(github_token)
        except HTTPException:
            copilot_api_token = github_token  # fallback to static list below
        copilot_headers = await get_backend_headers(copilot_api_token, is_grok=False)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(
                    f"{settings.proxy.copilot_api_base}/models",
                    headers=copilot_headers,
                )
                if resp.status_code == 200:
                    data: Dict[str, Any] = resp.json()
                    raw = data.get("data", data if isinstance(data, list) else [])
                    # Normalize to OpenAI schema
                    for m in raw:
                        models.append({
                            "id": m.get("id") or m.get("name") or m.get("model_id", "unknown"),
                            "object": "model",
                            "created": m.get("created", int(time.time())),
                            "owned_by": m.get("owned_by") or m.get("vendor", "github"),
                        })
                    logger.info(f"Fetched {len(models)} Copilot models live from GitHub")
        except Exception as exc:  # noqa: BLE001 – live Copilot fetch is best-effort
            logger.warning(f"Copilot live models fetch failed ({exc}), using static list")
        if not models:
            models = list(static_copilot_models)
        # Always include static Claude models so clients (e.g. openclaude) can resolve
        # a Claude model even when the live Copilot account only returns GPT models.
        _static_ids = {m["id"] for m in models}
        for m in static_copilot_models:
            if m["id"] not in _static_ids:
                models.append(m)
        models += static_grok_models

    else:
        # No/unknown token → static list
        models = static_copilot_models + static_grok_models

    # Deduplicate by id (preserve first occurrence)
    seen: set = set()
    unique_models = []
    for m in models:
        if m["id"] not in seen:
            seen.add(m["id"])
            unique_models.append(m)

    return {"object": "list", "data": unique_models}


@app.get("/health", response_model=HealthResponse)
async def health_check():
    uptime = time.time() - SERVICE_START_TIME
    return HealthResponse(
        status="healthy",
        timestamp=datetime.now().isoformat(),
        version=settings.version,
        active_tokens=len(TOKENS),
        service="copilot-api-proxy",
        uptime_seconds=uptime,
        environment=settings.environment
    )


# ==================== BACKGROUND TASKS & LIFESPAN (unchanged) ====================

async def periodic_cleanup():
    while True:
        try:
            await asyncio.sleep(settings.storage.cleanup_interval_hours * 3600)
            cleaned_count = await token_manager.cleanup_expired_tokens()
            if cleaned_count > 0:
                logger.info(f"Periodic cleanup: removed {cleaned_count} expired tokens")
        except Exception as e:  # noqa: BLE001 – cleanup loop must keep running
            logger.error(f"Error in periodic cleanup: {e}")


# ==================== COMPATIBILITY ALIAS ROUTES (no /v1 prefix) ====================
# Claude Code and some OpenAI clients call /chat/completions or /messages directly.

@app.post("/chat/completions")
@limiter.limit(f"{settings.security.rate_limit_requests}/minute")
async def chat_completions_alias(
        request: Request,
        chat_request: ChatRequest,
        raw_token: Optional[str] = Depends(verify_token),
):
    """Alias for /v1/chat/completions — clients that omit the /v1 prefix."""
    return await chat_completions(request, chat_request, raw_token)


@app.post("/messages")
@limiter.limit(f"{settings.security.rate_limit_requests}/minute")
async def claude_messages_alias(
        request: Request,
        claude_req: ClaudeRequest,
        raw_token: Optional[str] = Depends(verify_token),
):
    """Alias for /v1/messages — Anthropic clients that omit the /v1 prefix."""
    return await claude_messages(request, claude_req, raw_token)


@app.get("/models")
async def list_models_alias(
    request: Request,
    http_auth: Optional[HTTPAuthorizationCredentials] = Depends(security),
):
    """Alias for /v1/models — clients that omit the /v1 prefix."""
    return await list_models(request, http_auth)


# ==================== ERROR HANDLERS ====================

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    error_response = {
        "error": {"message": exc.detail, "type": "http_exception", "code": exc.status_code},
        "timestamp": datetime.now().isoformat(),
        "path": str(request.url)
    }
    if exc.status_code >= 500:
        logger.error(f"Server error {exc.status_code}: {exc.detail}")
    elif exc.status_code not in [401, 403]:
        logger.warning(f"Client error {exc.status_code}: {exc.detail}")
    return JSONResponse(status_code=exc.status_code, content=error_response)


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled exception: {exc}")
    error_detail: Dict[str, Any] = {
        "message": "An unexpected error occurred",
        "type": "internal_error",
        "code": 500,
    }
    if settings.debug:
        error_detail["debug"] = str(exc)
    error_response = {
        "error": error_detail,
        "timestamp": datetime.now().isoformat(),
        "path": str(request.url),
    }
    return JSONResponse(status_code=500, content=error_response)


# ==================== MAIN ENTRY POINT ====================

if __name__ == "__main__":
    if settings.environment == "development":
        uvicorn_config = settings.config_manager.get_uvicorn_config() if hasattr(settings, 'config_manager') else {
            "app": "main:app"}
        uvicorn.run(**uvicorn_config)
    else:
        logger.error("Direct execution only supported in development mode. Use the service wrapper in production.")
        sys.exit(1)
