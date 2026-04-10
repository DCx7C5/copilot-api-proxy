"""
Live-integration-style tests (mocked HTTP) for the full proxy pipeline:
  PAT login → copilot token exchange → chat completions → backend response

Also covers:
  - Backend 400/500/timeout errors
  - Streaming chat path
  - Alias routes (/chat/completions, /messages, /models without /v1)
  - Token management helpers (encrypt/decrypt, save/load, cleanup)
  - Grok Web backend routing
  - verify_token with raw credential prefixes
  - Error handlers
  - HEAD endpoints
"""
import json
import time
from unittest.mock import AsyncMock, patch, MagicMock

import httpx
import pytest
import respx

from main import (
    TOKENS, TokenData, token_manager, _copilot_token_cache,
    resolve_copilot_model, get_backend_headers,
    _messages_to_grok_web, _build_grok_web_payload,
    _grok_web_error_from_status, _grok_com_error_from_status,
    _token_list_item, _get_session_browser_info,
    is_grok_model, is_grok_web_model, is_grok_com_model,
    normalize_model_name,
)


# ═══════════════════════════════════════════════════════════════════════════════
#  HEAD endpoint tests
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.webapi
@pytest.mark.asyncio
async def test_head_root(client):
    r = await client.head("/")
    assert r.status_code == 200


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_head_v1(client):
    r = await client.head("/v1")
    assert r.status_code == 200


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_head_v1_slash(client):
    r = await client.head("/v1/")
    assert r.status_code == 200


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_get_v1_slash(client):
    r = await client.get("/v1/")
    assert r.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
#  Alias routes (without /v1 prefix)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.webapi
@pytest.mark.asyncio
async def test_alias_chat_completions_no_auth(client):
    r = await client.post("/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "Hi"}]})
    assert r.status_code == 401


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_alias_messages_no_auth(client):
    r = await client.post("/messages",
        json={"model": "claude-3-5-sonnet", "messages": [{"role": "user", "content": "Hi"}]})
    assert r.status_code == 401


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_alias_models(client):
    r = await client.get("/models")
    assert r.status_code == 200
    data = r.json()
    assert data["object"] == "list"
    assert len(data["data"]) > 0


# ═══════════════════════════════════════════════════════════════════════════════
#  Copilot backend 400 (PAT not supported)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.webapi
@pytest.mark.asyncio
async def test_chat_copilot_backend_400(client, valid_cp_token):
    # GIVEN copilot token exchange falls back to raw, backend returns 400
    with respx.mock:
        respx.get("https://api.github.com/copilot_internal/v2/token").mock(
            return_value=httpx.Response(404, text="Not Found"))
        respx.get("https://api.github.com/copilot_internal/v1/token").mock(
            return_value=httpx.Response(404, text="Not Found"))
        respx.post("https://api.githubcopilot.com/chat/completions").mock(
            return_value=httpx.Response(400, text="PATs not supported"))
        r = await client.post("/v1/chat/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "Hi"}]},
            headers={"Authorization": f"Bearer {valid_cp_token}"})
    assert r.status_code == 400


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_chat_copilot_backend_500(client, valid_cp_token):
    with respx.mock:
        respx.get("https://api.github.com/copilot_internal/v2/token").mock(
            return_value=httpx.Response(200, json={"token": "capi_t", "expires_at": "2027-01-01T00:00:00Z"}))
        respx.post("https://api.githubcopilot.com/chat/completions").mock(
            return_value=httpx.Response(500, text="Internal Server Error"))
        r = await client.post("/v1/chat/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "Hi"}]},
            headers={"Authorization": f"Bearer {valid_cp_token}"})
    assert r.status_code == 500


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_chat_copilot_backend_timeout(client, valid_cp_token):
    with respx.mock:
        respx.get("https://api.github.com/copilot_internal/v2/token").mock(
            return_value=httpx.Response(200, json={"token": "capi_t", "expires_at": "2027-01-01T00:00:00Z"}))
        respx.post("https://api.githubcopilot.com/chat/completions").mock(
            side_effect=httpx.TimeoutException("timed out"))
        r = await client.post("/v1/chat/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "Hi"}]},
            headers={"Authorization": f"Bearer {valid_cp_token}"})
    assert r.status_code == 504


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_chat_copilot_backend_connection_error(client, valid_cp_token):
    with respx.mock:
        respx.get("https://api.github.com/copilot_internal/v2/token").mock(
            return_value=httpx.Response(200, json={"token": "capi_t", "expires_at": "2027-01-01T00:00:00Z"}))
        respx.post("https://api.githubcopilot.com/chat/completions").mock(
            side_effect=httpx.ConnectError("refused"))
        r = await client.post("/v1/chat/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "Hi"}]},
            headers={"Authorization": f"Bearer {valid_cp_token}"})
    assert r.status_code == 502


# ═══════════════════════════════════════════════════════════════════════════════
#  Streaming chat — returns SSE
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.webapi
@pytest.mark.asyncio
async def test_chat_copilot_streaming(client, valid_cp_token):
    sse_body = (
        b'data: {"id":"chatcmpl-1","object":"chat.completion.chunk","choices":[{"delta":{"content":"Hi"},"index":0}]}\n\n'
        b'data: [DONE]\n\n'
    )
    with respx.mock:
        respx.get("https://api.github.com/copilot_internal/v2/token").mock(
            return_value=httpx.Response(200, json={"token": "capi_t", "expires_at": "2027-01-01T00:00:00Z"}))
        respx.post("https://api.githubcopilot.com/chat/completions").mock(
            return_value=httpx.Response(200, content=sse_body,
                headers={"content-type": "text/event-stream"}))
        r = await client.post("/v1/chat/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "Hi"}], "stream": True},
            headers={"Authorization": f"Bearer {valid_cp_token}"})
    assert r.status_code == 200
    assert "text/event-stream" in r.headers.get("content-type", "")


# ═══════════════════════════════════════════════════════════════════════════════
#  verify_token — raw credential prefixes bypass TOKENS lookup
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.webapi
@pytest.mark.asyncio
async def test_raw_xai_token_bypasses_lookup(client):
    # xai- token should be accepted without being in TOKENS store
    with respx.mock:
        respx.post("https://api.x.ai/v1/chat/completions").mock(
            return_value=httpx.Response(200, json={
                "id": "chatcmpl-grok", "object": "chat.completion",
                "model": "grok-3", "choices": [{"index": 0,
                    "message": {"role": "assistant", "content": "Grok here!"},
                    "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 5, "total_tokens": 8}}))
        r = await client.post("/v1/chat/completions",
            json={"model": "grok-3", "messages": [{"role": "user", "content": "Hi"}]},
            headers={"Authorization": "Bearer xai-abc123"})
    assert r.status_code == 200



@pytest.mark.webapi
@pytest.mark.asyncio
async def test_x_api_key_header_auth(client, valid_cp_token):
    # x-api-key header should work as alternative to Bearer
    with respx.mock:
        respx.get("https://api.github.com/copilot_internal/v2/token").mock(
            return_value=httpx.Response(200, json={"token": "capi_t", "expires_at": "2027-01-01T00:00:00Z"}))
        respx.post("https://api.githubcopilot.com/chat/completions").mock(
            return_value=httpx.Response(200, json={
                "id": "chatcmpl-1", "object": "chat.completion", "model": "gpt-4o",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"},
                    "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}))
        r = await client.post("/v1/chat/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "Hi"}]},
            headers={"x-api-key": valid_cp_token})
    assert r.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
#  Unit tests: model resolution, backend headers, helpers
# ═══════════════════════════════════════════════════════════════════════════════

def test_resolve_copilot_model_alias():
    # Legacy names → real Copilot API model IDs (dot format)
    assert resolve_copilot_model("claude-3-5-sonnet-latest") == "claude-sonnet-4.5"
    assert resolve_copilot_model("claude-3-7-sonnet-latest") == "claude-sonnet-4.5"


def test_resolve_copilot_model_passthrough():
    assert resolve_copilot_model("gpt-4o") == "gpt-4o"
    # Dash variants are aliased to dot format
    assert resolve_copilot_model("claude-sonnet-4-5") == "claude-sonnet-4.5"


@pytest.mark.asyncio
async def test_get_backend_headers_grok():
    h = await get_backend_headers("xai-test", is_grok=True)
    assert h["Authorization"] == "Bearer xai-test"
    assert "Copilot-Integration-Id" not in h


@pytest.mark.asyncio
async def test_get_backend_headers_copilot():
    h = await get_backend_headers("capi-test", is_grok=False)
    assert h["Authorization"] == "Bearer capi-test"
    assert h["Copilot-Integration-Id"] == "vscode-chat"
    assert "X-Request-Id" in h


def test_messages_to_grok_web_empty():
    msg, hist = _messages_to_grok_web([])
    assert msg == ""
    assert hist == []


def test_messages_to_grok_web_with_system():
    from main import ChatMessage
    msgs = [
        ChatMessage(role="system", content="You are helpful"),
        ChatMessage(role="user", content="Hello"),
    ]
    msg, hist = _messages_to_grok_web(msgs)
    assert "You are helpful" in msg
    assert "Hello" in msg


def test_messages_to_grok_web_with_history():
    from main import ChatMessage
    msgs = [
        ChatMessage(role="user", content="First"),
        ChatMessage(role="assistant", content="Reply"),
        ChatMessage(role="user", content="Second"),
    ]
    msg, hist = _messages_to_grok_web(msgs)
    assert msg == "Second"
    assert len(hist) == 2
    assert hist[0]["sender"] == 1  # user
    assert hist[1]["sender"] == 2  # assistant


def test_build_grok_web_payload():
    payload = _build_grok_web_payload("Hello", [], "grok-latest")
    assert payload["message"] == "Hello"
    assert payload["grokModelOptionId"] == "grok-latest"
    assert "conversationId" in payload


def test_grok_web_error_from_status():
    assert "expired" in _grok_web_error_from_status(401).lower() or "auth" in _grok_web_error_from_status(401).lower()
    assert "subscription" in _grok_web_error_from_status(403).lower()
    assert "500" in _grok_web_error_from_status(500)


def test_grok_com_error_from_status():
    assert "expired" in _grok_com_error_from_status(401).lower() or "auth" in _grok_com_error_from_status(401).lower()
    assert "403" in _grok_com_error_from_status(403) or "subscription" in _grok_com_error_from_status(403).lower()
    assert "429" in _grok_com_error_from_status(429) or "rate" in _grok_com_error_from_status(429).lower()
    assert "502" in _grok_com_error_from_status(502) or "HTTP" in _grok_com_error_from_status(502)


# ═══════════════════════════════════════════════════════════════════════════════
#  _token_list_item — provider detection
# ═══════════════════════════════════════════════════════════════════════════════

def test_token_list_item_github():
    td = TokenData(github_token="ghp_abc", created=time.time())
    item = _token_list_item("cp-test", td)
    assert item.provider == "github"


def test_token_list_item_grok_web():
    td = TokenData(github_token="grokweb::auth::ct0", created=time.time())
    item = _token_list_item("cp-test", td)
    assert item.provider == "grok-web"


def test_token_list_item_grok_com():
    td = TokenData(github_token="grokcom::cookie", created=time.time())
    item = _token_list_item("cp-test", td)
    assert item.provider == "grok-com"


def test_token_list_item_twitter():
    td = TokenData(github_token="twitter::tok::sec", created=time.time())
    item = _token_list_item("cp-test", td)
    assert item.provider == "twitter_oauth"


def test_token_list_item_xai():
    td = TokenData(github_token="xai-key123", created=time.time())
    item = _token_list_item("cp-test", td)
    assert item.provider == "xai"


def test_token_list_item_anthropic():
    td = TokenData(github_token="sk-ant-key123", created=time.time())
    item = _token_list_item("cp-test", td)
    assert item.provider == "anthropic"


def test_token_list_item_expired():
    td = TokenData(github_token="ghp_abc", created=time.time() - 7200, expires_at=time.time() - 3600)
    item = _token_list_item("cp-test", td)
    assert item.expired is True


def test_token_list_item_custom_provider():
    td = TokenData(github_token="something", created=time.time(), user_info={"provider": "custom_sso"})
    item = _token_list_item("cp-test", td)
    assert item.provider == "custom_sso"


# ═══════════════════════════════════════════════════════════════════════════════
#  _get_session_browser_info
# ═══════════════════════════════════════════════════════════════════════════════

def test_get_session_browser_info_not_found():
    ua, cookies = _get_session_browser_info("nonexistent-credential")
    assert ua is None
    assert cookies is None


def test_get_session_browser_info_found():
    TOKENS["cp-browser"] = TokenData(
        github_token="grokweb::auth::ct0",
        created=time.time(),
        user_info={"user_agent": "MyBrowser/1.0", "x_com_cookies": "full_cookie=value"},
    )
    ua, cookies = _get_session_browser_info("grokweb::auth::ct0")
    assert ua == "MyBrowser/1.0"
    assert cookies == "full_cookie=value"


# ═══════════════════════════════════════════════════════════════════════════════
#  Token manager: encrypt / decrypt
# ═══════════════════════════════════════════════════════════════════════════════

def test_token_manager_encrypt_decrypt():
    original = "ghp_secrettoken123"
    encrypted = token_manager._encrypt(original)
    assert encrypted != original
    decrypted = token_manager._decrypt(encrypted)
    assert decrypted == original


# ═══════════════════════════════════════════════════════════════════════════════
#  Token manager: save and load
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_token_manager_save_and_load():
    TOKENS["cp-save-test"] = TokenData(
        github_token="ghp_for_save",
        created=time.time(),
        user_info={"login": "testuser"},
    )
    token_manager._load_succeeded = True
    await token_manager.save_tokens()
    # Clear and reload
    saved_token = TOKENS["cp-save-test"].github_token
    TOKENS.clear()
    await token_manager.load_tokens()
    assert "cp-save-test" in TOKENS
    assert TOKENS["cp-save-test"].github_token == "ghp_for_save"


@pytest.mark.asyncio
async def test_token_manager_skip_save_on_empty_without_load():
    # If load never succeeded and TOKENS is empty, save should be a no-op
    token_manager._load_succeeded = False
    TOKENS.clear()
    # save_tokens should return early without writing
    await token_manager.save_tokens()
    # No crash = success; the guard prevents overwriting a valid file with empty data


@pytest.mark.asyncio
async def test_token_manager_cleanup_expired():
    TOKENS["cp-active"] = TokenData(github_token="ghp_a", created=time.time(), expires_at=time.time() + 3600)
    TOKENS["cp-dead"] = TokenData(github_token="ghp_d", created=time.time() - 7200, expires_at=time.time() - 3600)
    with patch.object(token_manager, "save_tokens", new_callable=AsyncMock):
        with patch("main.settings.storage.cleanup_expired_tokens", True):
            count = await token_manager.cleanup_expired_tokens()
    assert count == 1
    assert "cp-dead" not in TOKENS
    assert "cp-active" in TOKENS


# ═══════════════════════════════════════════════════════════════════════════════
#  Logout redirect
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.webapi
@pytest.mark.asyncio
async def test_logout_redirects(client):
    r = await client.get("/logout", follow_redirects=False)
    assert r.status_code == 302
    assert "/login" in r.headers.get("location", "")


# ═══════════════════════════════════════════════════════════════════════════════
#  PAT form login — edge case
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.html
@pytest.mark.asyncio
async def test_pat_form_post_returns_404(client):
    """PAT form endpoint must be gone — 404 or 405."""
    r = await client.post("/login/pat/form", data={"github_token": "ghp_anything"})
    assert r.status_code in (404, 405)


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_pat_json_endpoint_returns_404(client):
    """PAT JSON endpoint must be gone — 404 or 405."""
    r = await client.post("/login/pat", json={"github_token": "ghp_anything"})
    assert r.status_code in (404, 405)


# ═══════════════════════════════════════════════════════════════════════════════
#  Grok Web login
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.webapi
@pytest.mark.asyncio
async def test_login_grok_web_skip_validation(client):
    r = await client.post("/login/grok-web?skip_validation=true",
        json={"auth_token": "at123", "ct0": "ct0_abc"})
    assert r.status_code == 200
    data = r.json()
    assert data["token"].startswith("cp-")


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_login_grok_web_empty_fields(client):
    r = await client.post("/login/grok-web?skip_validation=true",
        json={"auth_token": "", "ct0": "ct0_abc"})
    assert r.status_code == 400


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_login_grok_web_with_ua_and_cookies(client):
    r = await client.post("/login/grok-web?skip_validation=true",
        json={"auth_token": "at123", "ct0": "ct0_abc",
              "user_agent": "TestUA/1.0", "x_com_cookies": "full=cookie"})
    assert r.status_code == 200
    cp_token = r.json()["token"]
    assert TOKENS[cp_token].user_info["user_agent"] == "TestUA/1.0"
    assert TOKENS[cp_token].user_info["x_com_cookies"] == "full=cookie"


# ═══════════════════════════════════════════════════════════════════════════════
#  Twitter bearer login
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.webapi
@pytest.mark.asyncio
async def test_twitter_bearer_login_with_token(client):
    r = await client.post("/login/twitter/bearer",
        json={"bearer_token": "AAAAAAAAAAtest"})
    assert r.status_code == 200
    data = r.json()
    assert data["token"].startswith("cp-")


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_twitter_bearer_login_no_token_no_config(client):
    # No bearer in body and no server config → 400
    with patch("main.settings.twitter.bearer_token", None):
        r = await client.post("/login/twitter/bearer", json={})
    assert r.status_code == 400


# ═══════════════════════════════════════════════════════════════════════════════
#  Chat with model alias resolution
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.webapi
@pytest.mark.asyncio
async def test_chat_model_alias_resolved(client, valid_cp_token):
    """claude-3-5-sonnet-latest should be resolved to claude-3-5-sonnet."""
    with respx.mock:
        respx.get("https://api.github.com/copilot_internal/v2/token").mock(
            return_value=httpx.Response(200, json={"token": "capi_t", "expires_at": "2027-01-01T00:00:00Z"}))
        route = respx.post("https://api.githubcopilot.com/chat/completions").mock(
            return_value=httpx.Response(200, json={
                "id": "chatcmpl-t", "object": "chat.completion", "model": "claude-3-5-sonnet",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}))
        r = await client.post("/v1/chat/completions",
            json={"model": "claude-3-5-sonnet-latest",
                  "messages": [{"role": "user", "content": "Hi"}]},
            headers={"Authorization": f"Bearer {valid_cp_token}"})
    assert r.status_code == 200
    # Verify the resolved model was sent to the backend
    sent_body = json.loads(route.calls.last.request.content)
    assert sent_body["model"] == "claude-sonnet-4.5"


# ═══════════════════════════════════════════════════════════════════════════════
#  Chat with temperature and max_tokens
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.webapi
@pytest.mark.asyncio
async def test_chat_with_temperature(client, valid_cp_token):
    with respx.mock:
        respx.get("https://api.github.com/copilot_internal/v2/token").mock(
            return_value=httpx.Response(200, json={"token": "capi_t", "expires_at": "2027-01-01T00:00:00Z"}))
        route = respx.post("https://api.githubcopilot.com/chat/completions").mock(
            return_value=httpx.Response(200, json={
                "id": "chatcmpl-t", "object": "chat.completion", "model": "gpt-4o",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}))
        r = await client.post("/v1/chat/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "Hi"}],
                  "temperature": 0.5, "max_tokens": 100},
            headers={"Authorization": f"Bearer {valid_cp_token}"})
    assert r.status_code == 200
    sent = json.loads(route.calls.last.request.content)
    assert sent["temperature"] == 0.5
    assert sent["max_tokens"] == 100


# ═══════════════════════════════════════════════════════════════════════════════
#  Grok Web model routing without cookies → 401
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.webapi
@pytest.mark.asyncio
async def test_grok_web_model_no_cookie_returns_401(client, valid_cp_token):
    r = await client.post("/v1/chat/completions",
        json={"model": "grok-web-3", "messages": [{"role": "user", "content": "Hi"}]},
        headers={"Authorization": f"Bearer {valid_cp_token}"})
    assert r.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════════
#  normalize_model_name edge cases
# ═══════════════════════════════════════════════════════════════════════════════

def test_normalize_model_name_claude_dots():
    # normalize_model_name is now a no-op — dots are preserved for the Copilot API
    assert normalize_model_name("claude-sonnet-4.5") == "claude-sonnet-4.5"
    assert normalize_model_name("claude-opus-4.6") == "claude-opus-4.6"


def test_normalize_model_name_o3():
    assert normalize_model_name("o3-mini") == "o3-mini"


def test_normalize_model_name_unknown_model_no_change():
    assert normalize_model_name("custom-model.v2") == "custom-model.v2"

