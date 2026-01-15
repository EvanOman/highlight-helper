#!/bin/bash
# Highlight Helper Service Installation Script
#
# This script installs the Highlight Helper as a systemd service.
# It must be run with sudo/root privileges.
#
# Usage:
#   sudo ./deploy/install.sh [install|uninstall|status]

set -e

SERVICE_NAME="highlight-helper"
SERVICE_FILE="highlight-helper.service"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "This script must be run as root (use sudo)"
        exit 1
    fi
}

check_dependencies() {
    if ! command -v docker &> /dev/null; then
        log_error "Docker is not installed"
        exit 1
    fi

    if ! command -v docker compose &> /dev/null; then
        log_error "Docker Compose is not installed"
        exit 1
    fi

    if ! systemctl is-active --quiet docker; then
        log_error "Docker service is not running"
        exit 1
    fi
}

install_service() {
    log_info "Installing ${SERVICE_NAME} service..."

    # Check dependencies
    check_dependencies

    # Check if .env file exists
    if [[ ! -f "${PROJECT_DIR}/.env" ]]; then
        log_warn ".env file not found. Creating from template..."
        if [[ -f "${PROJECT_DIR}/.env.example" ]]; then
            cp "${PROJECT_DIR}/.env.example" "${PROJECT_DIR}/.env"
            log_warn "Please edit ${PROJECT_DIR}/.env with your API keys"
        else
            log_error "No .env.example file found"
            exit 1
        fi
    fi

    # Create data directory if it doesn't exist
    mkdir -p "${PROJECT_DIR}/data"

    # Build the Docker image
    log_info "Building Docker image..."
    cd "${PROJECT_DIR}"
    docker compose build

    # Copy service file with project directory substituted
    log_info "Installing systemd service..."
    sed "s|__PROJECT_DIR__|${PROJECT_DIR}|g" "${SCRIPT_DIR}/${SERVICE_FILE}" > /etc/systemd/system/${SERVICE_FILE}

    # Reload systemd
    systemctl daemon-reload

    # Enable service to start on boot
    systemctl enable "${SERVICE_NAME}"

    # Start the service
    log_info "Starting service..."
    systemctl start "${SERVICE_NAME}"

    # Wait for health check
    log_info "Waiting for service to become healthy..."
    sleep 15

    # Check status
    if systemctl is-active --quiet "${SERVICE_NAME}"; then
        log_info "Service installed and running successfully!"
        log_info ""
        log_info "Useful commands:"
        log_info "  sudo systemctl status ${SERVICE_NAME}  - Check service status"
        log_info "  sudo systemctl stop ${SERVICE_NAME}    - Stop the service"
        log_info "  sudo systemctl start ${SERVICE_NAME}   - Start the service"
        log_info "  sudo systemctl restart ${SERVICE_NAME} - Restart the service"
        log_info "  sudo journalctl -u ${SERVICE_NAME} -f  - Follow logs"
        log_info ""
        log_info "Access the application at: http://localhost:18742"
    else
        log_error "Service failed to start. Check logs with: journalctl -u ${SERVICE_NAME}"
        exit 1
    fi
}

uninstall_service() {
    log_info "Uninstalling ${SERVICE_NAME} service..."

    # Stop the service if running
    if systemctl is-active --quiet "${SERVICE_NAME}"; then
        log_info "Stopping service..."
        systemctl stop "${SERVICE_NAME}"
    fi

    # Disable the service
    if systemctl is-enabled --quiet "${SERVICE_NAME}" 2>/dev/null; then
        log_info "Disabling service..."
        systemctl disable "${SERVICE_NAME}"
    fi

    # Remove service file
    if [[ -f "/etc/systemd/system/${SERVICE_FILE}" ]]; then
        log_info "Removing service file..."
        rm "/etc/systemd/system/${SERVICE_FILE}"
    fi

    # Reload systemd
    systemctl daemon-reload

    log_info "Service uninstalled successfully!"
    log_info "Note: Docker images and data directory were not removed."
    log_info "To remove Docker images: docker compose down --rmi all"
    log_info "To remove data: rm -rf ${PROJECT_DIR}/data"
}

show_status() {
    echo "Service Status:"
    echo "==============="
    systemctl status "${SERVICE_NAME}" --no-pager || true
    echo ""
    echo "Container Status:"
    echo "================="
    docker ps --filter "name=${SERVICE_NAME}" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" || true
    echo ""
    echo "Health Check:"
    echo "============="
    docker inspect --format='{{.State.Health.Status}}' "${SERVICE_NAME}" 2>/dev/null || echo "Container not running"
}

# Main
case "${1:-install}" in
    install)
        check_root
        install_service
        ;;
    uninstall)
        check_root
        uninstall_service
        ;;
    status)
        show_status
        ;;
    *)
        echo "Usage: $0 [install|uninstall|status]"
        echo ""
        echo "Commands:"
        echo "  install    - Install and start the service (default)"
        echo "  uninstall  - Stop and remove the service"
        echo "  status     - Show service and container status"
        exit 1
        ;;
esac
