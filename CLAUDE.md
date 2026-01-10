# Claude Code Instructions

This file contains instructions for Claude Code when working on this project.

## Before Committing Changes

**IMPORTANT**: Always run tests before committing any code changes.

```bash
# Run unit and integration tests
python -m pytest tests/unit tests/integration -v --tb=short

# Run linter
ruff check app/ tests/

# Run formatter check
ruff format --check app/ tests/
```

All tests must pass before creating commits or pull requests.

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

## Pull Request Workflow

1. Create a feature branch from main
2. Make changes
3. Run tests and linter locally
4. Commit with descriptive message
5. Push and create PR for review
