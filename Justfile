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
    uv run ty check . --exclude "app/services/highlight_extractor.py" --exclude "tests/"

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

# Install dependencies
install:
    uv sync --dev

# Start development server
dev:
    uv run uvicorn app.main:app --host 0.0.0.0 --port 18742 --reload

# Start production server
serve:
    uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
