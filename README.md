# Copilot API Proxy - Arch Linux Package

A complete, production-ready PKGBUILD package for GitHub Copilot API proxy with **uv** for ultrafast Python dependency management.

## [*] Package Overview

This package provides a FastAPI-based proxy that translates OpenAI-compatible API requests to GitHub Copilot, featuring:

- **[>>] uv integration** for blazing-fast Python dependency management
- **[PKG] Pre-built virtual environment** included in package for instant startup
- **Socket-activated systemd service** for efficient resource usage
- **[LOCK] Caddy reverse proxy integration** with automatic TLS
- **Security hardening** with dedicated user and permissions  
- **Web dashboard** for token management and monitoring

## [>>] Key Performance Features

- **Lightning-fast startup**: Pre-built virtual environment eliminates dependency installation time
- **uv package manager**: 10-100x faster than pip for dependency resolution and installation
- **Smart fallback**: Uses pre-built environment by default, falls back to runtime creation if needed
- **Minimal overhead**: Socket activation means zero resource usage when idle

## [PKG] Installation

```bash
# Build and install the package
makepkg -si

# Configure GitHub App credentials
sudo nano /etc/copilot-api-proxy/config.env

# Enable and start services
sudo systemctl enable --now copilot-api-proxy.socket

# If using Caddy (recommended)
sudo systemctl enable --now caddy
```

## [CFG] Configuration

### 1. GitHub App Setup

1. Create a GitHub App at: https://github.com/settings/apps/new
2. Set **Authorization callback URL** to: `https://localhost:8443/auth/callback`
3. Enable "Request user authorization (OAuth) during installation"
4. Copy Client ID and Secret to `/etc/copilot-api-proxy/config.env`:

```env
GITHUB_APP_CLIENT_ID=Iv1.your_client_id_here
GITHUB_APP_CLIENT_SECRET=your_client_secret_here
GITHUB_APP_REDIRECT_URI=https://localhost:8443/auth/callback
BASE_URL=https://localhost:8443
```

### 2. Service Configuration

The service automatically:
- **Uses pre-built virtual environment** from package for instant startup
- **Falls back to uv runtime creation** if needed (much faster than pip)
- Installs dependencies in seconds instead of minutes
- Runs on a Unix socket for performance and security

## [WWW] Usage

### Web Interface
- **Homepage**: https://localhost:8443
- **Dashboard**: https://localhost:8443/dashboard
- **Health Check**: https://localhost:8443/health

### API Usage

Compatible with any OpenAI API client:

```bash
# Get authentication token via web interface first
curl -X POST https://localhost:8443/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "model": "gpt-4", 
    "messages": [
      {"role": "user", "content": "Hello!"}
    ]
  }'
```

### Python Client Example

```python
import openai

client = openai.OpenAI(
    api_key="your-token-from-web-interface",
    base_url="https://localhost:8443/v1"
)

response = client.chat.completions.create(
    model="gpt-4",
    messages=[{"role": "user", "content": "Hello!"}]
)
print(response.choices[0].message.content)
```

## [SVC] Service Management

```bash
# Check service status
sudo systemctl status copilot-api-proxy

# View logs
sudo journalctl -u copilot-api-proxy -f

# Restart service
sudo systemctl restart copilot-api-proxy

# Check socket status
sudo systemctl status copilot-api-proxy.socket

# View all logs
sudo journalctl -u copilot-api-proxy.service -u copilot-api-proxy.socket -f
```

## [DIR] File Locations

```
/etc/copilot-api-proxy/config.env                    # Main configuration
/var/lib/copilot-api-proxy/tokens.json               # Token storage (encrypted)
/var/lib/copilot-api-proxy/.venv/                    # Runtime virtual environment (if used)
/usr/lib/copilot-api-proxy/.venv/                    # Pre-built virtual environment
/var/log/copilot-api-proxy/                          # Service logs
/usr/lib/copilot-api-proxy/                          # Application files
/run/copilot-api-proxy/copilot-proxy.sock            # Unix socket
/etc/caddy/conf.d/copilot-api-proxy                  # Caddy configuration
```

## [LOCK] Security Features

- **Dedicated system user**: `copilot-api-proxy` with minimal privileges
- **Unix domain sockets**: Internal communication only
- **Security hardening**: systemd protections enabled
- **TLS termination**: Handled by Caddy with proper headers
- **Token encryption**: Secure storage and validation
- **Process isolation**: No network access except required APIs

## [FIX] Troubleshooting

### Common Issues

**"Permission denied" errors**:
```bash
sudo chown -R copilot-api-proxy:copilot-api-proxy /var/lib/copilot-api-proxy
```

**"Socket not found"**:
```bash
sudo systemctl restart copilot-api-proxy.socket
sudo systemctl status copilot-api-proxy.socket
```

**"Dependencies missing"**:
```bash
# Force recreation of virtual environment with uv
sudo rm -rf /var/lib/copilot-api-proxy/.venv /usr/lib/copilot-api-proxy/.venv
sudo systemctl restart copilot-api-proxy
```

**"Authentication failed"**:
- Verify GitHub App credentials in config file
- Check callback URL matches exactly
- Ensure GitHub App is properly configured

### Debug Mode

```bash
# Run service manually for debugging
sudo -u copilot-api-proxy /usr/bin/copilot-api-proxy
```

## [NET] Architecture

```
Internet -> Caddy (TLS) -> Unix Socket -> FastAPI App -> GitHub Copilot API
                                      |
                                Token Storage + Web UI
```

## [PKG] Package Details

- **Dependencies**: `python`, `uv`, `systemd`
- **Optional Dependencies**: `caddy` (recommended), `nginx` (alternative)  
- **Architecture**: `any` (pure Python)
- **License**: MIT
- **Package Size**: ~13MB (includes pre-built virtual environment)
- **Backup Files**: `/etc/copilot-api-proxy/config.env`

## [DEV] Development

To modify the package:

1. Edit source files in the PKGBUILD directory
2. Rebuild: `makepkg -f`
3. Reinstall: `sudo pacman -U copilot-api-proxy-*.pkg.tar.zst`
4. Restart: `sudo systemctl restart copilot-api-proxy`

## [PERF] Performance Notes

- **Instant startup**: Pre-built virtual environment eliminates dependency installation time
- **Socket activation**: Service starts on-demand
- **uv speed**: 10-100x faster dependency resolution compared to pip
- **Unix sockets**: Lower latency than TCP
- **Caddy**: Efficient HTTP/2 and TLS handling
- **Memory usage**: ~50MB with all dependencies loaded
- **Package size**: ~13MB (includes complete Python environment)

## [>>] uv Integration Benefits

- **Build-time optimization**: Dependencies resolved and installed during package build
- **Faster updates**: uv's advanced caching and resolution algorithms
- **Reliable environments**: Consistent dependency versions across installations  
- **Smart fallbacks**: Runtime environment creation when needed
- **Minimal maintenance**: Pre-built environments reduce runtime complexity

This package provides a robust, secure, and ultra-fast GitHub Copilot API proxy suitable for personal and enterprise use.