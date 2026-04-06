#!/bin/bash
# OpenClaude Copilot Proxy Installer - Direct TLS only (no Caddy)
set -euo pipefail
RED='\033[0;31m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; NC='\033[0m'
log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
SERVICE_NAME="copilot-api-proxy"
INSTALL_PREFIX="/usr/lib/${SERVICE_NAME}"
CONFIG_DIR="/etc/${SERVICE_NAME}"
DATA_DIR="/var/lib/${SERVICE_NAME}"
LOG_DIR="/var/log/${SERVICE_NAME}"
check_root() { [[ $EUID -eq 0 ]] || { echo -e "${RED}[ERROR]${NC} Run with sudo"; exit 1; }; }
create_user() { log_info "Creating service user..."; getent group ${SERVICE_NAME} >/dev/null || groupadd -r ${SERVICE_NAME}; getent passwd ${SERVICE_NAME} >/dev/null || useradd -r -g ${SERVICE_NAME} -d ${DATA_DIR} -s /usr/bin/nologin ${SERVICE_NAME}; }
setup_directories() { log_info "Setting up directories..."; mkdir -p ${INSTALL_PREFIX} ${CONFIG_DIR} ${DATA_DIR} ${LOG_DIR} /run/${SERVICE_NAME}; chown -R root:root ${INSTALL_PREFIX} ${CONFIG_DIR}; chown ${SERVICE_NAME}:${SERVICE_NAME} ${DATA_DIR} ${LOG_DIR} /run/${SERVICE_NAME}; chmod 755 ${INSTALL_PREFIX} ${LOG_DIR}; chmod 750 ${DATA_DIR}; }
install_application() { log_info "Copying files..."; cp main.py config.py requirements.txt pyproject.toml copilot-proxy-wrapper Makefile "${INSTALL_PREFIX}/" 2>/dev/null || true; mkdir -p "${INSTALL_PREFIX}/templates"; cp -r templates/* "${INSTALL_PREFIX}/templates/" 2>/dev/null || true; cp copilot-api-proxy.service /etc/systemd/system/; chmod 755 "${INSTALL_PREFIX}/copilot-proxy-wrapper"; mv "${INSTALL_PREFIX}/copilot-proxy-wrapper" /usr/bin/${SERVICE_NAME}; }
setup_virtual_environment() { log_info "Setting up venv with uv..."; cd "${INSTALL_PREFIX}"; uv venv .venv --python python3 --clear; uv pip install -r requirements.txt --python .venv/bin/python; }
install_systemd() { log_info "Installing systemd service (direct TLS)..."; systemctl daemon-reload; }
install_config() { log_info "Installing config..."; cp config.env "${CONFIG_DIR}/" 2>/dev/null || true; chown root:${SERVICE_NAME} "${CONFIG_DIR}/config.env"; chmod 640 "${CONFIG_DIR}/config.env"; }
setup_certs() { log_info "Certificates via Makefile..."; cd "${INSTALL_PREFIX}"; make certs trust || true; }
main() { check_root; create_user; setup_directories; install_application; setup_virtual_environment; install_systemd; install_config; setup_certs; log_success "OpenClaude Proxy installed!"; echo "Run: sudo systemctl enable --now ${SERVICE_NAME}"; }
main "$@"
