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

# Build Tailwind CSS (minified)
css:
    TAILWINDCSS_VERSION=v3.4.17 uv run tailwindcss -i static/css/input.css -o static/css/app.css --minify

# Watch Tailwind CSS for changes (dev mode)
css-watch:
    TAILWINDCSS_VERSION=v3.4.17 uv run tailwindcss -i static/css/input.css -o static/css/app.css --watch

# Cross-boundary contract checks (SSE protocol coverage, self-contained deps, Dockerfile sources)
lint-contracts:
    uv run python scripts/check_contracts.py

# Full-stack chat self-test in a real browser with a deterministic fake LLM (no API cost)
selftest:
    uv run pytest tests/e2e/test_chat_selftest.py -v

# Read-only smoke check against a running instance (default: local prod container)
smoke url="http://127.0.0.1:18742/highlights":
    uv run python scripts/smoke.py {{url}}

# Regenerate the synthetic-realistic eval dataset (images + dataset.json)
eval-generate:
    uv run python -m evals.generate_dataset

# Run extraction evals ONLINE (real API, populates the cache) against a pipeline
eval pipeline="service":
    uv run python -m evals.cli --pipeline {{pipeline}} --json-out evals/reports/latest.json -v

# Replay extraction evals OFFLINE from the cache (no API cost; for CI/smoke)
eval-offline pipeline="service":
    uv run python -m evals.cli --pipeline {{pipeline}} --offline

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
fc: css fmt lint-fix lint lint-contracts type test

# CI checks (no auto-fix)
ci: lint format-check lint-contracts type test

# Update vendored chatkit assets from sibling repo
update-chatkit:
    rm -rf static/chatkit
    cp -r ../chatkit/dist static/chatkit
    cp ../chatkit/src/theme/chatkit.css static/chatkit/theme/chatkit.css

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

# Redeploy: rebuild, restart, wait for health, then smoke-check the live instance
redeploy: docker-restart
    @echo "Waiting for container health..."
    @timeout 90 bash -c 'until [ "$(docker inspect -f "{{{{.State.Health.Status}}" highlight-helper 2>/dev/null)" = "healthy" ]; do sleep 2; done'
    just smoke

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
# Database Migrations (Alembic)
# =============================================================================

# Run pending migrations
migrate:
    uv run alembic upgrade head

# Create a new auto-generated migration
migration name:
    uv run alembic revision --autogenerate -m "{{name}}"

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
