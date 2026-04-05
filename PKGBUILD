# Maintainer: Your Name <your.email@example.com>
pkgname=copilot-api-proxy
pkgver=2.0.0
pkgrel=1
pkgdesc="Production-ready GitHub Copilot API proxy with OpenAI-compatible endpoints"
arch=('any')
url="https://github.com/yourusername/copilot-api-proxy"
license=('MIT')
depends=('python>=3.9' 'uv' 'systemd')
optdepends=(
    'caddy: recommended reverse proxy with automatic TLS'
    'nginx: alternative reverse proxy'
    'certbot: for Let's Encrypt certificates'
)
makedepends=('python-build' 'python-installer' 'python-wheel')
backup=(
    'etc/copilot-api-proxy/config.env'
)
install=copilot-api-proxy.install
source=(
    'main.py'
    'config.py'
    'config.env'
    'copilot-api-proxy-wrapper'
    'copilot-api-proxy.service'
    'copilot-api-proxy.socket'
    'copilot-api-proxy.install'
    'Caddyfile'
    'requirements.txt'
    'templates/base.html'
    'templates/index.html'
    'templates/dashboard.html'
)
sha256sums=(
    'SKIP'
    'SKIP'
    'SKIP'
    'SKIP'
    'SKIP'
    'SKIP'
    'SKIP'
    'SKIP'
    'SKIP'
    'SKIP'
    'SKIP'
    'SKIP'
)

prepare() {
    cd "$srcdir"

    # Create directory structure
    mkdir -p build/{lib,bin,templates,conf.d}

    # Copy application files
    cp main.py build/lib/
    cp config.py build/lib/
    cp requirements.txt build/lib/
    cp -r templates/* build/templates/

    # Copy wrapper script
    cp copilot-api-proxy-wrapper build/bin/copilot-api-proxy

    # Copy configuration files
    cp config.env build/
    cp Caddyfile build/conf.d/copilot-api-proxy
}

build() {
    cd "$srcdir/build"

    # Create virtual environment with uv for faster dependency resolution
    msg2 "Creating optimized virtual environment with uv..."

    # Create virtual environment
    uv venv .venv --python python3

    # Install dependencies with uv (much faster than pip)
    uv pip install --python .venv/bin/python -r requirements.txt

    # Pre-compile Python bytecode for faster startup
    msg2 "Pre-compiling Python bytecode..."
    .venv/bin/python -m compileall lib/

    # Optimize virtual environment (remove unnecessary files)
    msg2 "Optimizing virtual environment..."
    find .venv -name "*.pyc" -path "*/test/*" -delete
    find .venv -name "__pycache__" -path "*/test/*" -type d -exec rm -rf {} + 2>/dev/null || true
    find .venv -name "*.dist-info" -type d -exec rm -rf {}/WHEEL {} + 2>/dev/null || true

    # Create version info file
    echo "{\"version\":\"$pkgver\",\"build_date\":\"$(date -Iseconds)\",\"build_method\":\"makepkg\"}" > lib/version.json
}

package() {
    cd "$srcdir/build"

    # Create directory structure
    install -dm755 "$pkgdir/usr/lib/$pkgname"
    install -dm755 "$pkgdir/usr/bin"
    install -dm755 "$pkgdir/etc/$pkgname"
    install -dm755 "$pkgdir/etc/caddy/conf.d"
    install -dm755 "$pkgdir/usr/lib/systemd/system"

    # Install application files
    cp -r lib/* "$pkgdir/usr/lib/$pkgname/"
    cp -r .venv "$pkgdir/usr/lib/$pkgname/"

    # Install templates
    install -dm755 "$pkgdir/usr/lib/$pkgname/templates"
    cp -r templates/* "$pkgdir/usr/lib/$pkgname/templates/"

    # Install wrapper script
    install -Dm755 bin/copilot-api-proxy "$pkgdir/usr/bin/copilot-api-proxy"

    # Install configuration files
    install -Dm644 "$srcdir/config.env" "$pkgdir/etc/$pkgname/config.env"
    install -Dm644 "$srcdir/Caddyfile" "$pkgdir/etc/caddy/conf.d/copilot-api-proxy"

    # Install systemd service files
    install -Dm644 "$srcdir/copilot-api-proxy.service" "$pkgdir/usr/lib/systemd/system/"
    install -Dm644 "$srcdir/copilot-api-proxy.socket" "$pkgdir/usr/lib/systemd/system/"

    # Create systemd override directory for easy customization
    install -dm755 "$pkgdir/etc/systemd/system/copilot-api-proxy.service.d"

    # Install documentation
    install -dm755 "$pkgdir/usr/share/doc/$pkgname"

    # Create example configurations
    cat > "$pkgdir/usr/share/doc/$pkgname/example-configs.md" << 'EOF'
# Example Configurations

## Unix Socket + Caddy (Recommended)
```env
SERVER__MODE=unix_socket
SERVER__UNIX_SOCKET_PATH=/run/copilot-api-proxy/copilot-proxy.sock
BASE_URL=https://localhost:8443
```

## Direct TLS Socket
```env
SERVER__MODE=tls_socket
SERVER__HOST=0.0.0.0
SERVER__PORT=8443
SERVER__SSL_CERTFILE=/etc/ssl/certs/copilot-proxy.crt
SERVER__SSL_KEYFILE=/etc/ssl/private/copilot-proxy.key
BASE_URL=https://your-domain.com:8443
```

## Custom Port Configuration
```env
SERVER__MODE=tls_socket
SERVER__HOST=127.0.0.1
SERVER__PORT=9443
SERVER__SSL_CERTFILE=/path/to/cert.pem
SERVER__SSL_KEYFILE=/path/to/key.pem
BASE_URL=https://localhost:9443
```
EOF

    # Create performance tuning guide
    cat > "$pkgdir/usr/share/doc/$pkgname/performance.md" << 'EOF'
# Performance Tuning

## Virtual Environment
- Pre-built virtual environment included for instant startup
- Runtime fallback with uv for ultra-fast dependency installation
- Bytecode pre-compilation reduces startup time

## Systemd Optimizations
- Socket activation for zero idle resource usage
- Security hardening enabled by default
- Proper resource limits and isolation

## Monitoring
- Built-in health check endpoint: /health
- Structured logging with JSON support
- Rate limiting with configurable thresholds
EOF
}

# Post-install function is handled by the .install script