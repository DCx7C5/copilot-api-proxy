#!/bin/bash
# GitHub Copilot API Proxy - Security Audit Script
# Version 2.0 - Production Security Validation

set -euo pipefail

# ANSI color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Configuration
SERVICE_NAME="copilot-api-proxy"
CONFIG_DIR="/etc/${SERVICE_NAME}"
DATA_DIR="/var/lib/${SERVICE_NAME}"
LOG_DIR="/var/log/${SERVICE_NAME}"
INSTALL_PREFIX="/usr/lib/${SERVICE_NAME}"

# Security check results
SECURITY_ISSUES=()
SECURITY_WARNINGS=()
SECURITY_PASSED=()

# Functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[PASS]${NC} $1"
    SECURITY_PASSED+=("$1")
}

log_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
    SECURITY_WARNINGS+=("$1")
}

log_error() {
    echo -e "${RED}[FAIL]${NC} $1"
    SECURITY_ISSUES+=("$1")
}

check_file_permissions() {
    log_info "Checking file permissions..."
    local perms owner token_file
    # Check service files
    if [[ -f "/etc/systemd/system/${SERVICE_NAME}.service" ]]; then
        local perms
        perms=$(stat -c "%a" "/etc/systemd/system/${SERVICE_NAME}.service")
        if [[ "$perms" == "644" ]]; then
            log_success "Service file permissions correct (644)"
        else
            log_error "Service file permissions incorrect: $perms (should be 644)"
        fi
    fi

    # Check config file permissions
    if [[ -f "${CONFIG_DIR}/config.env" ]]; then
        perms=$(stat -c "%a" "${CONFIG_DIR}/config.env")
        owner=$(stat -c "%U:%G" "${CONFIG_DIR}/config.env")
        if [[ "$perms" == "640" ]] && [[ "$owner" == "root:${SERVICE_NAME}" ]]; then
            log_success "Config file permissions and ownership correct"
        else
            log_error "Config file permissions/ownership incorrect: $perms $owner"
        fi
    fi

    # Check data directory permissions
    if [[ -d "$DATA_DIR" ]]; then
        # shellcheck disable=SC2155
        perms=$(stat -c "%a" "$DATA_DIR")
        owner=$(stat -c "%U:%G" "$DATA_DIR")
        if [[ "$perms" == "750" ]] && [[ "$owner" == "${SERVICE_NAME}:${SERVICE_NAME}" ]]; then
            log_success "Data directory permissions correct"
        else
            log_error "Data directory permissions incorrect: $perms $owner"
        fi
    fi

    # Check token file permissions
    token_file="${DATA_DIR}/tokens.json"
    if [[ -f "$token_file" ]]; then
        perms=$(stat -c "%a" "$token_file")
        if [[ "$perms" == "600" ]]; then
            log_success "Token file permissions correct (600)"
        else
            log_error "Token file permissions incorrect: $perms (should be 600)"
        fi
    fi
}

check_user_security() {
    local groups shell home
    log_info "Checking user and group security..."

    # Check if service user exists and is properly configured
    if id "$SERVICE_NAME" &>/dev/null; then
        shell=$(getent passwd "$SERVICE_NAME" | cut -d: -f7)
        home=$(getent passwd "$SERVICE_NAME" | cut -d: -f6)

        if [[ "$shell" == "/usr/bin/nologin" || "$shell" == "/bin/false" ]]; then
            log_success "Service user shell properly restricted"
        else
            log_warning "Service user shell not restricted: $shell"
        fi

        if [[ "$home" == "$DATA_DIR" ]]; then
            log_success "Service user home directory correctly set"
        else
            log_warning "Service user home directory: $home"
        fi
    else
        log_error "Service user '$SERVICE_NAME' does not exist"
    fi

    # Check if user is in minimal groups
    groups=$(groups "$SERVICE_NAME" 2>/dev/null | cut -d: -f2)
    log_info "Service user groups: $groups"
}

check_systemd_security() {
    log_info "Checking systemd security hardening..."

    local service_file="/etc/systemd/system/${SERVICE_NAME}.service"
    if [[ ! -f "$service_file" ]]; then
        log_error "Service file not found: $service_file"
        return
    fi

    # Check critical security settings
    local security_settings=(
        "NoNewPrivileges=yes"
        "PrivateTmp=yes"
        "PrivateDevices=yes"
        "ProtectSystem=strict"
        "ProtectHome=yes"
        "RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX"
        "SystemCallFilter=@system-service"
        "MemoryDenyWriteExecute=yes"
        "LockPersonality=yes"
    )

    for setting in "${security_settings[@]}"; do
        if grep -q "^$setting" "$service_file"; then
            log_success "Security setting enabled: $setting"
        else
            log_warning "Security setting missing: $setting"
        fi
    done

    # Check resource limits
    if grep -q "^MemoryMax=" "$service_file"; then
        log_success "Memory limits configured"
    else
        log_warning "No memory limits configured"
    fi

    if grep -q "^TasksMax=" "$service_file"; then
        log_success "Task limits configured"
    else
        log_warning "No task limits configured"
    fi
}

check_network_security() {
    log_info "Checking network security configuration..."

    # Check if socket is properly configured
    local socket_file="/etc/systemd/system/${SERVICE_NAME}.socket"
    if [[ -f "$socket_file" ]]; then
        # Check socket permissions
        if grep -q "SocketMode=0660" "$socket_file"; then
            log_success "Socket permissions properly restricted"
        else
            log_warning "Socket permissions may be too permissive"
        fi

        # Check socket ownership
        if grep -q "SocketGroup=caddy" "$socket_file"; then
            log_success "Socket group properly configured for Caddy"
        else
            log_warning "Socket group configuration needs review"
        fi
    fi

    # Check if service is listening on appropriate interfaces
    if systemctl is-active "${SERVICE_NAME}" &>/dev/null; then
        local listening
        listening=$(ss -tlnp | grep "$SERVICE_NAME" || echo "No network sockets found")
        log_info "Network sockets: $listening"

        # Check for public interface binding
        if echo "$listening" | grep -q "0.0.0.0"; then
            log_warning "Service appears to be listening on all interfaces"
        elif echo "$listening" | grep -q "127.0.0.1\|::1\|unix"; then
            log_success "Service properly restricted to local/socket interfaces"
        fi
    fi
}

check_configuration_security() {
    log_info "Checking configuration security..."
    local config_file server_mode cert_file key_file
    local config_file="${CONFIG_DIR}/config.env"
    if [[ ! -f "$config_file" ]]; then
        log_error "Configuration file not found: $config_file"
        return
    fi

    # Check for secure defaults
    server_mode=$(grep "^SERVER__MODE=" "$config_file" | cut -d= -f2)
    case "$server_mode" in
        "unix_socket")
            log_success "Using secure unix socket mode"
            ;;
        "tls_socket")
            log_info "Using TLS socket mode - ensure certificates are valid"
            # Check if TLS certificates exist
            cert_file=$(grep "^SERVER__SSL_CERTFILE=" "$config_file" | cut -d= -f2)
            key_file=$(grep "^SERVER__SSL_KEYFILE=" "$config_file" | cut -d= -f2)

            if [[ -f "$cert_file" && -f "$key_file" ]]; then
                log_success "TLS certificates found"

                # Check certificate validity
                if openssl x509 -in "$cert_file" -checkend 86400 -noout &>/dev/null; then
                    log_success "TLS certificate valid for at least 24 hours"
                else
                    log_warning "TLS certificate expires soon or is invalid"
                fi
            else
                log_error "TLS certificates not found or inaccessible"
            fi
            ;;
        "development")
            log_warning "Development mode detected - not recommended for production"
            ;;
        *)
            log_warning "Unknown server mode: $server_mode"
            ;;
    esac

    # Check token encryption
    if grep -q "^STORAGE__ENCRYPT_TOKENS=true" "$config_file"; then
        log_success "Token encryption enabled"
    else
        log_warning "Token encryption disabled"
    fi

    # Check for secure headers
    if grep -q "^SECURITY__" "$config_file"; then
        log_success "Security settings configured"
    else
        log_warning "No explicit security settings found"
    fi

    # Check for GitHub credentials (but don't expose them)
    if grep -q "^GITHUB__CLIENT_ID=" "$config_file" && ! grep -q "your_client_id_here" "$config_file"; then
        log_success "GitHub Client ID configured"
    else
        log_warning "GitHub Client ID not configured"
    fi

    if grep -q "^GITHUB__CLIENT_SECRET=" "$config_file" && ! grep -q "your_client_secret_here" "$config_file"; then
        log_success "GitHub Client Secret configured"
    else
        log_warning "GitHub Client Secret not configured"
    fi
}

check_log_security() {
    log_info "Checking logging security..."
    local perms owner log_files
    # Check log directory permissions
    if [[ -d "$LOG_DIR" ]]; then
        perms=$(stat -c "%a" "$LOG_DIR")
        owner=$(stat -c "%U:%G" "$LOG_DIR")

        if [[ "$perms" == "755" ]] && [[ "$owner" == "${SERVICE_NAME}:${SERVICE_NAME}" ]]; then
            log_success "Log directory permissions correct"
        else
            log_warning "Log directory permissions: $perms $owner"
        fi

        # Check for log rotation
        if [[ -f "/etc/logrotate.d/${SERVICE_NAME}" ]]; then
            log_success "Log rotation configured"
        else
            log_warning "Log rotation not configured"
        fi
    fi

    # Check for sensitive information in logs
    if [[ -d "$LOG_DIR" ]]; then
        local sensitive_patterns=(
            "password"
            "secret"
            "token.*="
            "Authorization: Bearer"
            "client_secret"
        )

        log_files=$(find "$LOG_DIR" -name "*.log" -type f 2>/dev/null)
        if [[ -n "$log_files" ]]; then
            for pattern in "${sensitive_patterns[@]}"; do
                if grep -irl "$pattern" $log_files 2>/dev/null | head -1 | grep -q .; then
                    log_warning "Potential sensitive information in logs: $pattern"
                fi
            done
        fi
    fi
}

check_dependency_security() {
    log_info "Checking Python dependency security..."
    local venv_perms venv_path
    venv_path="${INSTALL_PREFIX}/.venv"
    if [[ -d "$venv_path" ]]; then
        # Check if pip-audit is available for security scanning
        if command -v pip-audit &>/dev/null; then
            log_info "Running pip-audit security scan..."
            if pip-audit --requirement "${INSTALL_PREFIX}/requirements.txt" --output-format=text 2>/dev/null; then
                log_success "No known security vulnerabilities in dependencies"
            else
                log_warning "Security vulnerabilities found in dependencies"
            fi
        else
            log_info "pip-audit not available for dependency security scanning"
        fi

        # Check virtual environment permissions
        venv_perms=$(stat -c "%a" "$venv_path")
        if [[ "$venv_perms" == "755" ]]; then
            log_success "Virtual environment permissions correct"
        else
            log_warning "Virtual environment permissions: $venv_perms"
        fi
    else
        log_warning "Virtual environment not found at $venv_path"
    fi
}

check_firewall_configuration() {
    log_info "Checking firewall configuration..."
    local ufw_status iptables_rules
    # Check UFW
    if command -v ufw &>/dev/null; then
        ufw_status=$(ufw status 2>/dev/null | head -1)
        log_info "UFW status: $ufw_status"

        if echo "$ufw_status" | grep -q "Status: active"; then
            # Check for appropriate rules
            if ufw status | grep -q "8443\|8000"; then
                log_success "UFW rules found for service ports"
            else
                log_warning "No UFW rules found for service ports"
            fi
        fi
    fi

    # Check firewalld
    if command -v firewall-cmd &>/dev/null; then
        if firewall-cmd --state &>/dev/null; then
            log_success "firewalld is active"
            # Check for service ports
            if firewall-cmd --list-ports 2>/dev/null | grep -q "8443\|8000"; then
                log_success "firewalld rules found for service ports"
            else
                log_warning "No firewalld rules found for service ports"
            fi
        else
            log_info "firewalld is not active"
        fi
    fi

    # Check iptables
    if command -v iptables &>/dev/null; then
        iptables_rules=$(iptables -L 2>/dev/null | wc -l)
        if [[ $iptables_rules -gt 10 ]]; then
            log_info "iptables rules are configured"
        fi
    fi
}

check_ssl_configuration() {
    log_info "Checking SSL/TLS configuration..."
    local config_file server_mode cert_file cert_info not_after
    # Check if using TLS socket mode
    config_file="${CONFIG_DIR}/config.env"
    if [[ -f "$config_file" ]]; then
        server_mode=$(grep "^SERVER__MODE=" "$config_file" | cut -d= -f2)

        if [[ "$server_mode" == "tls_socket" ]]; then
            cert_file=$(grep "^SERVER__SSL_CERTFILE=" "$config_file" | cut -d= -f2)

            if [[ -f "$cert_file" ]]; then
                # Check certificate details
                cert_info=$(openssl x509 -in "$cert_file" -text -noout 2>/dev/null)

                # Check key strength
                if echo "$cert_info" | grep -q "RSA Public-Key: (2048 bit)\|Public-Key: (256 bit)"; then
                    log_success "SSL certificate uses strong key"
                else
                    log_warning "SSL certificate may use weak key"
                fi

                # Check signature algorithm
                if echo "$cert_info" | grep -q "Signature Algorithm: sha256"; then
                    log_success "SSL certificate uses secure signature algorithm"
                else
                    log_warning "SSL certificate may use weak signature algorithm"
                fi

                # Check expiration
                not_after=$(echo "$cert_info" | grep "Not After" | sed 's/.*Not After : //')
                log_info "SSL certificate expires: $not_after"
            fi
        fi
    fi

    # Check for weak SSL/TLS configurations
    if systemctl is-active "${SERVICE_NAME}" &>/dev/null; then
        # This would require the service to be running and accessible
        # In a real audit, you might use tools like sslscan or testssl.sh
        log_info "SSL/TLS runtime configuration check would require external tools"
    fi
}

generate_report() {
    echo ""
    echo -e "${CYAN}================================${NC}"
    echo -e "${CYAN} Security Audit Report ${NC}"
    echo -e "${CYAN}================================${NC}"
    echo ""

    echo -e "${GREEN}PASSED CHECKS (${#SECURITY_PASSED[@]}):${NC}"
    for item in "${SECURITY_PASSED[@]}"; do
        echo -e "  ✓ $item"
    done

    if [[ ${#SECURITY_WARNINGS[@]} -gt 0 ]]; then
        echo ""
        echo -e "${YELLOW}WARNINGS (${#SECURITY_WARNINGS[@]}):${NC}"
        for item in "${SECURITY_WARNINGS[@]}"; do
            echo -e "  ⚠ $item"
        done
    fi

    if [[ ${#SECURITY_ISSUES[@]} -gt 0 ]]; then
        echo ""
        echo -e "${RED}CRITICAL ISSUES (${#SECURITY_ISSUES[@]}):${NC}"
        for item in "${SECURITY_ISSUES[@]}"; do
            echo -e "  ✗ $item"
        done
    fi

    echo ""
    echo -e "${CYAN}RECOMMENDATIONS:${NC}"
    echo "• Regularly update dependencies with 'uv pip install --upgrade'"
    echo "• Monitor logs for security events"
    echo "• Review firewall rules periodically"
    echo "• Rotate SSL certificates before expiration"
    echo "• Enable token encryption in production"
    echo "• Use dedicated service account with minimal privileges"
    echo "• Regular security audits with this script"

    if [[ ${#SECURITY_ISSUES[@]} -gt 0 ]]; then
        echo ""
        echo -e "${RED}⚠ SECURITY ISSUES FOUND - IMMEDIATE ACTION REQUIRED${NC}"
        exit 1
    elif [[ ${#SECURITY_WARNINGS[@]} -gt 0 ]]; then
        echo ""
        echo -e "${YELLOW}⚠ Security warnings found - review recommended${NC}"
        exit 2
    else
        echo ""
        echo -e "${GREEN}✓ All security checks passed${NC}"
        exit 0
    fi
}

main() {
    echo -e "${CYAN}GitHub Copilot API Proxy - Security Audit${NC}"
    echo -e "${CYAN}Version 2.0 - Production Security Validation${NC}"
    echo ""

    check_file_permissions
    check_user_security
    check_systemd_security
    check_network_security
    check_configuration_security
    check_log_security
    check_dependency_security
    check_firewall_configuration
    check_ssl_configuration

    generate_report
}

# Run main function
main "$@"