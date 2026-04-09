# Makefile for OpenClaude / Claude Code Copilot Proxy - Direct TLS (no Caddy)
# Full install: `make` or `make install`
# Sophisticated uninstall: `make uninstall`

.PHONY: all certs trust clean install uninstall dev dev-run lint test test-api test-html

CERT_DIR=/var/lib/copilot-api-proxy/ssl
CERT_FILE=$(CERT_DIR)/server.crt
KEY_FILE=$(CERT_DIR)/server.key
DAYS=365
CN=localhost

SERVICE_NAME=copilot-api-proxy
INSTALL_PREFIX=/usr/lib/$(SERVICE_NAME)
CONFIG_DIR=/etc/$(SERVICE_NAME)
DATA_DIR=/var/lib/$(SERVICE_NAME)
LOG_DIR=/var/log/$(SERVICE_NAME)
SERVICE_FILE=/etc/systemd/system/$(SERVICE_NAME).service
WRAPPER=/usr/bin/$(SERVICE_NAME)

all: install

# ── Development environment ──────────────────────────────────────────────────
dev:
	@echo "🛠  Setting up development environment..."
	@uv venv .venv --python python3
	@uv pip install -r requirements.txt --python .venv/bin/python
	@uv pip install pytest pytest-asyncio pytest-cov ruff --python .venv/bin/python
	@if [ ! -f config.local.env ]; then cp config.env config.local.env && \
		sed -i 's/ENVIRONMENT=production/ENVIRONMENT=development/' config.local.env && \
		sed -i 's|LOGGING_CONFIG__FILE_PATH=.*|LOGGING_CONFIG__FILE_PATH=|' config.local.env && \
		sed -i 's|STORAGE__DATA_DIR=.*|STORAGE__DATA_DIR=./data|' config.local.env && \
		echo "📝 Created config.local.env — edit GITHUB__CLIENT_ID and GITHUB__CLIENT_SECRET"; fi
	@echo "✅ Dev environment ready. Activate with: source .venv/bin/activate"
	@echo "   Then run: make dev-run"

dev-run:
	@echo "▶  Starting dev server (hot-reload)..."
	@ENVIRONMENT=development \
		SERVER__MODE=development \
		SERVER__DEV_HOST=127.0.0.1 \
		SERVER__DEV_PORT=8000 \
		$$(grep -v '^#' config.local.env 2>/dev/null | xargs -d '\n') \
		.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000 --reload

lint:
	@.venv/bin/ruff check . --fix

test:
	@.venv/bin/pytest tests/ -v --cov=main --cov-report=term-missing 2>/dev/null || \
		echo "ℹ  No tests directory found. Create tests/ to get started."

test-api:
	@echo "🔌 Running Web-API tests only (marker: webapi)..."
	@.venv/bin/pytest tests/ -v -m webapi --cov=main --cov-report=term-missing

test-html:
	@echo "🌐 Running HTML/template tests only (marker: html)..."
	@.venv/bin/pytest tests/ -v -m html



certs:
	@echo "Creating self-signed TLS certificates..."
	@mkdir -p $(CERT_DIR)
	@openssl genrsa -out $(KEY_FILE) 2048
	@openssl req -new -x509 -key $(KEY_FILE) -out $(CERT_FILE) -days $(DAYS) \
		-subj "/C=DE/ST=NRW/L=Lennestadt/O=OpenClaudeProxy/CN=$(CN)" \
		-addext "subjectAltName=DNS:localhost,IP:127.0.0.1" \
		-addext "basicConstraints=critical,CA:TRUE,pathlen:0"
	@chmod 640 $(KEY_FILE)
	@chmod 644 $(CERT_FILE)
	@chown root:copilot-api-proxy $(KEY_FILE) 2>/dev/null || true
	@chown root:copilot-api-proxy $(CERT_FILE) 2>/dev/null || true
	@chmod 755 $(CERT_DIR)
	@test -f $(CERT_FILE) && echo "✅ Certificates created successfully" || (echo "❌ Failed to create certificates" && exit 1)

trust:
	@cp $(CERT_FILE) /etc/ca-certificates/trust-source/anchors/copilot-proxy.crt 2>/dev/null || \
		cp $(CERT_FILE) /usr/local/share/ca-certificates/copilot-proxy.crt 2>/dev/null || \
		cp $(CERT_FILE) /etc/pki/ca-trust/source/anchors/copilot-proxy.crt 2>/dev/null || true
	@update-ca-trust 2>/dev/null || update-ca-certificates 2>/dev/null || true
	@echo "✅ Certificate added to system trust store"

clean:
	rm -rf $(CERT_DIR)

install:
	@echo "🚀 Running full OpenClaude Copilot Proxy installation (Direct TLS, no Caddy)..."
	@if ! command -v openssl >/dev/null 2>&1; then \
		if command -v apt-get >/dev/null 2>&1; then sudo apt-get update && sudo apt-get install -y openssl; \
		elif command -v pacman >/dev/null 2>&1; then sudo pacman -S --noconfirm openssl; \
		elif command -v dnf >/dev/null 2>&1; then sudo dnf install -y openssl; \
		elif command -v yum >/dev/null 2>&1; then sudo yum install -y openssl; fi; \
	fi
	@if ! command -v uv >/dev/null 2>&1; then curl -LsSf https://astral.sh/uv/install.sh | sh; fi
	@getent group $(SERVICE_NAME) >/dev/null || groupadd -r $(SERVICE_NAME)
	@getent passwd $(SERVICE_NAME) >/dev/null || useradd -r -g $(SERVICE_NAME) -d $(DATA_DIR) -s /usr/bin/nologin $(SERVICE_NAME)
	@mkdir -p $(INSTALL_PREFIX) $(CONFIG_DIR) $(DATA_DIR) $(LOG_DIR) /run/$(SERVICE_NAME) $(CERT_DIR)
	@chown -R root:root $(INSTALL_PREFIX) $(CONFIG_DIR)
	@chown -R $(SERVICE_NAME):$(SERVICE_NAME) $(DATA_DIR) $(LOG_DIR) /run/$(SERVICE_NAME)
	@chmod 755 $(INSTALL_PREFIX) $(LOG_DIR) $(CONFIG_DIR)
	@chmod 750 $(DATA_DIR) $(CERT_DIR)
	@$(MAKE) certs
	@cp main.py config.py requirements.txt pyproject.toml copilot-proxy-wrapper $(INSTALL_PREFIX)/ 2>/dev/null || true
	@mkdir -p $(INSTALL_PREFIX)/templates
	@cp -r templates/* $(INSTALL_PREFIX)/templates/ 2>/dev/null || true
	@cp copilot-api-proxy.service $(SERVICE_FILE)
	@chown -R root:root $(INSTALL_PREFIX)
	@find $(INSTALL_PREFIX) -type f \( -name "*.py" -o -name "*.txt" -o -name "*.toml" \) -exec chmod 644 {} +
	@find $(INSTALL_PREFIX) -type d -exec chmod 755 {} +
	@chmod 755 $(INSTALL_PREFIX)/copilot-proxy-wrapper
	@mv $(INSTALL_PREFIX)/copilot-proxy-wrapper $(WRAPPER)
	@cd $(INSTALL_PREFIX) && uv venv .venv --python python3 --clear && uv pip install -r requirements.txt --python .venv/bin/python
	@chown -R $(SERVICE_NAME):$(SERVICE_NAME) $(INSTALL_PREFIX)/.venv
	@cp config.env $(CONFIG_DIR)/ 2>/dev/null || true
	@chown root:root $(CONFIG_DIR)/config.env
	@chmod 644 $(CONFIG_DIR)/config.env
	@$(MAKE) trust
	@systemctl daemon-reload
	@echo "✅ Full installation complete!"
	@echo "Run: sudo systemctl enable --now $(SERVICE_NAME)"

uninstall:
	@echo "⚠️  Sophisticated uninstall of OpenClaude Copilot Proxy"
	@echo "This will remove:"
	@echo "   • Systemd service"
	@echo "   • All application files in $(INSTALL_PREFIX)"
	@echo "   • Config in $(CONFIG_DIR)"
	@echo "   • Certificates in $(CERT_DIR)"
	@echo "   • User and group '$(SERVICE_NAME)'"
	@echo ""
	@read -p "Type 'YES' to confirm full uninstall (data in $(DATA_DIR) and $(LOG_DIR) will be preserved): " confirm; \
	if [ "$$confirm" != "YES" ]; then echo "Aborted."; exit 1; fi
	@echo "Stopping and disabling service..."
	@systemctl stop $(SERVICE_NAME) 2>/dev/null || true
	@systemctl disable $(SERVICE_NAME) 2>/dev/null || true
	@systemctl daemon-reload
	@echo "Removing files..."
	@rm -f $(SERVICE_FILE) $(WRAPPER)
	@rm -rf $(INSTALL_PREFIX) $(CONFIG_DIR) $(CERT_DIR)
	@echo "Removing user and group..."
	@userdel $(SERVICE_NAME) 2>/dev/null || true
	@groupdel $(SERVICE_NAME) 2>/dev/null || true
	@echo "✅ Sophisticated uninstall finished."
	@echo "Data preserved in: $(DATA_DIR) and $(LOG_DIR)"
	@echo "Run 'sudo make clean' if you also want to remove certificates."