"""
Tests for Copilot token exchange (_get_copilot_token) — all branches.
"""
import time
from unittest.mock import patch

import httpx
import pytest
import respx

from main import _get_copilot_token, _copilot_token_cache


# ═══════════════════════════════════════════════════════════════════════════════
#  Cached token — returns immediately
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_copilot_token_cache_hit():
    # GIVEN a cached token that is still valid (>60 s remaining)
    _copilot_token_cache["ghp_cached"] = ("capi_cached", time.time() + 600)
    # WHEN we request a copilot token
    result = await _get_copilot_token("ghp_cached")
    # THEN we get the cached value without any HTTP call
    assert result == "capi_cached"


@pytest.mark.asyncio
async def test_copilot_token_cache_expired_triggers_refresh():
    # GIVEN a cached token that expires within 60 s (stale)
    _copilot_token_cache["ghp_stale"] = ("capi_old", time.time() + 30)
    # WHEN all endpoints fail → fallback to raw token
    with respx.mock:
        respx.get("https://api.github.com/copilot_internal/v2/token").mock(
            return_value=httpx.Response(403, text="Forbidden"))
        respx.get("https://api.github.com/copilot_internal/v1/token").mock(
            return_value=httpx.Response(403, text="Forbidden"))
        result = await _get_copilot_token("ghp_stale")
    # THEN falls back to raw token (all endpoints failed, not 401)
    assert result == "ghp_stale"


# ═══════════════════════════════════════════════════════════════════════════════
#  v2 token endpoint — success
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_copilot_token_v2_success_with_iso_expiry():
    # GIVEN v2 returns a valid token with ISO timestamp
    with respx.mock:
        respx.get("https://api.github.com/copilot_internal/v2/token").mock(
            return_value=httpx.Response(200, json={
                "token": "capi_v2_ok",
                "expires_at": "2027-06-01T00:00:00Z",
            }))
        result = await _get_copilot_token("ghp_v2test")
    assert result == "capi_v2_ok"
    # AND token is cached
    assert "ghp_v2test" in _copilot_token_cache
    assert _copilot_token_cache["ghp_v2test"][0] == "capi_v2_ok"


@pytest.mark.asyncio
async def test_copilot_token_v2_success_with_numeric_expiry():
    # GIVEN v2 returns a valid token with numeric expires_at
    future_ts = time.time() + 1800
    with respx.mock:
        respx.get("https://api.github.com/copilot_internal/v2/token").mock(
            return_value=httpx.Response(200, json={
                "token": "capi_num_exp",
                "expires_at": future_ts,
            }))
        result = await _get_copilot_token("ghp_numexp")
    assert result == "capi_num_exp"


@pytest.mark.asyncio
async def test_copilot_token_v2_success_with_empty_expiry():
    # GIVEN v2 returns a valid token with empty expires_at (default 25min)
    with respx.mock:
        respx.get("https://api.github.com/copilot_internal/v2/token").mock(
            return_value=httpx.Response(200, json={
                "token": "capi_no_exp",
                "expires_at": "",
            }))
        result = await _get_copilot_token("ghp_noexp")
    assert result == "capi_no_exp"


@pytest.mark.asyncio
async def test_copilot_token_v2_success_with_invalid_expiry():
    # GIVEN v2 returns a token with non-parseable expires_at
    with respx.mock:
        respx.get("https://api.github.com/copilot_internal/v2/token").mock(
            return_value=httpx.Response(200, json={
                "token": "capi_bad_exp",
                "expires_at": "not-a-date",
            }))
        result = await _get_copilot_token("ghp_badexp")
    assert result == "capi_bad_exp"


# ═══════════════════════════════════════════════════════════════════════════════
#  v2 → 401 → raises HTTPException immediately
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_copilot_token_401_raises():
    # GIVEN v2 returns 401
    from fastapi import HTTPException
    with respx.mock:
        respx.get("https://api.github.com/copilot_internal/v2/token").mock(
            return_value=httpx.Response(401, json={"message": "Bad credentials"}))
        with pytest.raises(HTTPException) as exc_info:
            await _get_copilot_token("ghp_bad401")
    assert exc_info.value.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════════
#  v2 fails → v1 fallback succeeds
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_copilot_token_v2_fails_v1_succeeds():
    # GIVEN v2 returns 403, but v1 returns token
    with respx.mock:
        respx.get("https://api.github.com/copilot_internal/v2/token").mock(
            return_value=httpx.Response(403, text="Forbidden"))
        respx.get("https://api.github.com/copilot_internal/v1/token").mock(
            return_value=httpx.Response(200, json={
                "token": "capi_v1_ok",
                "expires_at": "2027-01-01T00:00:00Z",
            }))
        result = await _get_copilot_token("ghp_v1fallback")
    assert result == "capi_v1_ok"


# ═══════════════════════════════════════════════════════════════════════════════
#  All endpoints fail → falls back to raw token
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_copilot_token_all_fail_returns_raw():
    # GIVEN all copilot endpoints return non-200, non-401
    with respx.mock:
        respx.get("https://api.github.com/copilot_internal/v2/token").mock(
            return_value=httpx.Response(500, text="ISE"))
        respx.get("https://api.github.com/copilot_internal/v1/token").mock(
            return_value=httpx.Response(500, text="ISE"))
        result = await _get_copilot_token("ghp_raw_fallback")
    # THEN raw token is returned
    assert result == "ghp_raw_fallback"


@pytest.mark.asyncio
async def test_copilot_token_network_error_falls_back():
    # GIVEN network errors on all endpoints
    with respx.mock:
        respx.get("https://api.github.com/copilot_internal/v2/token").mock(
            side_effect=httpx.ConnectError("refused"))
        respx.get("https://api.github.com/copilot_internal/v1/token").mock(
            side_effect=httpx.ConnectError("refused"))
        result = await _get_copilot_token("ghp_net_err")
    assert result == "ghp_net_err"


@pytest.mark.asyncio
async def test_copilot_token_200_but_empty_token_field():
    # GIVEN v2 returns 200 but with empty token field → tries next
    with respx.mock:
        respx.get("https://api.github.com/copilot_internal/v2/token").mock(
            return_value=httpx.Response(200, json={"token": "", "expires_at": ""}))
        respx.get("https://api.github.com/copilot_internal/v1/token").mock(
            return_value=httpx.Response(200, json={"token": "capi_v1_nonempty", "expires_at": "2027-01-01T00:00:00Z"}))
        result = await _get_copilot_token("ghp_empty_token")
    assert result == "capi_v1_nonempty"

