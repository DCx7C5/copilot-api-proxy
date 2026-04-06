#!/usr/bin/env python3
"""
Configuration management for GitHub Copilot API Proxy + xAI Grok
Supports multiple deployment modes + multi-backend (Copilot + Grok)
"""

import os
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any, Literal
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ServerConfig(BaseModel):
    """Server configuration options"""
    mode: Literal["unix_socket", "tls_socket", "development"] = "unix_socket"

    # Unix socket configuration
    unix_socket_path: str = "/run/copilot-api-proxy/copilot-proxy.sock"
    unix_socket_user: str = "copilot-api-proxy"
    unix_socket_group: str = "caddy"
    unix_socket_mode: int = 0o660

    # TLS socket configuration
    host: str = "127.0.0.1"
    port: int = 8000
    ssl_certfile: Optional[str] = None
    ssl_keyfile: Optional[str] = None
    ssl_ca_certs: Optional[str] = None
    ssl_cert_reqs: Optional[str] = None

    # Development configuration
    dev_host: str = "127.0.0.1"
    dev_port: int = 8000
    dev_reload: bool = True

    @field_validator('mode')
    @classmethod
    def validate_mode(cls, v):
        if v not in ['unix_socket', 'tls_socket', 'development']:
            raise ValueError('Mode must be unix_socket, tls_socket, or development')
        return v

    @model_validator(mode='after')
    def validate_ssl_files(self):
        if self.mode == 'tls_socket':
            if not self.ssl_certfile:
                raise ValueError('ssl_certfile is required for TLS socket mode')
            if not self.ssl_keyfile:
                raise ValueError('ssl_keyfile is required for TLS socket mode')
            if self.ssl_certfile and not Path(self.ssl_certfile).exists():
                raise ValueError(f'SSL file {self.ssl_certfile} does not exist')
            if self.ssl_keyfile and not Path(self.ssl_keyfile).exists():
                raise ValueError(f'SSL file {self.ssl_keyfile} does not exist')
        return self


class SecurityConfig(BaseModel):
    """Security configuration"""
    secret_key: Optional[str] = None
    token_expiry_hours: int = 24
    max_tokens_per_user: int = 5
    rate_limit_requests: int = 100
    rate_limit_period: int = 60
    enable_cors: bool = False
    cors_origins: list = ["*"]

    # Request limits
    max_request_size: int = 10 * 1024 * 1024  # 10MB
    max_tokens_per_request: int = 4096
    request_timeout: int = 300  # 5 minutes


class GitHubConfig(BaseModel):
    """GitHub App configuration"""
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    redirect_uri: str = "https://localhost:8443/auth/callback"
    oauth_scopes: list = ["read:user"]

    @field_validator('client_id', 'client_secret', mode='before')
    @classmethod
    def validate_github_config(cls, v, info):
        if not v:
            logging.warning(f"GitHub {info.field_name} not configured - authentication will not work")
        return v


class XAIConfig(BaseModel):
    """xAI Grok configuration - used when model starts with 'grok-'"""
    api_base: str = "https://api.x.ai/v1"
    # No client_id/secret needed - uses direct Bearer token (gsk_...)


class LoggingConfig(BaseModel):
    """Logging configuration"""
    level: str = "INFO"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    file_path: Optional[str] = "/var/log/copilot-api-proxy/app.log"
    max_file_size: int = 10 * 1024 * 1024  # 10MB
    backup_count: int = 5

    # Structured logging
    enable_json_logging: bool = False
    log_requests: bool = True
    log_responses: bool = False

    @field_validator('level')
    @classmethod
    def validate_log_level(cls, v):
        if v.upper() not in ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']:
            raise ValueError('Invalid log level')
        return v.upper()


class StorageConfig(BaseModel):
    """Storage configuration"""
    data_dir: str = "/var/lib/copilot-api-proxy"
    token_file: str = "tokens.json"
    cache_dir: str = "/var/cache/copilot-api-proxy"

    # Token storage encryption
    encrypt_tokens: bool = True
    token_encryption_key: Optional[str] = None

    # Cleanup settings
    cleanup_expired_tokens: bool = True
    cleanup_interval_hours: int = 24

    def get_token_file_path(self) -> Path:
        return Path(self.data_dir) / self.token_file


class ProxyConfig(BaseModel):
    """Copilot API proxy configuration"""
    copilot_api_base: str = "https://api.githubcopilot.com"
    user_agent: str = "GitHubCopilotChat/1.0.0"
    request_timeout: int = 60
    max_retries: int = 3
    retry_delay: float = 1.0

    # Connection pooling
    max_connections: int = 100
    max_keepalive_connections: int = 20
    keepalive_expiry: int = 5


class Settings(BaseSettings):
    """Main application settings"""

    # Basic settings
    app_name: str = "OpenClaude Copilot Proxy + Grok"
    version: str = "2.0.1"
    environment: str = "production"
    debug: bool = False

    # Component configurations
    server: ServerConfig = Field(default_factory=ServerConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    github: GitHubConfig = Field(default_factory=GitHubConfig)
    xai: XAIConfig = Field(default_factory=XAIConfig)          # <-- NEW: Grok support
    logging_config: LoggingConfig = Field(default_factory=LoggingConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    proxy: ProxyConfig = Field(default_factory=ProxyConfig)

    # Base URL for the service
    base_url: str = "https://localhost:8443"

    model_config = SettingsConfigDict(
        env_file="/etc/copilot-api-proxy/config.env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )


class ConfigManager:
    """Configuration manager with validation and environment-specific loading"""

    def __init__(self, config_file: Optional[str] = None):
        self.config_file = config_file
        self._settings = None

    def load_settings(self) -> Settings:
        """Load and validate settings"""
        if self._settings is None:
            if self.config_file:
                os.environ['CONFIG_FILE'] = self.config_file

            self._settings = Settings()
            self._post_process_settings()
            self._validate_settings()

        return self._settings

    def _post_process_settings(self):
        """Post-process settings after loading"""
        if not self._settings.security.secret_key:
            import secrets
            self._settings.security.secret_key = secrets.token_urlsafe(32)

        self._ensure_directories()

        if not self._settings.github.redirect_uri.startswith('http'):
            base_url = self._settings.base_url.rstrip('/')
            self._settings.github.redirect_uri = f"{base_url}/auth/callback"

    def _ensure_directories(self):
        """Ensure required directories exist"""
        dirs_to_create = [
            self._settings.storage.data_dir,
            self._settings.storage.cache_dir,
        ]

        if self._settings.logging_config.file_path:
            log_dir = Path(self._settings.logging_config.file_path).parent
            dirs_to_create.append(str(log_dir))

        for dir_path in dirs_to_create:
            try:
                Path(dir_path).mkdir(parents=True, exist_ok=True)
            except PermissionError:
                logging.warning(f"Cannot create directory {dir_path} - permission denied")

    def _validate_settings(self):
        """Validate settings for consistency"""
        settings = self._settings

        if settings.server.mode == "tls_socket":
            if not settings.server.ssl_certfile or not settings.server.ssl_keyfile:
                raise ValueError("TLS socket mode requires ssl_certfile and ssl_keyfile")

        elif settings.server.mode == "unix_socket":
            socket_dir = Path(settings.server.unix_socket_path).parent
            socket_dir.mkdir(parents=True, exist_ok=True)

        if settings.environment == "production":
            if not settings.github.client_id or not settings.github.client_secret:
                logging.warning("GitHub App not configured - authentication will not work in production")

    def get_uvicorn_config(self) -> Dict[str, Any]:
        """Get uvicorn server configuration"""
        settings = self._settings.server

        base_config = {
            "app": "main:app",
            "log_level": self._settings.logging_config.level.lower(),
            "access_log": self._settings.logging_config.log_requests,
        }

        if settings.mode == "unix_socket":
            return {**base_config, "uds": settings.unix_socket_path}
        elif settings.mode == "tls_socket":
            return {
                **base_config,
                "host": settings.host,
                "port": settings.port,
                "ssl_keyfile": settings.ssl_keyfile,
                "ssl_certfile": settings.ssl_certfile,
                "ssl_ca_certs": settings.ssl_ca_certs,
                "ssl_cert_reqs": settings.ssl_cert_reqs,
            }
        else:  # development
            return {
                **base_config,
                "host": settings.dev_host,
                "port": settings.dev_port,
                "reload": settings.dev_reload,
            }

    def export_config(self, file_path: str, format: str = "env"):
        """Export configuration to file"""
        settings = self._settings

        if format == "env":
            self._export_env_file(file_path, settings)
        elif format == "json":
            self._export_json_file(file_path, settings)
        else:
            raise ValueError("Format must be 'env' or 'json'")

    def _export_env_file(self, file_path: str, settings: Settings):
        """Export configuration as environment file"""
        lines = [
            "# OpenClaude Copilot Proxy + Grok Configuration",
            "# Generated automatically - edit with care",
            "",
            f"APP_NAME={settings.app_name}",
            f"VERSION={settings.version}",
            f"ENVIRONMENT={settings.environment}",
            f"DEBUG={settings.debug}",
            f"BASE_URL={settings.base_url}",
            "",
            "# Server Configuration",
            f"SERVER__MODE={settings.server.mode}",
            f"SERVER__UNIX_SOCKET_PATH={settings.server.unix_socket_path}",
            f"SERVER__HOST={settings.server.host}",
            f"SERVER__PORT={settings.server.port}",
            "",
            "# GitHub Configuration (for Copilot/Claude)",
            f"GITHUB__CLIENT_ID={settings.github.client_id or ''}",
            f"GITHUB__CLIENT_SECRET={settings.github.client_secret or ''}",
            f"GITHUB__REDIRECT_URI={settings.github.redirect_uri}",
            "",
            "# xAI Grok Configuration",
            f"XAI__API_BASE={settings.xai.api_base}",
            "",
            "# Security Configuration",
            f"SECURITY__TOKEN_EXPIRY_HOURS={settings.security.token_expiry_hours}",
            f"SECURITY__MAX_TOKENS_PER_USER={settings.security.max_tokens_per_user}",
            "",
            "# Storage Configuration",
            f"STORAGE__DATA_DIR={settings.storage.data_dir}",
            f"STORAGE__TOKEN_FILE={settings.storage.token_file}",
            f"STORAGE__ENCRYPT_TOKENS={settings.storage.encrypt_tokens}",
            "",
            "# Proxy Configuration",
            f"PROXY__COPILOT_API_BASE={settings.proxy.copilot_api_base}",
            f"PROXY__REQUEST_TIMEOUT={settings.proxy.request_timeout}",
            "",
            "# Logging Configuration",
            f"LOGGING_CONFIG__LEVEL={settings.logging_config.level}",
            f"LOGGING_CONFIG__FILE_PATH={settings.logging_config.file_path or ''}",
        ]

        with open(file_path, 'w') as f:
            f.write('\n'.join(lines))

    def _export_json_file(self, file_path: str, settings: Settings):
        """Export configuration as JSON file"""
        config_dict = settings.model_dump()

        with open(file_path, 'w') as f:
            json.dump(config_dict, f, indent=2)


# Global configuration instance
config_manager = ConfigManager()

def get_settings() -> Settings:
    """Get application settings (singleton pattern)"""
    return config_manager.load_settings()