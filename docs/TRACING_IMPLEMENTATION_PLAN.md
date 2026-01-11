# OpenTelemetry Tracing Implementation Plan

This document outlines the plan for implementing OpenTelemetry (OTEL) tracing in the Highlight Helper application as requested in [Issue #25](https://github.com/EvanOman/highlight-helper/issues/25).

## Goals

1. **Route-level tracing** - Automatic tracing for all FastAPI endpoints using OTEL extensions
2. **Service-level tracing** - Custom spans for key operations with relevant business attributes
3. **Flexible collector configuration** - Support for Jaeger (local dev) and cloud providers like Datadog (production)

## Dependencies to Add

```toml
# OpenTelemetry core packages
opentelemetry-api>=1.24.0
opentelemetry-sdk>=1.24.0

# FastAPI instrumentation (auto-instruments routes)
opentelemetry-instrumentation-fastapi>=0.45b0

# HTTP client instrumentation (traces httpx calls)
opentelemetry-instrumentation-httpx>=0.45b0

# SQLAlchemy instrumentation (traces database queries)
opentelemetry-instrumentation-sqlalchemy>=0.45b0

# OTLP exporter (standard protocol for Jaeger, Datadog, etc.)
opentelemetry-exporter-otlp>=1.24.0
```

## Configuration

Add the following environment variables to `app/core/config.py`:

| Variable | Default | Description |
|----------|---------|-------------|
| `OTEL_ENABLED` | `false` | Enable/disable tracing |
| `OTEL_SERVICE_NAME` | `highlight-helper` | Service name in traces |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4317` | OTLP collector endpoint |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `grpc` | Protocol: `grpc` or `http/protobuf` |

## Implementation Plan

### 1. Create Tracing Module (`app/core/tracing.py`)

This module will:
- Initialize the tracer provider with configurable exporters
- Set up resource attributes (service name, version, environment)
- Provide a `get_tracer()` function for creating spans in services
- Handle graceful shutdown of the tracer provider

```python
# Key functions:
def setup_tracing(app: FastAPI) -> None:
    """Initialize tracing and instrument FastAPI app."""

def get_tracer(name: str) -> Tracer:
    """Get a tracer instance for creating custom spans."""

def shutdown_tracing() -> None:
    """Gracefully shutdown the tracer provider."""
```

### 2. FastAPI Integration (`app/main.py`)

Integrate tracing into the application lifespan:
- Call `setup_tracing(app)` during startup
- Call `shutdown_tracing()` during shutdown

The `opentelemetry-instrumentation-fastapi` package automatically instruments:
- All route handlers (creates spans with route, method, status code)
- Request/response timing
- HTTP headers propagation

### 3. Service-Level Custom Spans

Add custom spans to each service with relevant business context attributes:

#### HighlightExtractorService (`app/services/highlight_extractor.py`)

```python
# Span: "highlight_extractor.extract_highlight"
# Attributes:
#   - extraction.filename
#   - extraction.instructions_length
#   - extraction.confidence
#   - extraction.has_page_number
#   - extraction.text_length
```

#### BookLookupService (`app/services/book_lookup.py`)

```python
# Span: "book_lookup.search_books"
# Attributes:
#   - book_lookup.query
#   - book_lookup.max_results
#   - book_lookup.results_count

# Span: "book_lookup.search_by_isbn"
# Attributes:
#   - book_lookup.isbn
#   - book_lookup.found
```

#### ISBNExtractorService (`app/services/isbn_extractor.py`)

```python
# Span: "isbn_extractor.extract_isbn"
# Attributes:
#   - extraction.filename
#   - extraction.confidence
#   - extraction.source (barcode/text/unknown)
#   - extraction.isbn_length
```

#### ReadwiseService (`app/services/readwise.py`)

```python
# Span: "readwise.send_highlight"
# Attributes:
#   - readwise.book_title
#   - readwise.success
#   - readwise.error (if failed)

# Span: "readwise.send_highlights" (batch)
# Attributes:
#   - readwise.total_highlights
#   - readwise.synced_count
#   - readwise.failed_count

# Span: "readwise.validate_token"
# Attributes:
#   - readwise.token_valid
```

### 4. External API Call Tracing

The `opentelemetry-instrumentation-httpx` package will automatically trace:
- Google Books API calls (BookLookupService)
- Readwise API calls (ReadwiseService)
- OpenAI API calls (via httpx in DSPy)

These will show as child spans with HTTP details (URL, method, status code, timing).

### 5. Database Tracing

The `opentelemetry-instrumentation-sqlalchemy` package will automatically trace:
- All database queries
- Query timing and parameters (sanitized)

## File Changes Summary

| File | Changes |
|------|---------|
| `pyproject.toml` | Add OTEL dependencies |
| `app/core/config.py` | Add OTEL configuration variables |
| `app/core/tracing.py` | **New file** - Tracing setup module |
| `app/main.py` | Integrate tracing lifecycle |
| `app/services/highlight_extractor.py` | Add custom spans |
| `app/services/book_lookup.py` | Add custom spans |
| `app/services/isbn_extractor.py` | Add custom spans |
| `app/services/readwise.py` | Add custom spans |

## Verification Steps

### 1. Local Development with Jaeger

```bash
# Start Jaeger with Docker
docker run -d --name jaeger \
  -p 16686:16686 \
  -p 4317:4317 \
  jaegertracing/all-in-one:latest

# Set environment variables
export OTEL_ENABLED=true
export OTEL_SERVICE_NAME=highlight-helper
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317

# Start the application
uv run uvicorn app.main:app --reload

# Access Jaeger UI at http://localhost:16686
```

### 2. Verification Checklist

- [ ] **Route tracing**: Make HTTP requests and verify spans appear in Jaeger for each route
- [ ] **Service spans**: Verify custom spans appear as children of route spans
- [ ] **Attributes**: Verify business attributes are attached to spans
- [ ] **External calls**: Verify httpx calls to Google Books, Readwise, OpenAI appear as child spans
- [ ] **Database queries**: Verify SQLAlchemy queries appear as child spans
- [ ] **Error tracking**: Verify errors are captured in spans with appropriate status
- [ ] **Disabled mode**: Verify app works correctly when `OTEL_ENABLED=false`

### 3. Sample Test Flows

1. **Book Search Flow**:
   - `GET /books/add` (view route)
   - `POST /books/search` with query (should show book_lookup.search_books span)

2. **Highlight Extraction Flow**:
   - `POST /books/{id}/extract` with image
   - Should show `highlight_extractor.extract_highlight` span with OpenAI API child span

3. **Readwise Sync Flow**:
   - `POST /api/readwise/sync/{highlight_id}`
   - Should show `readwise.send_highlight` span with Readwise API child span

## Production Deployment (Datadog Example)

For production with Datadog:

```bash
# Install Datadog agent with OTLP support
# Or use Datadog's OTLP ingest endpoint

export OTEL_ENABLED=true
export OTEL_SERVICE_NAME=highlight-helper
export OTEL_EXPORTER_OTLP_ENDPOINT=http://datadog-agent:4317
# Or for Datadog's direct OTLP ingestion:
# OTEL_EXPORTER_OTLP_ENDPOINT=https://trace.agent.datadoghq.com
```

The OTLP protocol is supported by most observability platforms:
- Jaeger (local/self-hosted)
- Datadog
- Honeycomb
- New Relic
- Grafana Tempo
- AWS X-Ray (via ADOT collector)

## Implementation Order

1. Add dependencies to `pyproject.toml`
2. Add configuration to `app/core/config.py`
3. Create `app/core/tracing.py`
4. Update `app/main.py` with tracing lifecycle
5. Add spans to `HighlightExtractorService`
6. Add spans to `BookLookupService`
7. Add spans to `ISBNExtractorService`
8. Add spans to `ReadwiseService`
9. Run tests to ensure no regressions
10. Manual verification with Jaeger
