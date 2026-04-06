# Copilot API Proxy v2.0 - Production Ready

A **production-grade** FastAPI-based proxy that provides OpenAI-compatible API endpoints for GitHub Copilot with enterprise-level security, monitoring, and deployment options.

## [>>] What's New in v2.0

- **[CFG] Flexible Configuration**: Support for Unix sockets, TLS sockets, and development modes
- **[LOCK] Enhanced Security**: Comprehensive security hardening with systemd protections
- **[>>] Ultra-Fast Setup**: Pre-built virtual environments with `uv` for instant deployment
- **[PERF] Production Monitoring**: Health checks, structured logging, and rate limiting
- **[<>] Multiple Deployment Options**: Choose your preferred architecture
- **[AUDIT] Security Auditing**: Built-in security validation tools

## [START] Quick Start

### Installation Methods

#### Option 1: Automated Installation (Recommended)
```bash
# Clone the repository
git clone https://github.com/yourusername/copilot-api-proxy.git
cd copilot-api-proxy

# Install with automatic setup
sudo ./install.sh

# Or install with SSL certificates
sudo ./install.sh install-with-certs
```

#### Option 2: Arch Linux Package
```bash
# Build and install the package
makepkg -si

# Configure and start
sudo systemctl enable --now copilot-api-proxy.socket
```

### Configuration

Edit `/etc/copilot-api-proxy/config.env`:

```env
# Choose your deployment mode
SERVER__MODE=unix_socket  # or tls_socket, development

# GitHub App credentials
GITHUB__CLIENT_ID=Iv1.your_client_id_here
GITHUB__CLIENT_SECRET=your_client_secret_here

# Security settings
STORAGE__ENCRYPT_TOKENS=true
SECURITY__RATE_LIMIT_REQUESTS=100
```

### GitHub App Setup

1. Create a GitHub App at: https://github.com/settings/apps/new
2. Set **Authorization callback URL** to: `https://localhost:8443/auth/callback`
3. Enable "Request user authorization (OAuth) during installation"
4. Copy credentials to configuration file

### Start Services

```bash
# Start the proxy service
sudo systemctl enable --now copilot-api-proxy.socket

# Start Caddy (if using Unix socket mode)
sudo systemctl enable --now caddy

# Check status
sudo systemctl status copilot-api-proxy
```

## [CFG] Deployment Modes

### Mode 1: Unix Socket + Caddy (Recommended)

**Best for**: Production deployments with reverse proxy

```env
SERVER__MODE=unix_socket
SERVER__UNIX_SOCKET_PATH=/run/copilot-api-proxy/copilot-proxy.sock
BASE_URL=https://localhost:8443
```

**Architecture:**
```
Internet -> Caddy (TLS) -> Unix Socket -> FastAPI App -> GitHub Copilot API
```

**Advantages:**
- [+] Maximum security (no network exposure)
- [+] Automatic TLS management
- [+] Rate limiting and caching
- [+] Zero-downtime deployments
- [+] Advanced HTTP features

### Mode 2: Direct TLS Socket

**Best for**: Simple deployments without reverse proxy

```env
SERVER__MODE=tls_socket
SERVER__HOST=0.0.0.0
SERVER__PORT=8443
SERVER__SSL_CERTFILE=/etc/ssl/certs/copilot-proxy.crt
SERVER__SSL_KEYFILE=/etc/ssl/private/copilot-proxy.key
BASE_URL=https://your-domain.com:8443
```

**Architecture:**
```
Internet -> FastAPI App (TLS) -> GitHub Copilot API
```

**Advantages:**
- [+] Simple setup
- [+] Direct control over TLS
- [+] Custom port configuration
- [+] No additional dependencies

### Mode 3: Development Mode

**Best for**: Local development and testing

```env
SERVER__MODE=development
SERVER__DEV_HOST=127.0.0.1
SERVER__DEV_PORT=8000
```

**Advantages:**
- [+] Hot reloading
- [+] Debug information
- [+] No TLS required
- [+] Easy testing

## [LOCK] Security Features

### System-Level Security
- **Dedicated user account** with minimal privileges
- **systemd security hardening** with 30+ protection features
- **File permission controls** with proper ownership
- **Resource limits** to prevent resource exhaustion
- **Process isolation** with private tmp and devices

### Application Security
- **Token encryption** with configurable keys
- **Rate limiting** with customizable thresholds
- **Request validation** and size limits
- **Secure headers** (HSTS, CSP, etc.)
- **OAuth2 authentication** via GitHub
- **Session management** with expiration

### Network Security
- **Unix domain sockets** for internal communication
- **TLS termination** with strong cipher suites
- **CORS configuration** for cross-origin requests
- **Firewall integration** with UFW/firewalld
- **IP filtering** and connection limits

### Audit and Compliance
```bash
# Run security audit
sudo ./security-audit.sh

# Check file permissions
sudo find /etc/copilot-api-proxy -ls
sudo find /var/lib/copilot-api-proxy -ls

# Review systemd security
sudo systemd-analyze security copilot-api-proxy
```

## [PERF] Monitoring and Operations

### Health Monitoring
```bash
# Health check endpoint
curl https://localhost:8443/health

# Service status
sudo systemctl status copilot-api-proxy

# Real-time logs
sudo journalctl -u copilot-api-proxy -f
```

### Web Dashboard
- **Service Overview**: https://localhost:8443
- **Dashboard**: https://localhost:8443/dashboard
- **API Documentation**: https://localhost:8443/docs
- **Health Status**: https://localhost:8443/health

### Structured Logging
```json
{
  "ts": "2024-01-15T10:30:00.000Z",
  "level": "INFO",
  "msg": "Request completed",
  "user": "octocat",
  "status": 200,
  "duration": 1250,
  "model": "gpt-4"
}
```

### Maintenance Scripts
```bash
# Cleanup old logs and cache
sudo /usr/local/bin/copilot-api-proxy-cleanup

# Update dependencies
sudo systemctl stop copilot-api-proxy
cd /usr/lib/copilot-api-proxy
sudo uv pip install --upgrade -r requirements.txt
sudo systemctl start copilot-api-proxy
```

## [API] API Usage

### Authentication
```bash
# 1. Get token via web interface
curl https://localhost:8443/login

# 2. Follow OAuth flow to get API token
```

### OpenAI-Compatible API
```python
import openai

client = openai.OpenAI(
    api_key="your-token-from-authentication",
    base_url="https://localhost:8443/v1"
)

response = client.chat.completions.create(
    model="gpt-4",
    messages=[
        {"role": "user", "content": "Write a Python function for sorting"}
    ]
)

print(response.choices[0].message.content)
```

### cURL Examples
```bash
# Chat completion
curl -X POST https://localhost:8443/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "model": "gpt-4",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'

# List models
curl https://localhost:8443/v1/models \
  -H "Authorization: Bearer YOUR_TOKEN"
```

## [CFG] Advanced Configuration

### Environment Variables Reference

#### Server Configuration
```env
SERVER__MODE=unix_socket|tls_socket|development
SERVER__UNIX_SOCKET_PATH=/run/copilot-api-proxy/copilot-proxy.sock
SERVER__HOST=127.0.0.1
SERVER__PORT=8000
SERVER__SSL_CERTFILE=/path/to/cert.pem
SERVER__SSL_KEYFILE=/path/to/key.pem
```

#### Security Settings
```env
SECURITY__TOKEN_EXPIRY_HOURS=24
SECURITY__MAX_TOKENS_PER_USER=5
SECURITY__RATE_LIMIT_REQUESTS=100
SECURITY__RATE_LIMIT_PERIOD=60
SECURITY__MAX_REQUEST_SIZE=10485760
SECURITY__ENCRYPT_TOKENS=true
```

#### Logging Configuration
```env
LOGGING_CONFIG__LEVEL=INFO
LOGGING_CONFIG__FILE_PATH=/var/log/copilot-api-proxy/app.log
LOGGING_CONFIG__ENABLE_JSON_LOGGING=false
LOGGING_CONFIG__LOG_REQUESTS=true
```

#### Proxy Settings
```env
PROXY__COPILOT_API_BASE=https://api.githubcopilot.com
PROXY__REQUEST_TIMEOUT=60
PROXY__MAX_RETRIES=3
PROXY__MAX_CONNECTIONS=100
```

### Caddy Configuration
The included Caddyfile supports:
- **Environment variable configuration**
- **Rate limiting** with multiple zones
- **CORS handling** for API requests
- **Health check bypass** for monitoring
- **Structured JSON logging**
- **Error handling** with JSON responses
- **Security headers** and CSP policies

### Custom SSL Certificates
```bash
# Generate self-signed certificates
sudo ./install.sh install-with-certs

# Or use Let's Encrypt with Caddy
sudo caddy run --config /etc/caddy/conf.d/copilot-api-proxy
```

## [<>] Service Management

### systemctl Commands
```bash
# Service control
sudo systemctl start copilot-api-proxy
sudo systemctl stop copilot-api-proxy
sudo systemctl restart copilot-api-proxy
sudo systemctl status copilot-api-proxy

# Socket control
sudo systemctl start copilot-api-proxy.socket
sudo systemctl stop copilot-api-proxy.socket
sudo systemctl status copilot-api-proxy.socket

# Enable/disable
sudo systemctl enable copilot-api-proxy.socket
sudo systemctl disable copilot-api-proxy.socket
```

### Log Management
```bash
# View logs
sudo journalctl -u copilot-api-proxy -f

# Application logs
sudo tail -f /var/log/copilot-api-proxy/app.log

# Caddy logs
sudo tail -f /var/log/copilot-api-proxy/caddy-access.log

# Rotate logs manually
sudo logrotate /etc/logrotate.d/copilot-api-proxy
```

### Configuration Updates
```bash
# Edit configuration
sudo nano /etc/copilot-api-proxy/config.env

# Reload service
sudo systemctl reload-or-restart copilot-api-proxy

# Validate configuration
sudo /usr/bin/copilot-api-proxy --check-config
```

## [!] Troubleshooting

### Common Issues

#### Permission Errors
```bash
# Fix file permissions
sudo chown -R copilot-api-proxy:copilot-api-proxy /var/lib/copilot-api-proxy
sudo chmod 750 /var/lib/copilot-api-proxy
sudo chmod 600 /var/lib/copilot-api-proxy/tokens.json
```

#### Socket Issues
```bash
# Check socket status
sudo systemctl status copilot-api-proxy.socket
sudo ls -la /run/copilot-api-proxy/

# Restart socket
sudo systemctl restart copilot-api-proxy.socket
```

#### Dependencies Missing
```bash
# Recreate virtual environment
sudo rm -rf /usr/lib/copilot-api-proxy/.venv
sudo systemctl restart copilot-api-proxy
# Service will auto-create with uv
```

#### Authentication Issues
```bash
# Check GitHub App configuration
sudo grep GITHUB /etc/copilot-api-proxy/config.env

# Test OAuth flow
curl https://localhost:8443/login

# Check token storage
sudo ls -la /var/lib/copilot-api-proxy/tokens.json
```

### Debug Mode
```bash
# Enable debug logging
sudo sed -i 's/LOGGING_CONFIG__LEVEL=INFO/LOGGING_CONFIG__LEVEL=DEBUG/' /etc/copilot-api-proxy/config.env
sudo systemctl restart copilot-api-proxy

# Run service manually for debugging
sudo -u copilot-api-proxy /usr/bin/copilot-api-proxy
```

### Performance Tuning
```bash
# Check resource usage
sudo systemctl show copilot-api-proxy --property=MemoryCurrent
sudo systemctl show copilot-api-proxy --property=TasksCurrent

# Adjust limits in service file
sudo systemctl edit copilot-api-proxy
# Add: [Service]
#      MemoryMax=2G
#      TasksMax=512
```

## [PKG] Package Information

### Arch Linux Package
- **Package Name**: `copilot-api-proxy`
- **Version**: `2.0.0`
- **Architecture**: `any` (pure Python)
- **Dependencies**: `python>=3.9`, `uv`, `systemd`
- **Optional**: `caddy` (recommended), `nginx` (alternative)
- **Size**: ~13MB (includes pre-built virtual environment)

### File Locations
```
/usr/lib/copilot-api-proxy/           # Application files
├── main.py                           # Main application
├── config.py                         # Configuration management
├── requirements.txt                  # Python dependencies
├── .venv/                           # Pre-built virtual environment
└── templates/                        # HTML templates

/etc/copilot-api-proxy/               # Configuration
├── config.env                        # Main configuration
└── local.env                         # Local overrides (optional)

/var/lib/copilot-api-proxy/           # Data storage
├── tokens.json                       # Encrypted token storage
└── .venv/                           # Runtime virtual environment (fallback)

/var/log/copilot-api-proxy/           # Logs
├── app.log                          # Application logs
└── caddy-access.log                 # Caddy access logs

/usr/bin/                             # Executables
└── copilot-api-proxy                # Service wrapper script
```

### Performance Metrics
- **Cold start time**: <2 seconds (pre-built environment)
- **Memory usage**: ~50MB baseline, ~200MB under load
- **Request latency**: <100ms proxy overhead
- **Dependencies**: Resolved in <5 seconds with uv
- **Package build time**: <30 seconds

## [DEV] Contributing

### Development Setup
```bash
# Clone repository
git clone https://github.com/yourusername/copilot-api-proxy.git
cd copilot-api-proxy

# Set up development environment
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run in development mode
export SERVER__MODE=development
python main.py
```

### Testing
```bash
# Run security audit
./security-audit.sh

# Test API endpoints
curl http://localhost:8000/health

# Validate configuration
python -c "from config import get_settings; print(get_settings())"
```

### Building Package
```bash
# Build Arch Linux package
makepkg -f

# Install locally
sudo pacman -U copilot-api-proxy-*.pkg.tar.zst

# Test installation
sudo ./install.sh
```

## [LAW] License

MIT License - see [LICENSE](LICENSE) file for details.

## [LINK] Links

- **GitHub Repository**: https://github.com/yourusername/copilot-api-proxy
- **GitHub Copilot**: https://github.com/features/copilot
- **FastAPI Documentation**: https://fastapi.tiangolo.com/
- **Caddy Documentation**: https://caddyserver.com/docs/
- **uv Package Manager**: https://github.com/astral-sh/uv

---

**Made with <3 for the development community**

*[*] Star this repository if you find it useful!*