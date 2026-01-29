# Claude Code Instructions

This file contains instructions for Claude Code when working on this project.

## Before Committing Changes

**IMPORTANT**: Always run CI checks before committing any code changes.

```bash
# Run all checks (format, lint, type check, tests) - same as CI
just fc
```

This runs:
1. `just fmt` - Format code with ruff
2. `just lint-fix` - Fix linting issues
3. `just lint` - Verify no lint errors
4. `just type` - Type check with ty (excludes some files with DSPy issues)
5. `just test` - Run unit and integration tests

All checks must pass before creating commits or pull requests. CI will fail if any of these checks fail.

**Note**: The type checker excludes `app/services/highlight_extractor.py`, `app/services/isbn_extractor.py`, and `tests/` due to DSPy-related type issues.

## Development Validation Requirements

**IMPORTANT**: Significant UI/UX changes require loop-closed development validation.

For any significant change (new features, UI modifications, workflow changes):

1. **Start the dev server**: `uv run uvicorn app.main:app --host 0.0.0.0 --port 18742`
2. **Manually validate** the change works as expected in a browser
3. **Test on mobile viewport** if the change affects responsive design
4. **Run e2e tests** to ensure no regressions: `python -m pytest tests/e2e -v`

This ensures changes are validated end-to-end before committing.

## Project Structure

- `app/` - Main application code (FastAPI)
- `tests/unit/` - Unit tests
- `tests/integration/` - Integration tests
- `tests/e2e/` - End-to-end tests (require Playwright)
- `evals/` - Evaluation framework for AI extraction

## Key Services

### HighlightExtractorService (`app/services/highlight_extractor.py`)

Uses DSPy with OpenAI's GPT-5.2 for extracting text from book page images. When modifying this service:

1. The service accepts an optional `lm` parameter for dependency injection in tests
2. Use `dspy.context()` for thread-safe LM configuration (not global `dspy.configure()`)
3. Mock `dspy.Image`, `dspy.asyncify`, and `dspy.context` in tests since DSPy validates real image data

### BookLookupService (`app/services/book_lookup.py`)

Uses Google Books API for book search. Mock `_get_client()` in tests.

## Testing Guidelines

1. **Mock external services**: Always mock OpenAI/DSPy calls and external APIs
2. **Use dependency injection**: Services accept optional dependencies for testing
3. **Test public API**: Focus on testing the public interface, not implementation details
4. **Run tests locally**: CI will fail if tests don't pass locally

### E2E Tests (Playwright)

The project includes selector-based Playwright e2e tests in `tests/e2e/`. These test full user flows:

```bash
# Run e2e tests (requires Playwright installed)
python -m pytest tests/e2e -v

# Skip e2e tests
SKIP_E2E_TESTS=true python -m pytest tests/e2e -v
```

When adding new UI features:
- Add corresponding e2e tests to validate the user flow
- Use CSS selectors or text-based locators (e.g., `page.locator("text=Save Highlight")`)
- Test at multiple viewport sizes for responsive design

## HTTPS Setup

For local development or accessing over Tailscale, you may need HTTPS to avoid browser security warnings on form submissions.

### Using Self-Signed Certificates

1. **Generate certificates**:
   ```bash
   just gen-cert localhost
   # Or for Tailscale access:
   just gen-cert your-machine.tailnet-name.ts.net
   ```

2. **Start the server with HTTPS**:
   ```bash
   just dev-https
   # Or for production:
   just serve-https
   ```

3. **Accept the certificate** in your browser (self-signed certificates will show a warning).

### Alternative: Tailscale HTTPS

If using Tailscale, you can use Tailscale's built-in HTTPS feature:
1. Enable HTTPS in your Tailscale admin console
2. Access via `https://your-machine.tailnet-name.ts.net`
3. Tailscale will handle certificate provisioning automatically

## Deployment

This service runs via Docker and is accessible at:
- **Local**: http://localhost:18742
- **Tailscale**: https://omachine.werewolf-universe.ts.net/highlights/

### Tailscale Serve Configuration

The app uses `ROOT_PATH=/highlights` which requires the Tailscale serve route to preserve the path prefix:

```bash
tailscale serve --bg --set-path /highlights http://localhost:18742/highlights
```

This proxies requests to `http://localhost:18742/highlights/...` (NOT stripping the prefix). Without this, static files and some routes will return 404 because FastAPI's `root_path` setting makes route matching expect the full path including the prefix.

### Redeploy After Code Changes

To deploy local changes to the running service:

```bash
# Rebuild and restart (one command)
docker compose build && docker compose down && docker compose -f docker-compose.yml up -d

# Or use the Justfile targets:
just docker-restart
```

Wait ~30 seconds for the container to become healthy, then verify:
```bash
docker ps --filter "name=highlight-helper"
curl -I http://localhost:18742/
```

### Quick Commands

```bash
# Check status
just docker-status

# View logs
just docker-logs

# Rebuild only (no restart)
just docker-build

# Stop service
just docker-down
```

## Pull Request Workflow

1. Create a feature branch from main
2. Make changes
3. Run tests and linter locally
4. Commit with descriptive message
5. Push and create PR for review
