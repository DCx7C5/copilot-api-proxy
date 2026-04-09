"""
Shared pytest fixtures and test-environment bootstrap.

IMPORTANT: The os.environ assignments at the top of this file must run
BEFORE main.py is imported so that ConfigManager picks up the test values
(avoids PermissionError trying to mkdir /run/... in unix_socket mode).
"""

import json
import os
import time

# ── Override config BEFORE any application import ────────────────────────────
os.environ.setdefault("SERVER__MODE", "development")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("STORAGE__DATA_DIR", "/tmp/copilot-test-data")
os.environ.setdefault("STORAGE__CACHE_DIR", "/tmp/copilot-test-cache")
os.environ.setdefault("LOGGING_CONFIG__FILE_PATH", "/tmp/copilot-test-logs/app.log")
os.environ.setdefault("STORAGE__ENCRYPT_TOKENS", "false")
os.environ.setdefault("STORAGE__CLEANUP_EXPIRED_TOKENS", "false")
os.environ.setdefault("SERVER__DEV_HOST", "127.0.0.1")
os.environ.setdefault("SERVER__DEV_PORT", "18765")

# ── Application imports (settings now use the overrides above) ───────────────
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from unittest.mock import MagicMock

from main import app, TOKENS, _copilot_token_cache, TokenData


# ── Async HTTP client fixture ─────────────────────────────────────────────────

@pytest_asyncio.fixture
async def client():
    """Async test client that speaks directly to the FastAPI app via ASGI."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


# ── State-reset fixture (autouse) ─────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_state():
    """Clear all shared in-memory state before and after every test."""
    TOKENS.clear()
    _copilot_token_cache.clear()
    yield
    TOKENS.clear()
    _copilot_token_cache.clear()


# ── Token fixture ─────────────────────────────────────────────────────────────

@pytest.fixture
def valid_cp_token() -> str:
    """Inject one valid ``cp-*`` token and return its string value."""
    token = "cp-1234567890-testtoken-abc"
    TOKENS[token] = TokenData(
        github_token="ghp_test_github_token_xyz",
        created=time.time(),
        expires_at=time.time() + 3600,
        user_info={"login": "testuser"},
    )
    return token


# ── Mock-response helper ──────────────────────────────────────────────────────

def mock_http_response(status_code: int, json_data=None, text: str = "") -> MagicMock:
    """Build a minimal MagicMock that quacks like an ``httpx.Response``."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text or (json.dumps(json_data) if json_data else "")
    resp.content = resp.text.encode()
    resp.headers = {}
    return resp

