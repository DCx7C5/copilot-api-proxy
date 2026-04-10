"""
Device Flow tests — core coverage of:
  - _github_configured()  (unit)
  - GET /login/device
  - GET /login/device/poll
"""
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
    with patch("main.settings.github.client_id", cid), \
         patch("main.settings.github.device_flow_client_id", None):
        assert _github_configured() is False


def test_github_configured_true_for_real_id():
    with patch("main.settings.github.client_id", "Iv1.abc123realclientid"), \
         patch("main.settings.github.device_flow_client_id", None):
        assert _github_configured() is True


def test_device_flow_help_returns_nonempty_string():
    msg = _github_device_flow_help()
    assert isinstance(msg, str) and len(msg) > 20


# ═══════════════════════════════════════════════════════════════════════════════
#  GET /login/device
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.html
@pytest.mark.asyncio
async def test_device_flow_not_configured_returns_503(client):
    with patch("main._github_configured", return_value=False):
        r = await client.get("/login/device")
    assert r.status_code == 503


@pytest.mark.html
@pytest.mark.asyncio
async def test_device_flow_github_non200_returns_502(client):
    with patch("main._github_configured", return_value=True), respx.mock:
        respx.post("https://github.com/login/device/code").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        r = await client.get("/login/device")
    assert r.status_code == 502


@pytest.mark.html
@pytest.mark.asyncio
async def test_device_flow_github_error_returns_400(client):
    with patch("main._github_configured", return_value=True), respx.mock:
        respx.post("https://github.com/login/device/code").mock(
            return_value=httpx.Response(200, json={
                "error": "invalid_scope",
                "error_description": "The scopes requested are invalid: models:read.",
            })
        )
        r = await client.get("/login/device")
    assert r.status_code == 400
    assert "models:read" in r.json()["error"]["message"]


@pytest.mark.html
@pytest.mark.asyncio
async def test_device_flow_success_renders_html_with_user_code(client):
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
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "ABCD-1234" in r.text


# ═══════════════════════════════════════════════════════════════════════════════
#  GET /login/device/poll
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.webapi
@pytest.mark.asyncio
async def test_device_poll_not_configured_returns_503(client):
    with patch("main._github_configured", return_value=False):
        r = await client.get("/login/device/poll?device_code=anycode")
    assert r.status_code == 503


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_device_poll_github_non200_returns_error(client):
    with patch("main._github_configured", return_value=True), respx.mock:
        respx.post("https://github.com/login/oauth/access_token").mock(
            return_value=httpx.Response(502, text="Bad Gateway")
        )
        r = await client.get("/login/device/poll?device_code=test-code")
    assert r.status_code == 200
    assert r.json()["status"] == "error"


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_device_poll_authorization_pending(client):
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
    with patch("main._github_configured", return_value=True), respx.mock:
        respx.post("https://github.com/login/oauth/access_token").mock(
            return_value=httpx.Response(200, json={"error": "access_denied"})
        )
        r = await client.get("/login/device/poll?device_code=denied-code")
    assert r.status_code == 400
    assert "access_denied" in r.json()["error"]["message"]


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_device_poll_missing_device_code_param(client):
    with patch("main._github_configured", return_value=True):
        r = await client.get("/login/device/poll")
    assert r.status_code == 422


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_device_poll_success_stores_token(client):
    with patch("main._github_configured", return_value=True), respx.mock:
        respx.post("https://github.com/login/oauth/access_token").mock(
            return_value=httpx.Response(200, json={
                "access_token": "gho_device_flow_token",
                "token_type": "bearer",
            })
        )
        respx.get("https://api.github.com/user").mock(
            return_value=httpx.Response(200, json={"login": "octocat", "id": 42})
        )
        r = await client.get("/login/device/poll?device_code=valid-code")

    assert r.status_code == 200
    data = r.json()
    assert data["token"].startswith("cp-")
    assert data["expires_in"] > 0
    assert "expires_at" in data
    cp_token = data["token"]
    assert TOKENS[cp_token].github_token == "gho_device_flow_token"
    assert TOKENS[cp_token].user_info["login"] == "octocat"


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_device_poll_expiry_uses_max_of_github_and_config(client):
    # Bug fix: GitHub returns expires_in=28800 (8h), config minimum must win
    with patch("main._github_configured", return_value=True), respx.mock:
        respx.post("https://github.com/login/oauth/access_token").mock(
            return_value=httpx.Response(200, json={
                "access_token": "gho_exp_test",
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
    assert r.json()["expires_in"] >= config_expires


@pytest.mark.webapi
@pytest.mark.asyncio
async def test_device_poll_no_github_expiry_falls_back_to_config(client):
    with patch("main._github_configured", return_value=True), respx.mock:
        respx.post("https://github.com/login/oauth/access_token").mock(
            return_value=httpx.Response(200, json={"access_token": "gho_noexp"})
        )
        respx.get("https://api.github.com/user").mock(
            return_value=httpx.Response(200, json={"login": "dev"})
        )
        r = await client.get("/login/device/poll?device_code=noexp-code")

    from config import get_settings
    expected = get_settings().security.token_expiry_hours * 3600
    assert r.json()["expires_in"] == expected
