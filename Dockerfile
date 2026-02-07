# Dockerfile for Highlight Helper
# Multi-stage build for smaller final image

# =============================================================================
# Stage 1: Builder - Install dependencies
# =============================================================================
FROM python:3.13-slim AS builder

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Set working directory
WORKDIR /app

# Copy dependency files first (for better caching)
COPY pyproject.toml uv.lock readwise_sdk-0.1.0-py3-none-any.whl ./

# Install dependencies into a virtual environment
RUN uv sync --frozen --no-dev --no-install-project

# =============================================================================
# Stage 2: Runtime - Final image
# =============================================================================
FROM python:3.13-slim AS runtime

# Install curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash appuser

# Set working directory
WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy application code
COPY app/ ./app/
COPY static/ ./static/

# Create directories for data, certs, and backups (will be mounted as volumes)
RUN mkdir -p /app/data /app/certs /app/backups && chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Set environment variables
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Default database location (can be overridden)
ENV DATABASE_URL="sqlite+aiosqlite:///./data/highlight_helper.db"

# Expose the application port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/ || exit 1

# Run the application with proxy headers support for Tailscale
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
