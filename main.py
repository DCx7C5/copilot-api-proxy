#!/usr/bin/env python3
"""
GitHub Copilot API Proxy v2.1 + xAI Grok
Production-ready OpenAI-compatible proxy (Copilot + Grok + Claude)
"""

import asyncio
import json
import logging
import os
import time
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
import sys

import httpx
from fastapi import FastAPI, HTTPException, Request, Depends, BackgroundTasks
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field
import uvicorn
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from config import get_settings, Settings

# ==================== LOGGING SETUP ====================

def setup_logging(settings: Settings):
    """Configure logging based on settings"""
    log_config = settings.logging_config

    logging.basicConfig(
        level=getattr(logging, log_config.level),
        format=log_config.format,
        handlers=[]
    )

    console_handler = logging.StreamHandler()
    console_handler.setLevel(getattr(logging, log_config.level))

    if log_config.file_path:
        try:
            Path(log_config.file_path).parent.mkdir(parents=True, exist_ok=True)

            from logging.handlers import RotatingFileHandler
            file_handler = RotatingFileHandler(
                log_config.file_path,
                maxBytes=log_config.max_file_size,
                backupCount=log_config.backup_count
            )
            file_handler.setLevel(getattr(logging, log_config.level))

            if log_config.enable_json_logging:
                import json_log_formatter
                json_formatter = json_log_formatter.JSONFormatter()
                file_handler.setFormatter(json_formatter)
            else:
                formatter = logging.Formatter(log_config.format)
                file_handler.setFormatter(formatter)

            logging.getLogger().addHandler(file_handler)
        except Exception as e:
            logging.warning(f"Could not set up file logging: {e}")

    console_formatter = logging.Formatter(log_config.format)
    console_handler.setFormatter(console_formatter)
    logging.getLogger().addHandler(console_handler)

# ==================== GLOBAL SETTINGS ====================

settings = get_settings()
setup_logging(settings)
logger = logging.getLogger(__name__)

# ==================== RATE LIMITING ====================

limiter = Limiter(key_func=get_remote_address)

# ==================== FASTAPI APP SETUP ====================

app = FastAPI(
    title=settings.app_name,
    description="Production-ready OpenAI-compatible API proxy for GitHub Copilot + xAI Grok",
    version=settings.version,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json" if settings.debug else None
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

if settings.security.enable_cors:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.security.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

if settings.environment == "production":
    allowed_hosts = ["localhost", "127.0.0.1", "::1"]
    import urllib.parse
    parsed_url = urllib.parse.urlparse(settings.base_url)
    if parsed_url.hostname:
        allowed_hosts.append(parsed_url.hostname)

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

templates_path = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_path))

security = HTTPBearer(auto_error=False)

# ==================== DATA MODELS ====================

class ChatMessage(BaseModel):
    role: str = Field(..., description="Role of the message sender")
    content: str = Field(..., description="Content of the message")

class ChatRequest(BaseModel):
    model: str = Field(default="gpt-4", description="Model to use")
    messages: List[ChatMessage] = Field(..., description="List of messages")
    stream: bool = Field(default=False, description="Whether to stream the response")
    max_tokens: Optional[int] = Field(None, description="Maximum tokens to generate")
    temperature: Optional[float] = Field(None, description="Temperature for sampling")

    class Config:
        schema_extra = {
            "example": {
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "Write a Python function to calculate fibonacci numbers"}],
                "stream": False,
                "max_tokens": 1000,
                "temperature": 0.7
            }
        }

class ClaudeMessage(BaseModel):
    role: str = Field(..., description="user | assistant")
    content: str = Field(..., description="Message content")

class ClaudeRequest(BaseModel):
    model: str = Field(default="gpt-4", description="Model to use (mapped internally)")
    messages: List[ClaudeMessage] = Field(...)
    system: Optional[str] = None
    max_tokens: Optional[int] = Field(None, ge=1, le=4096)
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    stream: bool = False

    class Config:
        schema_extra = {
            "example": {
                "model": "claude-3-opus-20240229",
                "messages": [{"role": "user", "content": "Write a fast Fibonacci function"}],
                "system": "You are a world-class Python engineer.",
                "stream": True
            }
        }

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

# ==================== TOKEN MANAGEMENT ====================

TOKENS: Dict[str, TokenData] = {}
SERVICE_START_TIME = time.time()

class TokenManager:
    def __init__(self):
        self.encryption_key = self._get_or_create_encryption_key()

    def _get_or_create_encryption_key(self) -> Optional[str]:
        if not settings.storage.encrypt_tokens:
            return None
        key = settings.storage.token_encryption_key
        if not key:
            key = secrets.token_urlsafe(32)
            logger.warning("Generated new token encryption key. Set STORAGE__TOKEN_ENCRYPTION_KEY in config to persist across restarts.")
        return key

    async def save_tokens(self) -> None:
        try:
            token_file = settings.storage.get_token_file_path()
            token_file.parent.mkdir(parents=True, exist_ok=True)

            data = {}
            for token_id, token_data in TOKENS.items():
                serialized = token_data.dict()
                if self.encryption_key:
                    serialized['github_token'] = self._encrypt(serialized['github_token'])
                data[token_id] = serialized

            temp_file = token_file.with_suffix('.tmp')
            with open(temp_file, 'w') as f:
                json.dump(data, f, indent=2)
            temp_file.replace(token_file)

            logger.debug(f"Saved {len(TOKENS)} tokens to {token_file}")
        except Exception as e:
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
                except Exception as e:
                    logger.warning(f"Failed to load token {token_id[:10]}...: {e}")

            TOKENS.clear()
            TOKENS.update(loaded_tokens)
            logger.info(f"Loaded {len(TOKENS)} tokens from {token_file}")
        except Exception as e:
            logger.error(f"Error loading tokens: {e}")

    def _encrypt(self, data: str) -> str:
        import base64
        return base64.b64encode(data.encode()).decode()

    def _decrypt(self, data: str) -> str:
        import base64
        return base64.b64decode(data.encode()).decode()

    async def cleanup_expired_tokens(self) -> int:
        if not settings.storage.cleanup_expired_tokens:
            return 0
        current_time = time.time()
        expiry_threshold = current_time - (settings.security.token_expiry_hours * 3600)
        expired_tokens = [token_id for token_id, token_data in TOKENS.items() if token_data.expires_at and token_data.expires_at < current_time]
        for token_id in expired_tokens:
            del TOKENS[token_id]
        if expired_tokens:
            await self.save_tokens()
            logger.info(f"Cleaned up {len(expired_tokens)} expired tokens")
        return len(expired_tokens)

token_manager = TokenManager()

# ==================== BACKEND ROUTING HELPERS ====================

async def get_backend_headers(token: str, is_grok: bool) -> Dict[str, str]:
    """Return correct headers depending on backend (Copilot vs Grok)"""
    if is_grok:
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "OpenClaude-Grok-Proxy/2.1",
        }
    else:
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": settings.proxy.user_agent,
            "X-GitHub-Api-Version": "2022-11-28",
        }

def is_grok_model(model: str) -> bool:
    """Detect if the requested model is a Grok model"""
    return model.lower().startswith("grok-")

# ==================== AUTH DEPENDENCY (now provider-aware) ====================

@limiter.limit(f"{settings.security.rate_limit_requests}/{settings.security.rate_limit_period}s")
async def verify_token(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Optional[str]:   # returns raw token (GitHub or xAI key)
    """Return raw token. For Grok we bypass token store and use the provided key directly."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Authorization header required")

    token = credentials.credentials

    # Grok calls pass their own xAI key directly
    if request.state.is_grok:
        return token

    # Copilot / Claude path - use our stored token
    if token not in TOKENS:
        logger.warning(f"Invalid token attempt from {get_remote_address(request)}")
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    token_data = TOKENS[token]
    if token_data.expires_at and token_data.expires_at < time.time():
        del TOKENS[token]
        await token_manager.save_tokens()
        raise HTTPException(status_code=401, detail="Token has expired")

    token_data.last_used = time.time()
    if int(time.time()) % 300 == 0:
        await token_manager.save_tokens()

    return token_data.github_token

# ==================== WEB ROUTES (unchanged) ====================

@app.get("/", response_class=HTMLResponse)
@limiter.limit("30/minute")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "base_url": settings.base_url})

@app.get("/dashboard", response_class=HTMLResponse)
@limiter.limit("30/minute")
async def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request, "base_url": settings.base_url, "tokens": len(TOKENS)})

@app.get("/login")
@limiter.limit("10/minute")
async def login(request: Request):
    if not settings.github.client_id:
        raise HTTPException(status_code=503, detail="Authentication service not configured.")
    state = secrets.token_urlsafe(32)
    scopes = "+".join(settings.github.oauth_scopes)
    auth_url = f"https://github.com/login/oauth/authorize?client_id={settings.github.client_id}&redirect_uri={settings.github.redirect_uri}&scope={scopes}&state={state}"
    logger.info(f"OAuth login initiated from {get_remote_address(request)}")
    return {"login_url": auth_url, "state": state}

@app.get("/auth/callback")
@limiter.limit("10/minute")
async def auth_callback(request: Request, code: str, state: str):
    # (unchanged - GitHub OAuth only)
    if not settings.github.client_id or not settings.github.client_secret:
        raise HTTPException(status_code=503, detail="Authentication service not configured")
    token_data = {"client_id": settings.github.client_id, "client_secret": settings.github.client_secret, "code": code}
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post("https://github.com/login/oauth/access_token", data=token_data, headers={"Accept": "application/json"})
        if response.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to exchange code for token")
        result = response.json()
    if "access_token" not in result:
        raise HTTPException(status_code=400, detail="Authentication failed")
    api_token = f"cp-{int(time.time())}-{secrets.token_urlsafe(16)}"
    expires_in = result.get("expires_in") or (settings.security.token_expiry_hours * 3600)
    expires_at = time.time() + expires_in
    token_data_obj = TokenData(github_token=result["access_token"], created=time.time(), expires_at=expires_at)
    TOKENS[api_token] = token_data_obj
    await token_manager.save_tokens()
    return AuthResponse(message="Authentication successful", token=api_token, expires_in=expires_in, expires_at=datetime.fromtimestamp(expires_at).isoformat())

# ==================== API ROUTES WITH GROK SUPPORT ====================

@app.post("/v1/chat/completions")
@limiter.limit(f"{settings.security.rate_limit_requests}/{settings.security.rate_limit_period}s")
async def chat_completions(
    request: Request,
    chat_request: ChatRequest,
    raw_token: Optional[str] = Depends(verify_token)
):
    """OpenAI-compatible endpoint that routes to Copilot OR xAI Grok depending on model"""
    request.state.is_grok = is_grok_model(chat_request.model)   # flag for auth

    # Validate request size
    content_length = len(json.dumps(chat_request.dict()))
    if content_length > settings.security.max_request_size:
        raise HTTPException(status_code=413, detail=f"Request too large: {content_length} bytes (max: {settings.security.max_request_size})")

    if chat_request.max_tokens and chat_request.max_tokens > settings.security.max_tokens_per_request:
        raise HTTPException(status_code=400, detail=f"max_tokens too large: {chat_request.max_tokens} (max: {settings.security.max_tokens_per_request})")

    headers = await get_backend_headers(raw_token, request.state.is_grok)

    copilot_request = {
        "model": chat_request.model,
        "messages": [msg.dict() for msg in chat_request.messages],
        "stream": chat_request.stream,
    }
    if chat_request.max_tokens:
        copilot_request["max_tokens"] = chat_request.max_tokens
    if chat_request.temperature is not None:
        copilot_request["temperature"] = chat_request.temperature

    timeout = httpx.Timeout(settings.proxy.request_timeout, connect=10.0)

    base_url = settings.xai.api_base if request.state.is_grok else settings.proxy.copilot_api_base

    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            start_time = time.time()
            response = await client.post(
                f"{base_url}/chat/completions",
                json=copilot_request,
                headers=headers
            )
            request_duration = time.time() - start_time

            if settings.logging_config.log_requests:
                logger.info(f"Request completed: status={response.status_code}, duration={request_duration:.2f}s, model={chat_request.model}, backend={'xAI Grok' if request.state.is_grok else 'GitHub Copilot'}")

            if response.status_code != 200:
                if response.status_code == 401:
                    raise HTTPException(status_code=401, detail="Invalid or expired token. Please re-authenticate.")
                elif response.status_code == 429:
                    raise HTTPException(status_code=429, detail="Rate limit exceeded.")
                else:
                    raise HTTPException(status_code=response.status_code, detail=f"Backend error: {response.text[:200]}")

            if chat_request.stream:
                return StreamingResponse(iter([response.content]), media_type="text/event-stream")
            else:
                return response.json()

        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="Request to backend timed out")
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail="Error communicating with backend")

@app.post("/v1/messages")
@limiter.limit(f"{settings.security.rate_limit_requests}/{settings.security.rate_limit_period}s")
async def claude_messages(
    request: Request,
    claude_req: ClaudeRequest,
    raw_token: Optional[str] = Depends(verify_token)
):
    """Anthropic /v1/messages → converted and routed through the same backend logic (supports Grok too)"""
    openai_messages = []
    if claude_req.system:
        openai_messages.append({"role": "system", "content": claude_req.system})
    openai_messages.extend([{"role": msg.role, "content": msg.content} for msg in claude_req.messages])

    openai_req = ChatRequest(
        model=claude_req.model,
        messages=openai_messages,
        stream=claude_req.stream,
        max_tokens=claude_req.max_tokens,
        temperature=claude_req.temperature,
    )
    return await chat_completions(request, openai_req, raw_token)

@app.get("/v1/models")
async def list_models(raw_token: Optional[str] = Depends(verify_token)):
    """List available models (Copilot + Grok)"""
    return {
        "object": "list",
        "data": [
            {"id": "gpt-4", "object": "model", "created": 1677610602, "owned_by": "openai"},
            {"id": "gpt-3.5-turbo", "object": "model", "created": 1677610602, "owned_by": "openai"},
            {"id": "grok-beta", "object": "model", "created": 1735689600, "owned_by": "xai"},
            {"id": "grok-2-1212", "object": "model", "created": 1735689600, "owned_by": "xai"},
        ]
    }

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
        except Exception as e:
            logger.error(f"Error in periodic cleanup: {e}")

@app.on_event("startup")
async def startup_event():
    logger.info(f"[+] Starting {settings.app_name} v{settings.version}")
    logger.info(f"[+] Environment: {settings.environment} | Server mode: {settings.server.mode}")
    await token_manager.load_tokens()
    if settings.storage.cleanup_expired_tokens:
        asyncio.create_task(periodic_cleanup())
    logger.info(f"[+] Service ready - {len(TOKENS)} tokens loaded | Grok backend enabled")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("[-] Shutting down...")
    await token_manager.save_tokens()

# ==================== ERROR HANDLERS (unchanged) ====================

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
    error_response = {
        "error": {"message": "An unexpected error occurred", "type": "internal_error", "code": 500},
        "timestamp": datetime.now().isoformat(),
        "path": str(request.url)
    }
    if settings.debug:
        error_response["error"]["debug"] = str(exc)
    return JSONResponse(status_code=500, content=error_response)

# ==================== MAIN ENTRY POINT ====================

if __name__ == "__main__":
    if settings.environment == "development":
        uvicorn_config = settings.config_manager.get_uvicorn_config() if hasattr(settings, 'config_manager') else {"app": "main:app"}
        uvicorn.run(**uvicorn_config)
    else:
        logger.error("Direct execution only supported in development mode. Use the service wrapper in production.")
        sys.exit(1)