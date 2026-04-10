"""
Integration tests for all HTTP endpoints.
External HTTP calls (GitHub, Copilot, xAI) are intercepted with respx, so
no real network access is required.

Markers
-------
webapi – pure JSON/REST API endpoints (no HTML rendering)
HTML – HTML page / template rendering tests

Run only API tests:  pytest -m webapi
Run only HTML tests: pytest -m HTML
"""
import time
import pytest
import httpx
import respx
from main import TOKENS, TokenData, normalize_model_name, is_grok_model, is_grok_web_model, is_grok_com_model
# ═══════════════════════════════════════════════════════════════════════════════
#  /health
# ═══════════════════════════════════════════════════════════════════════════════
@pytest.mark.webapi
@pytest.mark.asyncio
async def test_health_returns_200(client):
    r = await client.get("/health")
    assert r.status_code == 200
@pytest.mark.webapi
@pytest.mark.asyncio
async def test_health_response_fields(client):
    r = await client.get("/health")
    data = r.json()
    assert data["status"] == "healthy"
    assert data["service"] == "copilot-api-proxy"
    assert isinstance(data["active_tokens"], int)
    assert isinstance(data["uptime_seconds"], float)
    assert data["environment"] == "development"
    assert "version" in data
    assert "timestamp" in data
@pytest.mark.webapi
@pytest.mark.asyncio
async def test_health_active_tokens_reflects_store(client, valid_cp_token):
    r = await client.get("/health")
    assert r.json()["active_tokens"] == 1
@pytest.mark.webapi
@pytest.mark.asyncio
async def test_health_uptime_positive(client):
    r = await client.get("/health")
    assert r.json()["uptime_seconds"] >= 0.0
# ═══════════════════════════════════════════════════════════════════════════════
#  HTML pages
# ═══════════════════════════════════════════════════════════════════════════════
@pytest.mark.html
@pytest.mark.asyncio
async def test_index_returns_html(client):
    r = await client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
@pytest.mark.html
@pytest.mark.asyncio
async def test_login_returns_html(client):
    r = await client.get("/login")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
@pytest.mark.html
@pytest.mark.asyncio
async def test_dashboard_renders_without_template_error(client):
    """Regression: the JSDoc @typedef {{ }} must not crash Jinja2."""
    r = await client.get("/dashboard")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
@pytest.mark.html
@pytest.mark.asyncio
async def test_dashboard_jsdoc_typedef_verbatim(client):
    """JSDoc @property tags must appear literally in the dashboard HTML."""
    r = await client.get("/dashboard")
    body = r.text
    assert "@property {number} active_tokens" in body
    assert "@property {number} uptime_seconds" in body
    assert "@property {string} environment" in body
@pytest.mark.html
@pytest.mark.asyncio
async def test_login_success_no_token_returns_400(client):
    r = await client.get("/login/success")
    assert r.status_code == 400
@pytest.mark.html
@pytest.mark.asyncio
async def test_login_success_numeric_expires_in(client):
    """expires_in is Optional[int]; FastAPI must coerce the query string."""
    r = await client.get("/login/success?token=cp-test&expires_in=3600&expires_at=2027-01-01")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "1h" in r.text  # template renders 3600 // 3600 == 1
@pytest.mark.html
@pytest.mark.asyncio
async def test_login_success_without_expires_in(client):
    r = await client.get("/login/success?token=cp-test")
    assert r.status_code == 200
# ═══════════════════════════════════════════════════════════════════════════════
#  /v1/models
# ═══════════════════════════════════════════════════════════════════════════════
@pytest.mark.webapi
@pytest.mark.asyncio
async def test_models_unauthenticated(client):
    r = await client.get("/v1/models")
    assert r.status_code == 200
    data = r.json()
    assert data["object"] == "list"
    assert len(data["data"]) > 0
@pytest.mark.webapi
@pytest.mark.asyncio
async def test_models_schema(client):
    r = await client.get("/v1/models")
    for m in r.json()["data"]:
        assert "id" in m and "object" in m and m["object"] == "model"
@pytest.mark.webapi
@pytest.mark.asyncio
async def test_models_providers_present(client):
    ids = {m["id"] for m in (await client.get("/v1/models")).json()["data"]}
    assert any("gpt"    in i for i in ids)
    assert any("grok"   in i for i in ids)
    assert any("claude" in i for i in ids)
# ═══════════════════════════════════════════════════════════════════════════════
#  Authentication guards
# ═══════════════════════════════════════════════════════════════════════════════
@pytest.mark.webapi
@pytest.mark.asyncio
async def test_chat_no_auth_returns_401(client):
    r = await client.post("/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "Hi"}]})
    assert r.status_code == 401
@pytest.mark.webapi
@pytest.mark.asyncio
async def test_chat_invalid_bearer_returns_401(client):
    r = await client.post("/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "Hi"}]},
        headers={"Authorization": "Bearer invalid-token-xyz"})
    assert r.status_code == 401
@pytest.mark.webapi
@pytest.mark.asyncio
async def test_chat_expired_token_returns_401(client):
    token = "cp-expired-token-test"
    TOKENS[token] = TokenData(
        github_token="ghp_expired",
        created=time.time() - 7200,
        expires_at=time.time() - 3600,
    )
    r = await client.post("/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "Hi"}]},
        headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
@pytest.mark.webapi
@pytest.mark.asyncio
async def test_messages_no_auth_returns_401(client):
    r = await client.post("/v1/messages",
        json={"model": "claude-3-5-sonnet", "messages": [{"role": "user", "content": "Hi"}]})
    assert r.status_code == 401
# ═══════════════════════════════════════════════════════════════════════════════
#  Device flow
# ═══════════════════════════════════════════════════════════════════════════════
@pytest.mark.html
@pytest.mark.asyncio
async def test_device_flow_unconfigured_503(client):
    """Device flow must return 503 when the GitHub OAuth App is not configured."""
    from unittest.mock import patch
    with patch("main._github_configured", return_value=False):
        r = await client.get("/login/device")
    assert r.status_code == 503
# ═══════════════════════════════════════════════════════════════════════════════
#  Chat – Copilot backend
# ═══════════════════════════════════════════════════════════════════════════════
@pytest.mark.webapi
@pytest.mark.asyncio
async def test_chat_copilot_success(client, valid_cp_token):
    with respx.mock:
        respx.get("https://api.github.com/copilot_internal/v2/token").mock(
            return_value=httpx.Response(200, json={
                "token": "capi_test", "expires_at": "2027-01-01T00:00:00Z"}))
        respx.post("https://api.githubcopilot.com/chat/completions").mock(
            return_value=httpx.Response(200, json={
                "id": "chatcmpl-t", "object": "chat.completion", "model": "gpt-4o",
                "choices": [{"index": 0,
                    "message": {"role": "assistant", "content": "Copilot reply"},
                    "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15}}))
        r = await client.post("/v1/chat/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "Hi"}]},
            headers={"Authorization": f"Bearer {valid_cp_token}"})
    assert r.status_code == 200
    assert r.json()["choices"][0]["message"]["content"] == "Copilot reply"
@pytest.mark.webapi
@pytest.mark.asyncio
async def test_chat_copilot_token_exchange_401(client, valid_cp_token):
    with respx.mock:
        respx.get("https://api.github.com/copilot_internal/v2/token").mock(
            return_value=httpx.Response(401, json={"message": "Unauthorized"}))
        r = await client.post("/v1/chat/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "Hi"}]},
            headers={"Authorization": f"Bearer {valid_cp_token}"})
    assert r.status_code == 401
@pytest.mark.webapi
@pytest.mark.asyncio
async def test_chat_copilot_backend_429(client, valid_cp_token):
    with respx.mock:
        respx.get("https://api.github.com/copilot_internal/v2/token").mock(
            return_value=httpx.Response(200, json={
                "token": "capi_t", "expires_at": "2027-01-01T00:00:00Z"}))
        respx.post("https://api.githubcopilot.com/chat/completions").mock(
            return_value=httpx.Response(429, text="Too Many Requests"))
        r = await client.post("/v1/chat/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "Hi"}]},
            headers={"Authorization": f"Bearer {valid_cp_token}"})
    assert r.status_code == 429
@pytest.mark.webapi
@pytest.mark.asyncio
async def test_chat_grok_model_no_xai_key_503(client, valid_cp_token):
    r = await client.post("/v1/chat/completions",
        json={"model": "grok-3", "messages": [{"role": "user", "content": "Hi"}]},
        headers={"Authorization": f"Bearer {valid_cp_token}"})
    assert r.status_code == 503
# ═══════════════════════════════════════════════════════════════════════════════
#  Chat – xAI / Grok backend
# ═══════════════════════════════════════════════════════════════════════════════
@pytest.mark.webapi
@pytest.mark.asyncio
async def test_chat_xai_token_routes_to_xai(client):
    with respx.mock:
        respx.post("https://api.x.ai/v1/chat/completions").mock(
            return_value=httpx.Response(200, json={
                "id": "chatcmpl-grok", "object": "chat.completion", "model": "grok-3",
                "choices": [{"index": 0,
                    "message": {"role": "assistant", "content": "Grok here!"},
                    "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 5, "total_tokens": 8}}))
        r = await client.post("/v1/chat/completions",
            json={"model": "grok-3", "messages": [{"role": "user", "content": "Hi"}]},
            headers={"Authorization": "Bearer xai-testtoken1234"})
    assert r.status_code == 200
    assert r.json()["choices"][0]["message"]["content"] == "Grok here!"
# ═══════════════════════════════════════════════════════════════════════════════
#  Chat – Anthropic pass-through
# ═══════════════════════════════════════════════════════════════════════════════
@pytest.mark.webapi
@pytest.mark.asyncio
async def test_chat_anthropic_token_proxied(client):
    with respx.mock:
        respx.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(200, json={
                "id": "msg-test", "type": "message", "role": "assistant",
                "content": [{"type": "text", "text": "Claude reply"}],
                "model": "claude-3-5-sonnet-20241022",
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 5, "output_tokens": 10}}))
        r = await client.post("/v1/messages",
            json={"model": "claude-3-5-sonnet",
                  "messages": [{"role": "user", "content": "Hi"}],
                  "max_tokens": 100},
            headers={"Authorization": "Bearer sk-ant-testtoken123"})
    assert r.status_code == 200
# ═══════════════════════════════════════════════════════════════════════════════
#  Request validation
# ═══════════════════════════════════════════════════════════════════════════════
@pytest.mark.webapi
@pytest.mark.asyncio
async def test_chat_max_tokens_exceeded_returns_400(client, valid_cp_token):
    with respx.mock:
        respx.get("https://api.github.com/copilot_internal/v2/token").mock(
            return_value=httpx.Response(200, json={
                "token": "capi_t", "expires_at": "2027-01-01T00:00:00Z"}))
        r = await client.post("/v1/chat/completions",
            json={"model": "gpt-4o",
                  "messages": [{"role": "user", "content": "Hi"}],
                  "max_tokens": 999_999},
            headers={"Authorization": f"Bearer {valid_cp_token}"})
    assert r.status_code == 400
# ═══════════════════════════════════════════════════════════════════════════════
#  Pure-Python unit tests (model routing helpers)
# ═══════════════════════════════════════════════════════════════════════════════
@pytest.mark.webapi
def test_normalize_model_name_passthrough():
    # normalize_model_name is now a no-op; resolution via resolve_copilot_model()
    assert normalize_model_name("claude-sonnet-4.6") == "claude-sonnet-4.6"
    assert normalize_model_name("claude-opus-4.5") == "claude-opus-4.5"
@pytest.mark.webapi
def test_normalize_model_name_no_change():
    assert normalize_model_name("gpt-4o") == "gpt-4o"
    assert normalize_model_name("grok-3") == "grok-3"
    assert normalize_model_name("o1-mini") == "o1-mini"
@pytest.mark.webapi
def test_is_grok_model_official():
    assert is_grok_model("grok-3") is True
    assert is_grok_model("grok-beta") is True
    assert is_grok_model("grok-2-1212") is True
@pytest.mark.webapi
def test_is_grok_model_rejects_web():
    assert is_grok_model("grok-web") is False
    assert is_grok_model("grok-web-3") is False
    assert is_grok_model("gpt-4o") is False
@pytest.mark.webapi
def test_is_grok_web_model():
    assert is_grok_web_model("grok-web") is True
    assert is_grok_web_model("grok-web-3") is True
    assert is_grok_web_model("grok-web-3-mini") is True
    assert is_grok_web_model("grok-3") is False
    assert is_grok_web_model("gpt-4o") is False
# ═══════════════════════════════════════════════════════════════════════════════
#  grok.com backend
# ═══════════════════════════════════════════════════════════════════════════════
@pytest.mark.webapi
def test_is_grok_com_model():
    assert is_grok_com_model("grok-com") is True
    assert is_grok_com_model("grok-com-3") is True
    assert is_grok_com_model("grok-com-3-mini") is True
    assert is_grok_com_model("grok-3") is False
    assert is_grok_com_model("grok-web") is False
    assert is_grok_com_model("gpt-4o") is False
@pytest.mark.webapi
@pytest.mark.asyncio
async def test_grok_com_models_in_list(client):
    """grok-com-* models must appear in the unauthenticated /v1/models list."""
    r = await client.get("/v1/models")
    ids = {m["id"] for m in r.json()["data"]}
    assert "grok-com" in ids
    assert "grok-com-3" in ids
    assert "grok-com-3-mini" in ids
@pytest.mark.webapi
@pytest.mark.asyncio
async def test_grok_com_model_no_cookie_returns_401(client, valid_cp_token):
    """A cp-* token cannot be used directly for grok-com-* models."""
    r = await client.post("/v1/chat/completions",
        json={"model": "grok-com-3", "messages": [{"role": "user", "content": "Hi"}]},
        headers={"Authorization": f"Bearer {valid_cp_token}"})
    assert r.status_code == 401
@pytest.mark.webapi
@pytest.mark.asyncio
async def test_chat_grokcom_routes_to_grokcom(client):
    """A grokcom:: bearer token must be routed to the grok.com backend."""
    with respx.mock:
        respx.post("https://grok.com/rest/app-chat/conversations/new").mock(
            return_value=httpx.Response(200, text=(
                'data: {"result":{"token":"Hello from grok.com","isThinking":false}}\n'
                'data: {"result":{"isSoftStop":true}}\n'
            )))
        r = await client.post("/v1/chat/completions",
            json={"model": "grok-com-3", "messages": [{"role": "user", "content": "Hi"}]},
            headers={"Authorization": "Bearer grokcom::sso=fake; sso_at=fake"})
    assert r.status_code == 200
    assert r.json()["choices"][0]["message"]["content"] == "Hello from grok.com"
@pytest.mark.webapi
@pytest.mark.asyncio
async def test_login_grok_com_skip_validation(client):
    """?skip_validation=true must register cookies without probing grok.com."""
    r = await client.post("/login/grok-com?skip_validation=true",
        json={"cookie": "sso=test; sso_at=test"})
    assert r.status_code == 200
    data = r.json()
    assert data["token"].startswith("cp-")
    assert "grok-com" in data["message"].lower()
@pytest.mark.webapi
@pytest.mark.asyncio
async def test_login_grok_com_live_401_returns_401(client):
    """A 401 from grok.com during probe must surface as HTTP 401."""
    with respx.mock:
        respx.post("https://grok.com/rest/app-chat/conversations/new").mock(
            return_value=httpx.Response(401, text="Unauthorized"))
        r = await client.post("/login/grok-com", json={"cookie": "sso=bad"})
    assert r.status_code == 401
# ═══════════════════════════════════════════════════════════════════════════════
#  Token management (clear keys)
# ═══════════════════════════════════════════════════════════════════════════════
@pytest.mark.webapi
@pytest.mark.asyncio
async def test_list_tokens_requires_auth(client):
    r = await client.get("/admin/tokens")
    assert r.status_code == 401

@pytest.mark.webapi
@pytest.mark.asyncio
async def test_list_tokens_returns_store(client, valid_cp_token):
    r = await client.get("/admin/tokens",
        headers={"Authorization": f"Bearer {valid_cp_token}"})
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert data["tokens"][0]["token_id"] == valid_cp_token
    assert data["tokens"][0]["provider"] == "github"

@pytest.mark.webapi
@pytest.mark.asyncio
async def test_clear_expired_removes_only_expired(client, valid_cp_token):
    # add an already-expired token
    TOKENS["cp-expired-clear-test"] = TokenData(
        github_token="ghp_x", created=time.time() - 7200, expires_at=time.time() - 3600
    )
    r = await client.delete("/admin/tokens/expired",
        headers={"Authorization": f"Bearer {valid_cp_token}"})
    assert r.status_code == 200
    data = r.json()
    assert data["cleared"] == 1
    assert data["remaining"] == 1          # valid_cp_token still alive
    assert "cp-expired-clear-test" not in TOKENS
    assert valid_cp_token in TOKENS

@pytest.mark.webapi
@pytest.mark.asyncio
async def test_revoke_single_token(client, valid_cp_token):
    # add a second token, revoke it
    TOKENS["cp-to-revoke"] = TokenData(github_token="ghp_r", created=time.time())
    r = await client.delete("/admin/tokens/cp-to-revoke",
        headers={"Authorization": f"Bearer {valid_cp_token}"})
    assert r.status_code == 200
    assert r.json()["cleared"] == 1
    assert "cp-to-revoke" not in TOKENS

@pytest.mark.webapi
@pytest.mark.asyncio
async def test_revoke_missing_token_returns_404(client, valid_cp_token):
    r = await client.delete("/admin/tokens/cp-does-not-exist",
        headers={"Authorization": f"Bearer {valid_cp_token}"})
    assert r.status_code == 404

@pytest.mark.webapi
@pytest.mark.asyncio
async def test_clear_all_tokens(client, valid_cp_token):
    r = await client.delete("/admin/tokens",
        headers={"Authorization": f"Bearer {valid_cp_token}"})
    assert r.status_code == 200
    data = r.json()
    assert data["cleared"] >= 1
    assert data["remaining"] == 0
    assert len(TOKENS) == 0
