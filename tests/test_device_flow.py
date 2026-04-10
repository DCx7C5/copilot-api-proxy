"""
Device Flow tests — full coverage of:
  - _github_configured()  (unit)
  - _github_device_flow_help()  (unit)
  - GET /login/device        (all branches)
  - GET /login/device/poll   (all branches)
"""
import time
from unittest.mock import patch

import httpx
import pytest
import respx

from main import TOKENS, _github_configured, _github_device_flow_help


# ═══════════════════════════════════════════════════════════════════════════════
#  Unit: _github_configured()
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("cid", [
    "",
    "your_client_id_here",
    "your_github_client_id",
    "none",
    "changeme",
])
def test_github_configured_false_for_placeholders(cid):
    # GIVEN a placeholder or empty client_id
    with patch("main.settings.github.client_id", cid):
        # WHEN we check if GitHub is configured
        result = _github_configured()
    # THEN it must return False
    assert result is False


def test_github_configured_true_for_real_id():
    # GIVEN a real (non-placeholder) GitHub OAuth App client ID
    with patch("main.settings.github.client_id", "Iv1.abc123realclientid"):
        result = _github_configured()
    assert result is True


def test_github_configured_case_insensitive():
    # GIVEN a placeholder in mixed case
    with patch("main.settings.github.client_id", "YOUR_CLIENT_ID_HERE"):
        result = _github_configured()
    assert result is False


def test_github_configured_none_value():
    # GIVEN None (unset)
    with patch("main.settings.github.client_id", None):
        result = _github_configured()
    assert result is False


# ═══════════════════════════════════════════════════════════════════════════════
#  Unit: _github_device_flow_help()
# ═══════════════════════════════════════════════════════════════════════════════

def test_device_flow_help_returns_nonempty_string():
    msg = _github_device_flow_help()
    assert isinstance(msg, str)
    assert len(msg) > 20
    assert "GITHUB__CLIENT_ID" in msg or "Device Flow" in msg


# ═══════════════════════════════════════════════════════════════════════════════
#  GET /login/device — all branches
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.html
@pytest.mark.asyncio
async def test_device_flow_not_configured_returns_503(client):
    # GIVEN device flow is not configured
    with patch("main._github_configured", return_value=False):
        r = await client.get("/login/device")
    # THEN 503 is returned
    assert r.status_code == 503


@pytest.mark.html
@pytest.mark.asyncio
async def test_device_flow_github_non200_returns_502(client):
    # GIVEN GitHub device/code endpoint returns 500
    with patch("main._github_configured", return_value=True), respx.mock:
        respx.post("https://github.com/login/device/code").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        r = await client.get("/login/device")
    # THEN proxy returns 502
    assert r.status_code == 502


@pytest.mark.html
@pytest.mark.asyncio
async def test_device_flow_github_error_with_description_returns_400(client):
    # GIVEN GitHub returns 200 but with an error + description
    with patch("main._github_configured", return_value=True), respx.mock:
        respx.post("https://github.com/login/device/code").mock(
            return_value=httpx.Response(200, json={
                "error": "invalid_scope",
                "error_description": "The scopes requested are invalid: models:read.",
            })
        )
        r = await client.get("/login/device")
    # THEN 400 with the human-readable description inside {"error": {"message": ...}}
    assert r.status_code == 400
    assert "models:read" in r.json()["error"]["message"]


@pytest.mark.html
@pytest.mark.asyncio
async def test_device_flow_github_error_without_description_returns_400(client):
    # GIVEN GitHub returns 200 with an error but no error_description
    with patch("main._github_configured", return_value=True), respx.mock:
        respx.post("https://github.com/login/device/code").mock(
            return_value=httpx.Response(200, json={"error": "not_implemented"})
        )
        r = await client.get("/login/device")
    assert r.status_code == 400
    assert "not_implemented" in r.json()["error"]["message"]


@pytest.mark.html
@pytest.mark.asyncio
async def test_device_flow_success_renders_html(client):
    # GIVEN GitHub returns a valid device code response
    with patch("main._github_configured", return_value=True), respx.mock:
        respx.post("https://github.com/login/device/code").mock(
            return_value=httpx.Response(200, json={
                "device_code": "dev-abc-123",
                "user_code": "ABCD-1234",
                "verification_uri": "https://github.com/login/device",
                "expires_in": 900,
                "interval": 5,
            })
        )
        r = await client.get("/login/device")
    # THEN HTML page is returned
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


@pytest.mark.html
@pytest.mark.asyncio
async def test_device_flow_success_html_contains_user_code(client):
    # GIVEN a successful device code request
    with patch("main._github_configured", return_value=True), respx.mock:
        respx.post("https://github.com/login/device/code").mock(
            return_value=httpx.Response(200, json={
                "device_code": "dev-abc-123",
                "user_code": "ABCD-1234",
                "verification_uri": "https://github.com/login/device",
                "expires_in": 900,
                "interval": 5,
            })
        )
        r = await client.get("/login/device")
    # THEN the user_code appears in the rendered HTML
    assert "ABCD-1234" in r.text


@pytest.mark.html
@pytest.mark.asyncio
async def test_device_flow_success_html_contains_poll_url(client):
    # GIVEN a successful device code request
    with patch("main._github_configured", return_value=True), respx.mock:
        respx.post("https://github.com/login/device/code").mock(
            return_value=httpx.Response(200, json={
                "device_code": "my-device-code-xyz",
                "user_code": "XXXX-9999",
                "verification_uri": "https://github.com/login/device",
                "expires_in": 900,
                "interval": 5,
            })
        )
        r = await client.get("/login/device")
    # THEN the poll URL with device_code is embedded
    assert "my-device-code-xyz" in r.text


# ═══════════════════════════════════════════════════════════════════════════════
#  GET /login/device/poll — all branches
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.webapi
@pytest.mark.asyncio
async def test_device_poll_not_configured_returns_503(client):
    # GIVEN device flow is not configured
    with patch("main._github_configured", return_value=False):
        r = await client.get("/login/device/poll?device_code=anycode")
    assert r.status_code == 503


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_device_poll_github_non200_returns_error_status(client):
    # GIVEN GitHub token endpoint returns 502
    with patch("main._github_configured", return_value=True), respx.mock:
        respx.post("https://github.com/login/oauth/access_token").mock(
            return_value=httpx.Response(502, text="Bad Gateway")
        )
        r = await client.get("/login/device/poll?device_code=test-code")
    # THEN returns {"status": "error", ...} (not an HTTP error)
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "error"
    assert "502" in data["detail"]


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_device_poll_authorization_pending(client):
    # GIVEN GitHub says still waiting for user approval
    with patch("main._github_configured", return_value=True), respx.mock:
        respx.post("https://github.com/login/oauth/access_token").mock(
            return_value=httpx.Response(200, json={"error": "authorization_pending"})
        )
        r = await client.get("/login/device/poll?device_code=test-code")
    assert r.status_code == 200
    assert r.json()["status"] == "authorization_pending"


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_device_poll_slow_down(client):
    # GIVEN GitHub asks us to slow down polling
    with patch("main._github_configured", return_value=True), respx.mock:
        respx.post("https://github.com/login/oauth/access_token").mock(
            return_value=httpx.Response(200, json={"error": "slow_down"})
        )
        r = await client.get("/login/device/poll?device_code=test-code")
    assert r.status_code == 200
    assert r.json()["status"] == "slow_down"


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_device_poll_expired_token_returns_400(client):
    # GIVEN device code has expired
    with patch("main._github_configured", return_value=True), respx.mock:
        respx.post("https://github.com/login/oauth/access_token").mock(
            return_value=httpx.Response(200, json={
                "error": "expired_token",
                "error_description": "The device code has expired.",
            })
        )
        r = await client.get("/login/device/poll?device_code=expired-code")
    assert r.status_code == 400
    assert "expired" in r.json()["error"]["message"].lower()


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_device_poll_access_denied_returns_400(client):
    # GIVEN user explicitly denied the request (no error_description)
    with patch("main._github_configured", return_value=True), respx.mock:
        respx.post("https://github.com/login/oauth/access_token").mock(
            return_value=httpx.Response(200, json={"error": "access_denied"})
        )
        r = await client.get("/login/device/poll?device_code=denied-code")
    assert r.status_code == 400
    assert "access_denied" in r.json()["error"]["message"]


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_device_poll_no_access_token_returns_pending(client):
    # GIVEN response has no error but also no access_token yet
    with patch("main._github_configured", return_value=True), respx.mock:
        respx.post("https://github.com/login/oauth/access_token").mock(
            return_value=httpx.Response(200, json={"something_else": "value"})
        )
        r = await client.get("/login/device/poll?device_code=test-code")
    assert r.status_code == 200
    assert r.json()["status"] == "pending"


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_device_poll_success_stores_token(client):
    # GIVEN GitHub grants access_token and user fetch succeeds
    with patch("main._github_configured", return_value=True), respx.mock:
        respx.post("https://github.com/login/oauth/access_token").mock(
            return_value=httpx.Response(200, json={
                "access_token": "ghp_device_flow_token",
                "token_type": "bearer",
            })
        )
        respx.get("https://api.github.com/user").mock(
            return_value=httpx.Response(200, json={"login": "octocat", "id": 42})
        )
        r = await client.get("/login/device/poll?device_code=valid-code")

    # THEN 200 with cp-* token
    assert r.status_code == 200
    data = r.json()
    assert data["token"].startswith("cp-")
    assert isinstance(data["expires_in"], (int, float)) and data["expires_in"] > 0
    assert "expires_at" in data

    # AND token is stored with correct github_token
    cp_token = data["token"]
    assert cp_token in TOKENS
    assert TOKENS[cp_token].github_token == "ghp_device_flow_token"
    assert TOKENS[cp_token].user_info["login"] == "octocat"


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_device_poll_success_user_fetch_fails_token_still_stored(client):
    # GIVEN GitHub grants token but /user fetch fails
    with patch("main._github_configured", return_value=True), respx.mock:
        respx.post("https://github.com/login/oauth/access_token").mock(
            return_value=httpx.Response(200, json={
                "access_token": "ghp_no_user_info",
                "token_type": "bearer",
            })
        )
        respx.get("https://api.github.com/user").mock(
            return_value=httpx.Response(500, text="error")
        )
        r = await client.get("/login/device/poll?device_code=valid-code")

    # THEN token is still issued (user_info is empty but token is valid)
    assert r.status_code == 200
    data = r.json()
    cp_token = data["token"]
    assert cp_token in TOKENS
    assert TOKENS[cp_token].github_token == "ghp_no_user_info"
    assert TOKENS[cp_token].user_info == {} or TOKENS[cp_token].user_info is None or TOKENS[cp_token].user_info == {}


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_device_poll_success_uses_github_expires_in(client):
    # GIVEN GitHub provides expires_in (8h = 28800s) but config minimum is larger
    # → max(28800, token_expiry_hours * 3600) is used
    with patch("main._github_configured", return_value=True), respx.mock:
        respx.post("https://github.com/login/oauth/access_token").mock(
            return_value=httpx.Response(200, json={
                "access_token": "ghp_exp_test",
                "expires_in": 28800,
            })
        )
        respx.get("https://api.github.com/user").mock(
            return_value=httpx.Response(200, json={"login": "dev"})
        )
        r = await client.get("/login/device/poll?device_code=exp-code")

    from config import get_settings
    config_expires = get_settings().security.token_expiry_hours * 3600
    assert r.status_code == 200
    # Result must be at least as long as config minimum
    assert r.json()["expires_in"] >= config_expires


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_device_poll_success_falls_back_to_settings_expiry(client):
    # GIVEN GitHub does NOT provide expires_in → settings default used
    with patch("main._github_configured", return_value=True), respx.mock:
        respx.post("https://github.com/login/oauth/access_token").mock(
            return_value=httpx.Response(200, json={"access_token": "ghp_noexp"})
        )
        respx.get("https://api.github.com/user").mock(
            return_value=httpx.Response(200, json={"login": "dev"})
        )
        r = await client.get("/login/device/poll?device_code=noexp-code")

    data = r.json()
    from config import get_settings
    expected = get_settings().security.token_expiry_hours * 3600
    assert data["expires_in"] == expected


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_device_poll_missing_device_code_param(client):
    # GIVEN no device_code query parameter
    with patch("main._github_configured", return_value=True):
        r = await client.get("/login/device/poll")
    # THEN FastAPI returns 422 Unprocessable Entity
    assert r.status_code == 422


