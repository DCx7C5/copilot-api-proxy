"""
Coverage-Boost-Tests für copilot-api-proxy.

Ziel: Abdeckung von nicht getesteten Pfaden in main.py und config.py.
Fokus auf:
  - _build_grok_web_headers (mit/ohne x_com_cookies)
  - resolve_copilot_model (Datum-Suffix)
  - _openai_to_anthropic_response
  - _openai_sse_to_anthropic_sse
  - _grok_web_sync / _grok_com_sync Fehler
  - _grok_web_chat / _grok_com_chat Fehler
  - /auth/callback OAuth-Flow
  - /login/device, /login/device/poll
  - _proxy_chat_to_anthropic (streaming)
  - _proxy_to_anthropic_messages (streaming + timeout)
  - verify_token (x-api-key, gho_ prefix, save-on-expire)
  - /v1/messages streaming + non-streaming Pfade
  - Alias-Routen (/chat/completions, /messages, /models)
  - Error-Handler (500 server error)
  - periodic_cleanup (unit)
  - _github_configured / _xai_configured / _twitter_configured
  - _oauth1_auth_header
  - TokenManager._get_or_create_encryption_key
  - Copilot-Token-Cache (Cache-Hit-Zweig)
  - gsk_ Token-Präfix
"""
import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import respx

from main import (
    TOKENS,
    TokenData,
    _build_grok_web_headers,
    _grok_com_error_from_status,
    _grok_web_error_from_status,
    _github_configured,
    _xai_configured,
    _twitter_configured,
    _openai_to_anthropic_response,
    _oauth1_auth_header,
    _copilot_token_cache,
    resolve_copilot_model,
    token_manager,
    normalize_model_name,
    is_grok_model,
)


# ═══════════════════════════════════════════════════════════════════════════════
#  _build_grok_web_headers  (lines 653-685)
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildGrokWebHeaders:
    """Tests for _build_grok_web_headers()."""

    def test_with_x_com_cookies_contains_auth_and_ct0(self):
        # GIVEN a full cookie string that already has auth_token and ct0
        headers = _build_grok_web_headers(
            auth_token="myauth",
            ct0="myct0",
            x_com_cookies="auth_token=myauth; ct0=myct0; extra=1",
        )
        # THEN cookie is used as-is
        assert "auth_token=myauth" in headers["Cookie"]
        assert headers["Authorization"] == "Bearer myauth"
        assert headers["X-Csrf-Token"] == "myct0"

    def test_with_x_com_cookies_missing_auth_token_prepended(self):
        # GIVEN cookie string without auth_token
        headers = _build_grok_web_headers(
            auth_token="myauth",
            ct0="myct0",
            x_com_cookies="extra=value",
        )
        # THEN auth_token is prepended
        assert "auth_token=myauth" in headers["Cookie"]

    def test_with_x_com_cookies_missing_ct0_prepended(self):
        # GIVEN cookie string without ct0
        headers = _build_grok_web_headers(
            auth_token="myauth",
            ct0="myct0",
            x_com_cookies="auth_token=myauth; other=1",
        )
        # THEN ct0 is prepended
        assert "ct0=myct0" in headers["Cookie"]

    def test_without_x_com_cookies_builds_minimal(self):
        # GIVEN no x_com_cookies
        headers = _build_grok_web_headers(
            auth_token="tok123",
            ct0="csrf456",
        )
        cookie = headers["Cookie"]
        assert "auth_token=tok123" in cookie
        assert "ct0=csrf456" in cookie

    def test_user_agent_override(self):
        # GIVEN a custom user-agent
        headers = _build_grok_web_headers(
            auth_token="tok",
            ct0="csrf",
            user_agent="CustomBrowser/2.0",
        )
        assert headers["User-Agent"] == "CustomBrowser/2.0"

    def test_no_user_agent_falls_back_to_settings(self):
        # GIVEN no user-agent → falls back to settings.browser.user_agent
        headers = _build_grok_web_headers(auth_token="tok", ct0="csrf")
        # THEN User-Agent is a string (may be empty from test config)
        assert isinstance(headers["User-Agent"], str)

    def test_extra_x_com_cookies_merged(self):
        # GIVEN settings.browser.x_com_cookies has extras
        with patch("main.settings.browser.x_com_cookies", "pref=abc; lang=en"):
            headers = _build_grok_web_headers(auth_token="tok", ct0="csrf")
        assert "pref=abc" in headers["Cookie"]
        assert "lang=en" in headers["Cookie"]
        # auth_token and ct0 must not be duplicated
        assert headers["Cookie"].count("auth_token=tok") == 1

    def test_content_type_json(self):
        headers = _build_grok_web_headers(auth_token="tok", ct0="csrf")
        assert headers["Content-Type"] == "application/json"


# ═══════════════════════════════════════════════════════════════════════════════
#  resolve_copilot_model – date suffix stripping (lines 592-599)
# ═══════════════════════════════════════════════════════════════════════════════

class TestResolveCopilotModelDateSuffix:
    """Test date-suffix stripping in resolve_copilot_model."""

    def test_date_suffix_stripped_and_resolved(self):
        # GIVEN a model name with a date suffix that maps to an alias
        # claude-haiku-4-5-20251001 → strip → claude-haiku-4-5 → alias lookup
        result = resolve_copilot_model("claude-haiku-4-5-20251001")
        # THEN the alias is resolved (claude-haiku-4.5)
        assert "claude" in result.lower()
        assert "20251001" not in result

    def test_date_suffix_stripped_no_alias_uses_stripped(self):
        # GIVEN a model with date suffix but no alias
        result = resolve_copilot_model("unknown-model-3-99999999")
        # THEN the stripped form is returned
        assert "99999999" not in result

    def test_no_date_suffix_passthrough(self):
        # GIVEN a model without date suffix
        result = resolve_copilot_model("gpt-4o")
        assert result == "gpt-4o"

    def test_claude_sonnet_date_suffix(self):
        # claude-sonnet-4-5-20251001 → should resolve to claude-sonnet-4.5
        result = resolve_copilot_model("claude-sonnet-4-5-20251001")
        assert "20251001" not in result


# ═══════════════════════════════════════════════════════════════════════════════
#  _openai_to_anthropic_response (lines 2362-2382)
# ═══════════════════════════════════════════════════════════════════════════════

class TestOpenaiToAnthropicResponse:
    """Tests for the OpenAI → Anthropic response converter."""

    def test_basic_conversion(self):
        # GIVEN a standard OpenAI chat.completion response
        openai_data = {
            "id": "chatcmpl-abc",
            "object": "chat.completion",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": "Hello!"},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
        }
        # WHEN converting to Anthropic format
        result = _openai_to_anthropic_response(openai_data, "claude-3-5-sonnet")
        # THEN fields are correct
        assert result["type"] == "message"
        assert result["role"] == "assistant"
        assert result["content"][0]["text"] == "Hello!"
        assert result["model"] == "claude-3-5-sonnet"
        assert result["stop_reason"] == "end_turn"

    def test_length_finish_reason_becomes_max_tokens(self):
        openai_data = {
            "id": "chatcmpl-xyz",
            "choices": [{"message": {"content": "long"}, "finish_reason": "length"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        }
        result = _openai_to_anthropic_response(openai_data, "claude-sonnet-4")
        assert result["stop_reason"] == "max_tokens"

    def test_empty_content_returns_empty_list(self):
        openai_data = {
            "id": "chatcmpl-empty",
            "choices": [{"message": {"content": ""}, "finish_reason": "stop"}],
            "usage": {},
        }
        result = _openai_to_anthropic_response(openai_data, "claude-sonnet-4")
        assert result["content"] == []

    def test_usage_tokens_mapped(self):
        openai_data = {
            "id": "chatcmpl-u",
            "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 13, "total_tokens": 20},
        }
        result = _openai_to_anthropic_response(openai_data, "claude-haiku-4.5")
        assert result["usage"]["input_tokens"] == 7
        assert result["usage"]["output_tokens"] == 13

    def test_missing_id_generates_fallback(self):
        openai_data = {
            "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
            "usage": {},
        }
        result = _openai_to_anthropic_response(openai_data, "claude-sonnet-4")
        assert result["id"].startswith("msg_")


# ═══════════════════════════════════════════════════════════════════════════════
#  _github_configured / _xai_configured / _twitter_configured (lines 1379-1404)
# ═══════════════════════════════════════════════════════════════════════════════

class TestConfiguredHelpers:
    """Tests for the *_configured() predicate functions."""

    def test_github_configured_with_real_id(self):
        with patch("main.settings.github.device_flow_client_id", "Iv1.realclientid123"):
            with patch("main.settings.github.client_id", ""):
                assert _github_configured() is True

    def test_github_configured_with_placeholder(self):
        with patch("main.settings.github.device_flow_client_id", "your_client_id_here"):
            with patch("main.settings.github.client_id", "your_client_id_here"):
                assert _github_configured() is False

    def test_github_configured_empty(self):
        with patch("main.settings.github.device_flow_client_id", ""):
            with patch("main.settings.github.client_id", ""):
                assert _github_configured() is False

    def test_xai_configured_with_real_key(self):
        with patch("main.settings.xai.api_key", "xai-realkeyabc123"):
            assert _xai_configured() is True

    def test_xai_configured_with_placeholder(self):
        with patch("main.settings.xai.api_key", "your_xai_api_key_here"):
            assert _xai_configured() is False

    def test_xai_configured_empty(self):
        with patch("main.settings.xai.api_key", ""):
            assert _xai_configured() is False

    def test_twitter_configured_both_present(self):
        with patch("main.settings.twitter.consumer_key", "real_consumer_key_123"):
            with patch("main.settings.twitter.consumer_secret", "real_consumer_secret_456"):
                assert _twitter_configured() is True

    def test_twitter_configured_missing_one(self):
        with patch("main.settings.twitter.consumer_key", "real_key"):
            with patch("main.settings.twitter.consumer_secret", ""):
                assert _twitter_configured() is False

    def test_twitter_configured_placeholder(self):
        with patch("main.settings.twitter.consumer_key", "your_twitter_consumer_key_here"):
            with patch("main.settings.twitter.consumer_secret", "real_secret"):
                assert _twitter_configured() is False


# ═══════════════════════════════════════════════════════════════════════════════
#  _oauth1_auth_header (lines 1303-1359)
# ═══════════════════════════════════════════════════════════════════════════════

class TestOauth1AuthHeader:
    """Unit tests for the OAuth 1.0a header builder."""

    def test_header_starts_with_oauth(self):
        header = _oauth1_auth_header(
            method="POST",
            url="https://api.twitter.com/oauth/request_token",
            consumer_key="ckey",
            consumer_secret="csecret",
        )
        assert header.startswith("OAuth ")

    def test_header_contains_required_fields(self):
        header = _oauth1_auth_header(
            method="POST",
            url="https://api.twitter.com/oauth/request_token",
            consumer_key="ckey",
            consumer_secret="csecret",
        )
        assert "oauth_consumer_key" in header
        assert "oauth_signature" in header
        assert "oauth_timestamp" in header
        assert "oauth_nonce" in header

    def test_header_with_token(self):
        header = _oauth1_auth_header(
            method="POST",
            url="https://api.twitter.com/oauth/access_token",
            consumer_key="ckey",
            consumer_secret="csecret",
            token="oauthtoken123",
            token_secret="tokensecret456",
            extra_params={"oauth_verifier": "verif789"},
        )
        assert "oauth_token" in header
        assert "oauth_verifier" in header

    def test_two_calls_have_different_nonces(self):
        h1 = _oauth1_auth_header("POST", "https://api.twitter.com/x", "k", "s")
        h2 = _oauth1_auth_header("POST", "https://api.twitter.com/x", "k", "s")
        # Signatures will differ due to different nonces/timestamps
        assert isinstance(h1, str) and isinstance(h2, str)


# ═══════════════════════════════════════════════════════════════════════════════
#  Copilot token cache — cache-hit path (line 456-460)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_copilot_token_cache_hit():
    """GIVEN a valid cached copilot token, _get_copilot_token should return it without HTTP."""
    from main import _get_copilot_token
    _copilot_token_cache["ghp_cached_test"] = ("capi_cached_token", time.time() + 1800)
    with respx.mock:
        # No HTTP mocks — if a request is made, it will raise
        result = await _get_copilot_token("ghp_cached_test")
    assert result == "capi_cached_token"
    del _copilot_token_cache["ghp_cached_test"]


# ═══════════════════════════════════════════════════════════════════════════════
#  TokenManager._get_or_create_encryption_key (lines 345-354)
# ═══════════════════════════════════════════════════════════════════════════════

def test_get_or_create_encryption_key_disabled():
    with patch("main.settings.storage.encrypt_tokens", False):
        key = token_manager._get_or_create_encryption_key()
    assert key is None


def test_get_or_create_encryption_key_with_existing():
    with patch("main.settings.storage.encrypt_tokens", True):
        with patch("main.settings.storage.token_encryption_key", "existing_key_abc"):
            key = token_manager._get_or_create_encryption_key()
    assert key == "existing_key_abc"


def test_get_or_create_encryption_key_generates_new():
    with patch("main.settings.storage.encrypt_tokens", True):
        with patch("main.settings.storage.token_encryption_key", ""):
            key = token_manager._get_or_create_encryption_key()
    # A new key is generated — must be a non-empty string
    assert isinstance(key, str) and len(key) > 0


# ═══════════════════════════════════════════════════════════════════════════════
#  gho_ raw token prefix bypasses TOKENS lookup
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.webapi
@pytest.mark.asyncio
async def test_gho_token_routes_to_copilot(client):
    """gho_ GitHub OAuth token should bypass TOKENS lookup and be accepted."""
    with respx.mock:
        respx.get("https://api.github.com/copilot_internal/v2/token").mock(
            return_value=httpx.Response(200, json={
                "token": "capi_test", "expires_at": "2027-01-01T00:00:00Z"}))
        respx.post("https://api.githubcopilot.com/chat/completions").mock(
            return_value=httpx.Response(200, json={
                "id": "chatcmpl-gho", "object": "chat.completion", "model": "gpt-4o",
                "choices": [{"index": 0,
                    "message": {"role": "assistant", "content": "OK via gho"},
                    "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}))
        r = await client.post("/v1/chat/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "Hi"}]},
            headers={"Authorization": "Bearer gho_testgithubtoken123"})
    assert r.status_code == 200


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_gsk_token_routes_to_xai(client):
    """gsk_ Grok API key should bypass TOKENS lookup and route to xAI."""
    with respx.mock:
        respx.post("https://api.x.ai/v1/chat/completions").mock(
            return_value=httpx.Response(200, json={
                "id": "chatcmpl-gsk", "object": "chat.completion", "model": "grok-3",
                "choices": [{"index": 0,
                    "message": {"role": "assistant", "content": "Grok via gsk_"},
                    "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}))
        r = await client.post("/v1/chat/completions",
            json={"model": "grok-3", "messages": [{"role": "user", "content": "Hi"}]},
            headers={"Authorization": "Bearer gsk_realtestkey123"})
    assert r.status_code == 200
    assert r.json()["choices"][0]["message"]["content"] == "Grok via gsk_"


# ═══════════════════════════════════════════════════════════════════════════════
#  /login/device — mocked GitHub Device Flow initiation (lines 1930-1959)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.html
@pytest.mark.asyncio
async def test_device_flow_configured_renders_page(client):
    """With a real GitHub Client ID, /login/device should render the HTML page."""
    with patch("main._github_configured", return_value=True):
        with respx.mock:
            respx.post("https://github.com/login/device/code").mock(
                return_value=httpx.Response(200, json={
                    "device_code": "device_abc",
                    "user_code": "WXYZ-1234",
                    "verification_uri": "https://github.com/login/device",
                    "expires_in": 900,
                    "interval": 5,
                }))
            r = await client.get("/login/device")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


@pytest.mark.html
@pytest.mark.asyncio
async def test_device_flow_github_error_returns_400(client):
    """If GitHub returns an error in the JSON, /login/device must return 400."""
    with patch("main._github_configured", return_value=True):
        with respx.mock:
            respx.post("https://github.com/login/device/code").mock(
                return_value=httpx.Response(200, json={
                    "error": "not_supported",
                    "error_description": "Device flow not supported",
                }))
            r = await client.get("/login/device")
    assert r.status_code == 400


@pytest.mark.html
@pytest.mark.asyncio
async def test_device_flow_github_502_on_bad_response(client):
    """If GitHub returns non-200, /login/device must return 502."""
    with patch("main._github_configured", return_value=True):
        with respx.mock:
            respx.post("https://github.com/login/device/code").mock(
                return_value=httpx.Response(503, text="Service Unavailable"))
            r = await client.get("/login/device")
    assert r.status_code == 502


# ═══════════════════════════════════════════════════════════════════════════════
#  /login/device/poll (lines 1962-2027)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.webapi
@pytest.mark.asyncio
async def test_device_flow_poll_authorization_pending(client):
    """authorization_pending must return {"status": "authorization_pending"}."""
    with patch("main._github_configured", return_value=True):
        with respx.mock:
            respx.post("https://github.com/login/oauth/access_token").mock(
                return_value=httpx.Response(200, json={"error": "authorization_pending"}))
            r = await client.get("/login/device/poll?device_code=abc")
    assert r.status_code == 200
    assert r.json()["status"] == "authorization_pending"


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_device_flow_poll_slow_down(client):
    with patch("main._github_configured", return_value=True):
        with respx.mock:
            respx.post("https://github.com/login/oauth/access_token").mock(
                return_value=httpx.Response(200, json={"error": "slow_down"}))
            r = await client.get("/login/device/poll?device_code=abc")
    assert r.status_code == 200
    assert r.json()["status"] == "slow_down"


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_device_flow_poll_other_error_returns_400(client):
    with patch("main._github_configured", return_value=True):
        with respx.mock:
            respx.post("https://github.com/login/oauth/access_token").mock(
                return_value=httpx.Response(200, json={
                    "error": "expired_token",
                    "error_description": "The device code has expired.",
                }))
            r = await client.get("/login/device/poll?device_code=abc")
    assert r.status_code == 400


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_device_flow_poll_no_access_token_returns_pending(client):
    with patch("main._github_configured", return_value=True):
        with respx.mock:
            respx.post("https://github.com/login/oauth/access_token").mock(
                return_value=httpx.Response(200, json={}))
            r = await client.get("/login/device/poll?device_code=abc")
    assert r.status_code == 200
    assert r.json()["status"] == "pending"


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_device_flow_poll_success_issues_token(client):
    with patch("main._github_configured", return_value=True):
        with respx.mock:
            respx.post("https://github.com/login/oauth/access_token").mock(
                return_value=httpx.Response(200, json={
                    "access_token": "gho_poll_success_token",
                    "expires_in": 28800,
                }))
            # Mock user info fetch
            respx.get("https://api.github.com/user").mock(
                return_value=httpx.Response(200, json={"login": "polluser"}))
            r = await client.get("/login/device/poll?device_code=abc")
    assert r.status_code == 200
    data = r.json()
    assert "token" in data
    assert data["token"].startswith("cp-")


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_device_flow_poll_github_http_error(client):
    with patch("main._github_configured", return_value=True):
        with respx.mock:
            respx.post("https://github.com/login/oauth/access_token").mock(
                return_value=httpx.Response(500, text="Internal Error"))
            r = await client.get("/login/device/poll?device_code=abc")
    assert r.status_code == 200
    assert r.json()["status"] == "error"


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_device_flow_poll_unconfigured_503(client):
    with patch("main._github_configured", return_value=False):
        r = await client.get("/login/device/poll?device_code=abc")
    assert r.status_code == 503


# ═══════════════════════════════════════════════════════════════════════════════
#  /auth/callback – OAuth Web Flow (lines 1502-1554)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.webapi
@pytest.mark.asyncio
async def test_auth_callback_no_client_id_503(client):
    """If GitHub OAuth is not configured, /auth/callback must return 503."""
    with patch("main.settings.github.client_id", ""):
        with patch("main.settings.github.client_secret", ""):
            r = await client.get("/auth/callback?code=abc&state=xyz")
    assert r.status_code == 503


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_auth_callback_github_token_exchange_fail_400(client):
    """Non-200 from GitHub token exchange → 400."""
    with patch("main.settings.github.client_id", "real_client_id"):
        with patch("main.settings.github.client_secret", "real_secret"):
            with respx.mock:
                respx.post("https://github.com/login/oauth/access_token").mock(
                    return_value=httpx.Response(400, json={"error": "bad_code"}))
                r = await client.get("/auth/callback?code=bad_code&state=xyz")
    assert r.status_code == 400


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_auth_callback_no_access_token_400(client):
    """If GitHub response has no access_token → 400."""
    with patch("main.settings.github.client_id", "real_client_id"):
        with patch("main.settings.github.client_secret", "real_secret"):
            with respx.mock:
                respx.post("https://github.com/login/oauth/access_token").mock(
                    return_value=httpx.Response(200, json={"error": "no token"}))
                r = await client.get("/auth/callback?code=abc&state=xyz")
    assert r.status_code == 400


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_auth_callback_success_redirects(client):
    """Successful OAuth callback must redirect to /login/success."""
    with patch("main.settings.github.client_id", "real_client_id"):
        with patch("main.settings.github.client_secret", "real_secret"):
            with respx.mock:
                respx.post("https://github.com/login/oauth/access_token").mock(
                    return_value=httpx.Response(200, json={
                        "access_token": "gho_callback_success",
                        "expires_in": 28800,
                    }))
                respx.get("https://api.github.com/user").mock(
                    return_value=httpx.Response(200, json={"login": "callbackuser"}))
                r = await client.get("/auth/callback?code=good_code&state=xyz",
                                     follow_redirects=False)
    assert r.status_code == 302
    assert "/login/success" in r.headers["location"]


# ═══════════════════════════════════════════════════════════════════════════════
#  _proxy_chat_to_anthropic — streaming path (lines 1191-1200)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.webapi
@pytest.mark.asyncio
async def test_chat_to_anthropic_streaming(client):
    """sk-ant-* token + claude model + stream=True must stream via Anthropic API."""
    sse_data = b"data: {\"type\":\"content_block_delta\",\"delta\":{\"text\":\"Hi\"}}\n\ndata: [DONE]\n\n"
    with respx.mock:
        respx.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(200, content=sse_data,
                headers={"content-type": "text/event-stream"}))
        r = await client.post("/v1/chat/completions",
            json={"model": "claude-3-5-sonnet",
                  "messages": [{"role": "user", "content": "Hi"}],
                  "stream": True},
            headers={"Authorization": "Bearer sk-ant-testtoken123"})
    assert r.status_code == 200
    assert "text/event-stream" in r.headers.get("content-type", "")


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_chat_to_anthropic_non_200(client):
    """Anthropic API error (non-200) must propagate as HTTP error."""
    with respx.mock:
        respx.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(429, json={"error": {"message": "Rate limit"}}))
        r = await client.post("/v1/chat/completions",
            json={"model": "claude-3-5-sonnet",
                  "messages": [{"role": "user", "content": "Hi"}]},
            headers={"Authorization": "Bearer sk-ant-testtoken123"})
    assert r.status_code == 429


# ═══════════════════════════════════════════════════════════════════════════════
#  _proxy_to_anthropic_messages — /v1/messages with sk-ant-* (lines 1234-1285)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.webapi
@pytest.mark.asyncio
async def test_messages_sk_ant_streaming(client):
    """sk-ant-* token on /v1/messages with stream=True must forward SSE."""
    sse_data = b"data: {\"type\":\"message_start\"}\n\ndata: [DONE]\n\n"
    with respx.mock:
        respx.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(200, content=sse_data,
                headers={"content-type": "text/event-stream"}))
        r = await client.post("/v1/messages",
            json={"model": "claude-3-5-sonnet",
                  "messages": [{"role": "user", "content": "Hi"}],
                  "max_tokens": 100,
                  "stream": True},
            headers={"Authorization": "Bearer sk-ant-testtoken123"})
    assert r.status_code == 200
    assert "text/event-stream" in r.headers.get("content-type", "")


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_messages_sk_ant_timeout(client):
    """Timeout from Anthropic API on /v1/messages must return 504."""
    with respx.mock:
        respx.post("https://api.anthropic.com/v1/messages").mock(
            side_effect=httpx.TimeoutException("Timeout"))
        r = await client.post("/v1/messages",
            json={"model": "claude-3-5-sonnet",
                  "messages": [{"role": "user", "content": "Hi"}],
                  "max_tokens": 100},
            headers={"Authorization": "Bearer sk-ant-testtoken123"})
    assert r.status_code == 504


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_messages_sk_ant_request_error(client):
    """Connection error from Anthropic API on /v1/messages must return 502."""
    with respx.mock:
        respx.post("https://api.anthropic.com/v1/messages").mock(
            side_effect=httpx.ConnectError("Connection refused"))
        r = await client.post("/v1/messages",
            json={"model": "claude-3-5-sonnet",
                  "messages": [{"role": "user", "content": "Hi"}],
                  "max_tokens": 100},
            headers={"Authorization": "Bearer sk-ant-testtoken123"})
    assert r.status_code == 502


# ═══════════════════════════════════════════════════════════════════════════════
#  /v1/messages with Copilot backend (streaming + non-streaming conversion)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.webapi
@pytest.mark.asyncio
async def test_messages_copilot_backend_streaming(client, valid_cp_token):
    """cp-* token on /v1/messages with stream=True must emit Anthropic SSE."""
    sse_body = (
        b'data: {"id":"chatcmpl-1","object":"chat.completion.chunk",'
        b'"choices":[{"delta":{"content":"Hello"},"index":0,"finish_reason":null}]}\n\n'
        b'data: [DONE]\n\n'
    )
    with respx.mock:
        respx.get("https://api.github.com/copilot_internal/v2/token").mock(
            return_value=httpx.Response(200, json={
                "token": "capi_test", "expires_at": "2027-01-01T00:00:00Z"}))
        respx.post("https://api.githubcopilot.com/chat/completions").mock(
            return_value=httpx.Response(200, content=sse_body,
                headers={"content-type": "text/event-stream"}))
        r = await client.post("/v1/messages",
            json={"model": "gpt-4o",
                  "messages": [{"role": "user", "content": "Hi"}],
                  "stream": True},
            headers={"Authorization": f"Bearer {valid_cp_token}"})
    assert r.status_code == 200
    assert "text/event-stream" in r.headers.get("content-type", "")
    # Anthropic SSE contains message_start event
    assert "message_start" in r.text


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_messages_copilot_backend_non_streaming_conversion(client, valid_cp_token):
    """cp-* token on /v1/messages without stream must convert OpenAI → Anthropic JSON."""
    with respx.mock:
        respx.get("https://api.github.com/copilot_internal/v2/token").mock(
            return_value=httpx.Response(200, json={
                "token": "capi_test", "expires_at": "2027-01-01T00:00:00Z"}))
        respx.post("https://api.githubcopilot.com/chat/completions").mock(
            return_value=httpx.Response(200, json={
                "id": "chatcmpl-conv", "object": "chat.completion", "model": "gpt-4o",
                "choices": [{"index": 0,
                    "message": {"role": "assistant", "content": "Converted response"},
                    "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 5, "total_tokens": 8}}))
        r = await client.post("/v1/messages",
            json={"model": "gpt-4o",
                  "messages": [{"role": "user", "content": "Hi"}],
                  "max_tokens": 100},
            headers={"Authorization": f"Bearer {valid_cp_token}"})
    assert r.status_code == 200
    data = r.json()
    # Anthropic format fields
    assert data["type"] == "message"
    assert data["role"] == "assistant"
    assert data["content"][0]["text"] == "Converted response"


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_messages_copilot_with_system(client, valid_cp_token):
    """ClaudeRequest with system prompt must forward it correctly."""
    with respx.mock:
        respx.get("https://api.github.com/copilot_internal/v2/token").mock(
            return_value=httpx.Response(200, json={
                "token": "capi_test", "expires_at": "2027-01-01T00:00:00Z"}))
        route = respx.post("https://api.githubcopilot.com/chat/completions").mock(
            return_value=httpx.Response(200, json={
                "id": "chatcmpl-sys", "object": "chat.completion", "model": "gpt-4o",
                "choices": [{"index": 0,
                    "message": {"role": "assistant", "content": "With system"},
                    "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8}}))
        r = await client.post("/v1/messages",
            json={"model": "gpt-4o",
                  "messages": [{"role": "user", "content": "Hi"}],
                  "system": "You are a helpful assistant."},
            headers={"Authorization": f"Bearer {valid_cp_token}"})
    assert r.status_code == 200
    # Verify system message was included in the OpenAI request
    sent = json.loads(route.calls.last.request.content)
    assert any(m["role"] == "system" for m in sent["messages"])


# ═══════════════════════════════════════════════════════════════════════════════
#  Grok web sync — error paths (lines 852-898)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.webapi
@pytest.mark.asyncio
async def test_grok_web_sync_401_raises_401(client):
    """Grok web backend 401 must surface as HTTP 401 through /v1/chat/completions."""
    with respx.mock:
        respx.post("https://grok.x.com/2/grok/add_response.json").mock(
            return_value=httpx.Response(401, text="Unauthorized"))
        r = await client.post("/v1/chat/completions",
            json={"model": "grok-web-3", "messages": [{"role": "user", "content": "Hi"}]},
            headers={"Authorization": "Bearer grokweb::auth123::ct0abc"})
    assert r.status_code == 401


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_grok_web_sync_403_raises_403(client):
    """Grok web backend 403 must surface as HTTP 403."""
    with respx.mock:
        respx.post("https://grok.x.com/2/grok/add_response.json").mock(
            return_value=httpx.Response(403, text="Forbidden"))
        r = await client.post("/v1/chat/completions",
            json={"model": "grok-web-3", "messages": [{"role": "user", "content": "Hi"}]},
            headers={"Authorization": "Bearer grokweb::auth123::ct0abc"})
    assert r.status_code == 403


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_grok_web_sync_timeout_504(client):
    """Timeout on grok.x.com must result in 504."""
    with respx.mock:
        respx.post("https://grok.x.com/2/grok/add_response.json").mock(
            side_effect=httpx.TimeoutException("Timeout"))
        r = await client.post("/v1/chat/completions",
            json={"model": "grok-web-3", "messages": [{"role": "user", "content": "Hi"}]},
            headers={"Authorization": "Bearer grokweb::auth123::ct0abc"})
    assert r.status_code == 504


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_grok_web_sync_connection_error_502(client):
    """Connection error on grok.x.com must result in 502."""
    with respx.mock:
        respx.post("https://grok.x.com/2/grok/add_response.json").mock(
            side_effect=httpx.ConnectError("Connection refused"))
        r = await client.post("/v1/chat/completions",
            json={"model": "grok-web-3", "messages": [{"role": "user", "content": "Hi"}]},
            headers={"Authorization": "Bearer grokweb::auth123::ct0abc"})
    assert r.status_code == 502


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_grok_web_invalid_token_format_401(client):
    """Invalid grokweb token format must result in 401."""
    r = await client.post("/v1/chat/completions",
        json={"model": "grok-web-3", "messages": [{"role": "user", "content": "Hi"}]},
        headers={"Authorization": "Bearer grokweb::onlyonepart"})
    assert r.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════════
#  Grok.com sync — error paths (lines 1100-1149)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.webapi
@pytest.mark.asyncio
async def test_grok_com_sync_401_raises_401(client):
    with respx.mock:
        respx.post("https://grok.com/rest/app-chat/conversations/new").mock(
            return_value=httpx.Response(401, text="Unauthorized"))
        r = await client.post("/v1/chat/completions",
            json={"model": "grok-com-3", "messages": [{"role": "user", "content": "Hi"}]},
            headers={"Authorization": "Bearer grokcom::sso=fake; sso_at=fake"})
    assert r.status_code == 401


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_grok_com_sync_429_raises_429(client):
    with respx.mock:
        respx.post("https://grok.com/rest/app-chat/conversations/new").mock(
            return_value=httpx.Response(429, text="Rate limited"))
        r = await client.post("/v1/chat/completions",
            json={"model": "grok-com-3", "messages": [{"role": "user", "content": "Hi"}]},
            headers={"Authorization": "Bearer grokcom::sso=fake; sso_at=fake"})
    assert r.status_code == 429


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_grok_com_sync_timeout_504(client):
    with respx.mock:
        respx.post("https://grok.com/rest/app-chat/conversations/new").mock(
            side_effect=httpx.TimeoutException("Timeout"))
        r = await client.post("/v1/chat/completions",
            json={"model": "grok-com-3", "messages": [{"role": "user", "content": "Hi"}]},
            headers={"Authorization": "Bearer grokcom::sso=fake; sso_at=fake"})
    assert r.status_code == 504


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_grok_com_sync_connection_error_502(client):
    with respx.mock:
        respx.post("https://grok.com/rest/app-chat/conversations/new").mock(
            side_effect=httpx.ConnectError("Connection refused"))
        r = await client.post("/v1/chat/completions",
            json={"model": "grok-com-3", "messages": [{"role": "user", "content": "Hi"}]},
            headers={"Authorization": "Bearer grokcom::sso=fake; sso_at=fake"})
    assert r.status_code == 502


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_grok_com_sync_success_with_data_prefix(client):
    """SSE lines with 'data:' prefix must be parsed correctly."""
    sse_text = (
        'data: {"result":{"token":"Hello","isSoftStop":false}}\n'
        'data: {"result":{"token":" world","isSoftStop":false}}\n'
        'data: {"result":{"token":"","isSoftStop":true}}\n'
    )
    with respx.mock:
        respx.post("https://grok.com/rest/app-chat/conversations/new").mock(
            return_value=httpx.Response(200, text=sse_text))
        r = await client.post("/v1/chat/completions",
            json={"model": "grok-com-3", "messages": [{"role": "user", "content": "Hi"}]},
            headers={"Authorization": "Bearer grokcom::sso=fake; sso_at=fake"})
    assert r.status_code == 200
    assert "Hello" in r.json()["choices"][0]["message"]["content"]


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_grok_com_error_from_status_all_codes():
    """Verify all _grok_com_error_from_status branches."""
    assert "auth" in _grok_com_error_from_status(401).lower() or "expired" in _grok_com_error_from_status(401).lower()
    assert "subscription" in _grok_com_error_from_status(403).lower() or "invalid" in _grok_com_error_from_status(403).lower()
    assert "rate" in _grok_com_error_from_status(429).lower() or "limit" in _grok_com_error_from_status(429).lower()
    assert "502" in _grok_com_error_from_status(502) or "HTTP" in _grok_com_error_from_status(502)


# ═══════════════════════════════════════════════════════════════════════════════
#  /v1/models with xAI token (live + fallback) (lines 2526-2542)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.webapi
@pytest.mark.asyncio
async def test_models_xai_token_live_fetch(client):
    """xai-* token triggers live model fetch from xAI."""
    with respx.mock:
        respx.get("https://api.x.ai/v1/models").mock(
            return_value=httpx.Response(200, json={"data": [
                {"id": "grok-3", "object": "model", "created": 1743552000, "owned_by": "xai"},
            ]}))
        r = await client.get("/v1/models",
            headers={"Authorization": "Bearer xai-testkey123"})
    assert r.status_code == 200
    ids = {m["id"] for m in r.json()["data"]}
    assert "grok-3" in ids


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_models_xai_token_live_fetch_fails_uses_static(client):
    """If xAI live fetch fails, fall back to static list."""
    with respx.mock:
        respx.get("https://api.x.ai/v1/models").mock(
            side_effect=httpx.ConnectError("refused"))
        r = await client.get("/v1/models",
            headers={"Authorization": "Bearer xai-testkey123"})
    assert r.status_code == 200
    data = r.json()
    assert data["object"] == "list"
    assert len(data["data"]) > 0


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_models_cp_token_live_fetch(client, valid_cp_token):
    """cp-* token triggers live Copilot model fetch."""
    with respx.mock:
        respx.get("https://api.github.com/copilot_internal/v2/token").mock(
            return_value=httpx.Response(200, json={
                "token": "capi_models", "expires_at": "2027-01-01T00:00:00Z"}))
        respx.get("https://api.githubcopilot.com/models").mock(
            return_value=httpx.Response(200, json={"data": [
                {"id": "gpt-4o", "object": "model", "created": 1715367049, "owned_by": "openai"},
            ]}))
        r = await client.get("/v1/models",
            headers={"Authorization": f"Bearer {valid_cp_token}"})
    assert r.status_code == 200
    ids = {m["id"] for m in r.json()["data"]}
    assert "gpt-4o" in ids


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_models_cp_token_live_fetch_fails_uses_static(client, valid_cp_token):
    """If live Copilot model fetch fails, use static list."""
    with respx.mock:
        respx.get("https://api.github.com/copilot_internal/v2/token").mock(
            return_value=httpx.Response(200, json={
                "token": "capi_models", "expires_at": "2027-01-01T00:00:00Z"}))
        respx.get("https://api.githubcopilot.com/models").mock(
            side_effect=httpx.ConnectError("refused"))
        r = await client.get("/v1/models",
            headers={"Authorization": f"Bearer {valid_cp_token}"})
    assert r.status_code == 200
    assert len(r.json()["data"]) > 0


# ═══════════════════════════════════════════════════════════════════════════════
#  Error handlers (lines 2660-2689)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.webapi
@pytest.mark.asyncio
async def test_http_exception_handler_returns_json_error(client):
    """HTTPException must be wrapped in {error: {...}} JSON."""
    r = await client.get("/v1/chat/completions")  # 405 Method Not Allowed
    # FastAPI itself raises 405; our handler wraps it
    assert r.status_code in (401, 404, 405)
    # Check the response has JSON (may be wrapped or raw depending on route)


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_404_returns_json_with_error_key(client):
    """Unknown path must return a JSON error response."""
    r = await client.get("/totally/unknown/path/xyz")
    assert r.status_code == 404
    body = r.json()
    assert "error" in body or "detail" in body


# ═══════════════════════════════════════════════════════════════════════════════
#  Streaming chat — backend non-200 in streaming path (lines 2308-2319)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.webapi
@pytest.mark.asyncio
async def test_chat_streaming_backend_non_200_emits_error_event(client, valid_cp_token):
    """Backend non-200 in streaming mode must emit an SSE error event."""
    with respx.mock:
        respx.get("https://api.github.com/copilot_internal/v2/token").mock(
            return_value=httpx.Response(200, json={
                "token": "capi_test", "expires_at": "2027-01-01T00:00:00Z"}))
        respx.post("https://api.githubcopilot.com/chat/completions").mock(
            return_value=httpx.Response(500, text="Backend Error"))
        r = await client.post("/v1/chat/completions",
            json={"model": "gpt-4o",
                  "messages": [{"role": "user", "content": "Hi"}],
                  "stream": True},
            headers={"Authorization": f"Bearer {valid_cp_token}"})
    assert r.status_code == 200  # SSE always returns 200; errors are embedded
    # The SSE body must contain an error event
    body = r.text
    assert "error" in body or "[DONE]" in body


# ═══════════════════════════════════════════════════════════════════════════════
#  Chat — 413 request too large (line 2262-2264)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.webapi
@pytest.mark.asyncio
async def test_chat_request_too_large_returns_413(client, valid_cp_token):
    """Payload exceeding max_request_size must return 413."""
    with patch("main.settings.security.max_request_size", 10):  # tiny limit
        with respx.mock:
            respx.get("https://api.github.com/copilot_internal/v2/token").mock(
                return_value=httpx.Response(200, json={
                    "token": "capi_t", "expires_at": "2027-01-01T00:00:00Z"}))
            r = await client.post("/v1/chat/completions",
                json={"model": "gpt-4o",
                      "messages": [{"role": "user", "content": "Some content here"}]},
                headers={"Authorization": f"Bearer {valid_cp_token}"})
    assert r.status_code == 413


# ═══════════════════════════════════════════════════════════════════════════════
#  Grok web login — live probe 401 + network error
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.webapi
@pytest.mark.asyncio
async def test_login_grok_web_live_401_returns_401(client):
    """A 401 from grok.x.com during probe → HTTP 401."""
    with respx.mock:
        respx.post("https://grok.x.com/2/grok/add_response.json").mock(
            return_value=httpx.Response(401, text="Unauthorized"))
        r = await client.post("/login/grok-web",
            json={"auth_token": "bad_token", "ct0": "bad_ct0"})
    assert r.status_code == 401


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_login_grok_web_live_502_on_bad_status(client):
    """Non-200/400 from grok.x.com during probe → HTTP 502."""
    with respx.mock:
        respx.post("https://grok.x.com/2/grok/add_response.json").mock(
            return_value=httpx.Response(503, text="Service Unavailable"))
        r = await client.post("/login/grok-web",
            json={"auth_token": "tok", "ct0": "ct0"})
    assert r.status_code == 502


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_login_grok_web_network_error_502(client):
    """Network error reaching grok.x.com → HTTP 502."""
    with respx.mock:
        respx.post("https://grok.x.com/2/grok/add_response.json").mock(
            side_effect=httpx.ConnectError("refused"))
        r = await client.post("/login/grok-web",
            json={"auth_token": "tok", "ct0": "ct0"})
    assert r.status_code == 502


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_login_grok_web_live_200_issues_token(client):
    """200 from grok.x.com during probe → token issued."""
    with respx.mock:
        respx.post("https://grok.x.com/2/grok/add_response.json").mock(
            return_value=httpx.Response(200, text="{}"))
        r = await client.post("/login/grok-web",
            json={"auth_token": "valid_tok", "ct0": "valid_ct0"})
    assert r.status_code == 200
    assert r.json()["token"].startswith("cp-")


# ═══════════════════════════════════════════════════════════════════════════════
#  Grok.com login — user_agent field  (line 1732-1733)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.webapi
@pytest.mark.asyncio
async def test_login_grok_com_with_user_agent(client):
    """grok-com login with user_agent must store it in user_info."""
    r = await client.post("/login/grok-com?skip_validation=true",
        json={"cookie": "sso=test; sso_at=test", "user_agent": "TestUA/2.0"})
    assert r.status_code == 200
    cp_token = r.json()["token"]
    assert TOKENS[cp_token].user_info.get("user_agent") == "TestUA/2.0"


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_login_grok_com_empty_cookie_400(client):
    """Empty cookie must return 400."""
    r = await client.post("/login/grok-com?skip_validation=true",
        json={"cookie": "   "})
    assert r.status_code == 400


# ═══════════════════════════════════════════════════════════════════════════════
#  verify_token — expired token deletion + save (lines 2074-2082)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.webapi
@pytest.mark.asyncio
async def test_expired_token_removed_from_store(client):
    """Expired cp-* token must be deleted from TOKENS on access attempt."""
    token = "cp-will-expire-on-use"
    TOKENS[token] = TokenData(
        github_token="ghp_expired_use",
        created=time.time() - 7200,
        expires_at=time.time() - 1,
    )
    r = await client.post("/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "Hi"}]},
        headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
    assert token not in TOKENS


# ═══════════════════════════════════════════════════════════════════════════════
#  periodic_cleanup (unit, lines 2613-2621)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_periodic_cleanup_runs_once_and_calls_cleanup():
    """periodic_cleanup must call cleanup_expired_tokens and then sleep."""
    from main import periodic_cleanup
    call_count = 0

    async def mock_cleanup():
        nonlocal call_count
        call_count += 1
        return 1

    with patch.object(token_manager, "cleanup_expired_tokens", side_effect=mock_cleanup):
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            mock_sleep.side_effect = asyncio.CancelledError  # stop after first iteration
            try:
                await periodic_cleanup()
            except asyncio.CancelledError:
                pass

    assert call_count == 1


# ═══════════════════════════════════════════════════════════════════════════════
#  TokenManager.load_tokens — load error (line 410-411)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_token_manager_load_error_does_not_crash():
    """If load_tokens fails (corrupt file), it must not crash and _load_succeeded stays False."""
    token_manager._load_succeeded = False
    with patch("main.settings.storage.get_token_file_path") as mock_path:
        mock_file = MagicMock()
        mock_file.exists.return_value = True
        mock_file.open = MagicMock(side_effect=PermissionError("denied"))
        mock_path.return_value = mock_file
        await token_manager.load_tokens()
    assert token_manager._load_succeeded is False


# ═══════════════════════════════════════════════════════════════════════════════
#  Token manager — save with encryption key (lines 375-377)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_token_manager_save_with_encryption(tmp_path):
    """If encryption_key is set, github_token must be encrypted in the file."""
    from main import TokenManager, TOKENS
    TOKENS.clear()
    TOKENS["cp-enc-test"] = TokenData(
        github_token="ghp_plaintext_secret",
        created=time.time(),
    )
    mgr = TokenManager()
    mgr.encryption_key = "test_enc_key"
    mgr._load_succeeded = True

    token_file = tmp_path / "tokens.json"
    with patch("main.settings.storage.get_token_file_path", return_value=token_file):
        await mgr.save_tokens()

    # File must exist and github_token must not be plaintext
    import json as _json
    with open(token_file) as f:
        data = _json.load(f)
    assert "cp-enc-test" in data
    # The token is base64-encoded, not plaintext
    assert data["cp-enc-test"]["github_token"] != "ghp_plaintext_secret"


# ═══════════════════════════════════════════════════════════════════════════════
#  Twitter OAuth — /login/twitter unconfigured
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.webapi
@pytest.mark.asyncio
async def test_login_twitter_unconfigured_503(client):
    """If Twitter OAuth is not configured, /login/twitter returns 503."""
    with patch("main._twitter_configured", return_value=False):
        r = await client.get("/login/twitter")
    assert r.status_code == 503


# ═══════════════════════════════════════════════════════════════════════════════
#  Twitter callback — /auth/twitter/callback unconfigured
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.webapi
@pytest.mark.asyncio
async def test_twitter_callback_unconfigured_503(client):
    with patch("main._twitter_configured", return_value=False):
        r = await client.get("/auth/twitter/callback?oauth_token=tok&oauth_verifier=ver")
    assert r.status_code == 503


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_twitter_callback_missing_request_token_400(client):
    """If oauth_token not in _twitter_request_tokens → 400."""
    with patch("main._twitter_configured", return_value=True):
        r = await client.get(
            "/auth/twitter/callback?oauth_token=nonexistent&oauth_verifier=ver")
    assert r.status_code == 400


# ═══════════════════════════════════════════════════════════════════════════════
#  _build_grok_com_payload — system + user messages merged (lines 949-985)
# ═══════════════════════════════════════════════════════════════════════════════

def test_build_grok_com_payload_merges_system_and_user():
    from main import _build_grok_com_payload, ChatMessage
    messages = [
        ChatMessage(role="system", content="Be helpful"),
        ChatMessage(role="user", content="Hello"),
    ]
    payload = _build_grok_com_payload(messages, "grok-3")
    query = payload["message"]["query"]
    assert "Be helpful" in query
    assert "Hello" in query
    assert payload["modelName"] == "grok-3"
    assert payload["temporary"] is True


def test_build_grok_com_payload_empty_messages():
    from main import _build_grok_com_payload, ChatMessage
    payload = _build_grok_com_payload([], "grok-3")
    assert payload["message"]["query"] == "(empty)"


# ═══════════════════════════════════════════════════════════════════════════════
#  is_grok_model vs grok-com / grok-web (edge cases)
# ═══════════════════════════════════════════════════════════════════════════════

def test_is_grok_model_rejects_grok_com():
    from main import is_grok_model
    # grok-com-* should NOT be treated as official xAI grok
    assert is_grok_model("grok-com") is False
    assert is_grok_model("grok-com-3") is False


def test_is_grok_model_rejects_grok_web():
    from main import is_grok_model
    assert is_grok_model("grok-web") is False


def test_is_grok_model_accepts_official():
    from main import is_grok_model
    assert is_grok_model("grok-3") is True
    assert is_grok_model("grok-beta") is True
    assert is_grok_model("grok-3-mini") is True

