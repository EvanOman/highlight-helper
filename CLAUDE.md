# Highlight Helper - Development Guide

## Quick Reference

```bash
just fc          # Format, lint, type-check, unit+integration tests (run before every commit)
just test-e2e    # E2E tests with Playwright (run before pushing to GitHub)
just test-all    # All tests (unit + integration + e2e)
just redeploy    # Rebuild and restart Docker container for local deployment
```

## Testing

### Local Validation vs CI

`just fc` runs unit and integration tests but **does not run E2E tests**. CI runs both plus E2E as a separate job. To avoid pushing code that breaks CI:

```bash
just fc && just test-e2e    # Full local validation matching CI
```

### E2E Tests

E2E tests (`tests/e2e/`) use Playwright and spin up a real uvicorn server against a **temporary SQLite database**. They never touch the production database.

If E2E tests fail with connection errors, check that port 8765 is free.

## Database

The production SQLite database (`highlight_helper.db`) contains real user data. **Never delete or overwrite it.** Tests use isolated in-memory or temp databases.

Schema migrations are managed by **Alembic** (`alembic/` directory). On startup, `init_db()` detects the database state and either runs migrations from scratch (fresh DB), stamps the baseline then upgrades (pre-Alembic DB), or simply upgrades to head (already managed).

```bash
just migrate             # Run pending migrations
just migration "add foo" # Create a new auto-generated migration
```

When writing new test fixtures that need a database, always use the existing `test_session` / `override_get_db` fixtures from `tests/conftest.py`, or the temp-directory approach in the E2E server fixture. Never reference `highlight_helper.db` directly in tests. Tests use `Base.metadata.create_all` directly (not Alembic) for speed.

## Architecture

- **Repository pattern**: All DB access goes through `app/repositories/`. Repositories raise `NotFoundError` (domain exception), never `HTTPException`.
- **Dependency injection**: Repositories and services are injected via FastAPI `Depends()`.
- **Async context managers**: `ReadwiseService` uses `async with` for resource cleanup.
- **Templates**: Jinja2 templates in `app/templates/`, shared setup in `app/api/views/_common.py`.

## Deployment

The app runs in Docker behind Tailscale Serve. Use `just redeploy` to rebuild and restart. The Docker container uses a persistent volume for the SQLite database - it is **not** the same file as the local `highlight_helper.db`.
