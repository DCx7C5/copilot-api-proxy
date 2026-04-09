"""
Unit tests for configuration management (config.py).
No HTTP calls are needed – just Settings/ConfigManager logic.
"""

from pathlib import Path

# conftest.py has already forced SERVER__MODE=development before config was loaded.
from config import get_settings


def test_environment_is_development():
    cfg = get_settings()
    assert cfg.environment == "development"


def test_server_mode_is_development():
    cfg = get_settings()
    assert cfg.server.mode == "development"


def test_version_set():
    cfg = get_settings()
    assert cfg.version, "Version string must not be empty"
    # Basic semver-ish check: X.Y.Z
    parts = cfg.version.split(".")
    assert len(parts) == 3, f"Expected X.Y.Z, got {cfg.version!r}"


def test_storage_data_dir_overridden():
    cfg = get_settings()
    assert cfg.storage.data_dir == "/tmp/copilot-test-data"


def test_storage_cache_dir_overridden():
    cfg = get_settings()
    assert cfg.storage.cache_dir == "/tmp/copilot-test-cache"


def test_get_token_file_path_uses_data_dir():
    cfg = get_settings()
    expected = Path("/tmp/copilot-test-data") / cfg.storage.token_file
    assert cfg.storage.get_token_file_path() == expected


def test_proxy_copilot_api_base():
    cfg = get_settings()
    assert cfg.proxy.copilot_api_base.startswith("https://")


def test_proxy_request_timeout_positive():
    cfg = get_settings()
    assert cfg.proxy.request_timeout > 0


def test_security_token_expiry_positive():
    cfg = get_settings()
    assert cfg.security.token_expiry_hours > 0


def test_security_rate_limit_positive():
    cfg = get_settings()
    assert cfg.security.rate_limit_requests > 0


def test_xai_api_base_set():
    cfg = get_settings()
    assert cfg.xai.api_base.startswith("https://")


def test_logging_level_valid():
    import logging
    cfg = get_settings()
    assert hasattr(logging, cfg.logging_config.level), (
        f"Invalid log level: {cfg.logging_config.level!r}"
    )


def test_encrypt_tokens_false_in_tests():
    """Ensures the test override is active (avoids key-generation noise)."""
    cfg = get_settings()
    assert cfg.storage.encrypt_tokens is False


def test_cleanup_expired_tokens_false_in_tests():
    cfg = get_settings()
    assert cfg.storage.cleanup_expired_tokens is False

