set shell := ["bash", "-cu"]

default:
    @just --list

# Format code
fmt:
    uv run ruff format .

# Check formatting without changes
format-check:
    uv run ruff format --check .

# Run linter
lint:
    uv run ruff check .

# Run linter with auto-fix
lint-fix:
    uv run ruff check . --fix

# Run type checker
type:
    uv run ty check .

# Run unit and integration tests
test:
    uv run pytest tests/unit tests/integration

# Run e2e tests (requires Playwright)
test-e2e:
    uv run pytest tests/e2e -v

# Run all tests including e2e
test-all:
    uv run pytest tests/

# FIX + CHECK: Run before every commit
fc: fmt lint-fix lint type test

# CI checks (no auto-fix)
ci: lint format-check type test

# Update vendored chatkit assets from sibling repo
update-chatkit:
    rm -rf static/chatkit
    cp -r ../chatkit/dist static/chatkit

# Install dependencies
install:
    uv sync --dev

# Start development server (HTTP)
dev:
    uv run uvicorn app.main:app --host 0.0.0.0 --port 18742 --reload

# Start development server with HTTPS (requires certs)
dev-https:
    @if [ ! -f certs/cert.pem ] || [ ! -f certs/key.pem ]; then \
        echo "Error: SSL certificates not found."; \
        echo "Run 'just gen-cert' to generate self-signed certificates."; \
        exit 1; \
    fi
    uv run uvicorn app.main:app --host 0.0.0.0 --port 18742 --reload --ssl-keyfile=certs/key.pem --ssl-certfile=certs/cert.pem

# Generate self-signed SSL certificates for local HTTPS
gen-cert domain="localhost":
    ./scripts/generate_cert.sh {{domain}}

# Start production server
serve:
    uv run uvicorn app.main:app --host 0.0.0.0 --port 8000

# Start production server with HTTPS
serve-https:
    @if [ ! -f certs/cert.pem ] || [ ! -f certs/key.pem ]; then \
        echo "Error: SSL certificates not found."; \
        echo "Run 'just gen-cert' to generate certificates."; \
        exit 1; \
    fi
    uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --ssl-keyfile=certs/key.pem --ssl-certfile=certs/cert.pem

# =============================================================================
# Docker Commands
# =============================================================================

# Build Docker image
docker-build:
    docker compose build

# Start container (production mode - no code mounting)
docker-up:
    docker compose -f docker-compose.yml up -d

# Start container (development mode - with code mounting)
docker-up-dev:
    docker compose up -d

# Stop container
docker-down:
    docker compose down

# View container logs
docker-logs:
    docker compose logs -f

# Check container status
docker-status:
    @docker ps --filter "name=highlight-helper"
    @echo ""
    @docker inspect highlight-helper 2>/dev/null | grep -A2 '"Health"' | head -3 || echo "Container not running"

# Rebuild and restart container
docker-restart: docker-build docker-down docker-up

# Redeploy: rebuild and restart the production container (alias for docker-restart)
redeploy: docker-restart

# =============================================================================
# Service Management (systemd)
# =============================================================================

# Install as systemd service (requires sudo)
service-install:
    sudo ./deploy/install.sh install

# Uninstall systemd service (requires sudo)
service-uninstall:
    sudo ./deploy/install.sh uninstall

# Check service status
service-status:
    ./deploy/install.sh status

# View service logs (follows)
service-logs:
    sudo journalctl -u highlight-helper -f

# Restart the service (requires sudo)
service-restart:
    sudo systemctl restart highlight-helper

# =============================================================================
# Database Backup Commands
# =============================================================================

# Create a database backup
backup:
    ./scripts/backup_db.sh

# List available backups
backup-list:
    @echo "Available backups:"
    @find ./backups -name "highlight_helper_*.db" -type f 2>/dev/null | sort | while read backup; do \
        size=$$(du -h "$$backup" | cut -f1); \
        echo "  $$(basename $$backup) ($$size)"; \
    done || echo "  No backups found"

# Restore from a backup file
backup-restore file:
    @if [ ! -f "{{file}}" ]; then \
        echo "Error: Backup file not found: {{file}}"; \
        exit 1; \
    fi
    @echo "Restoring from: {{file}}"
    @echo "This will overwrite the current database. Press Ctrl+C to cancel..."
    @sleep 3
    cp "{{file}}" ./data/highlight_helper.db
    @echo "Database restored successfully."
