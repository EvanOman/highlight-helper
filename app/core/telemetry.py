"""OpenTelemetry setup and utilities for distributed tracing."""

import logging
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.trace import Status, StatusCode

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Global tracer instance
_tracer: trace.Tracer | None = None


def setup_telemetry() -> None:
    """Initialize OpenTelemetry tracing based on settings.

    Call this once during application startup.
    """
    global _tracer

    settings = get_settings()

    if not settings.otel_enabled:
        logger.info("OpenTelemetry tracing is disabled")
        _tracer = trace.get_tracer(__name__)
        return

    # Create resource with service information
    resource = Resource.create(
        {
            "service.name": settings.otel_service_name,
            "service.version": "0.1.0",
            "deployment.environment": settings.environment,
        }
    )

    # Create tracer provider
    provider = TracerProvider(resource=resource)

    # Configure exporter based on settings
    if settings.otel_exporter == "console":
        processor = BatchSpanProcessor(ConsoleSpanExporter())
        logger.info("OpenTelemetry configured with console exporter")
    elif settings.otel_exporter == "otlp":
        exporter = OTLPSpanExporter(
            endpoint=settings.otel_endpoint,
            insecure=True,  # Set to False in production with TLS
        )
        processor = BatchSpanProcessor(exporter)
        logger.info(f"OpenTelemetry configured with OTLP exporter at {settings.otel_endpoint}")
    elif settings.otel_exporter == "none":
        logger.info("OpenTelemetry tracing configured but no exporter set")
        _tracer = trace.get_tracer(__name__)
        return
    else:
        logger.warning(f"Unknown OTEL exporter '{settings.otel_exporter}', tracing disabled")
        _tracer = trace.get_tracer(__name__)
        return

    provider.add_span_processor(processor)

    # Set as global tracer provider
    trace.set_tracer_provider(provider)

    # Get tracer instance
    _tracer = trace.get_tracer(__name__)

    logger.info(f"OpenTelemetry tracing initialized for service: {settings.otel_service_name}")


def instrument_fastapi(app: Any) -> None:
    """Instrument FastAPI application for automatic tracing.

    Args:
        app: FastAPI application instance
    """
    settings = get_settings()
    if not settings.otel_enabled:
        return

    FastAPIInstrumentor.instrument_app(app)
    logger.info("FastAPI instrumentation enabled")


def instrument_httpx() -> None:
    """Instrument HTTPX client for automatic tracing of outbound HTTP requests."""
    settings = get_settings()
    if not settings.otel_enabled:
        return

    HTTPXClientInstrumentor().instrument()
    logger.info("HTTPX instrumentation enabled")


def instrument_sqlalchemy(engine: Any) -> None:
    """Instrument SQLAlchemy for automatic database query tracing.

    Args:
        engine: SQLAlchemy engine instance
    """
    settings = get_settings()
    if not settings.otel_enabled:
        return

    SQLAlchemyInstrumentor().instrument(engine=engine)
    logger.info("SQLAlchemy instrumentation enabled")


def get_tracer(name: str | None = None) -> trace.Tracer:
    """Get a tracer instance for creating spans.

    Args:
        name: Optional name for the tracer (defaults to module name)

    Returns:
        OpenTelemetry Tracer instance
    """
    if _tracer is not None and name is None:
        return _tracer
    return trace.get_tracer(name or __name__)


@contextmanager
def create_span(
    name: str,
    attributes: dict[str, Any] | None = None,
    record_exception: bool = True,
):
    """Create a traced span with optional attributes.

    Usage:
        with create_span("operation_name", {"key": "value"}) as span:
            # Your code here
            span.set_attribute("result", "success")

    Args:
        name: Name of the span/operation
        attributes: Optional dict of initial attributes
        record_exception: Whether to record exceptions on the span

    Yields:
        The active span
    """
    tracer = get_tracer()
    with tracer.start_as_current_span(name) as span:
        if attributes:
            for key, value in attributes.items():
                span.set_attribute(key, value)
        try:
            yield span
        except Exception as e:
            if record_exception:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
            raise


def add_span_attributes(**attributes: Any) -> None:
    """Add attributes to the current active span.

    Args:
        **attributes: Key-value pairs to add to the span
    """
    span = trace.get_current_span()
    for key, value in attributes.items():
        if value is not None:
            span.set_attribute(key, value)


def set_span_status(success: bool, message: str = "") -> None:
    """Set the status of the current active span.

    Args:
        success: Whether the operation was successful
        message: Optional status message
    """
    span = trace.get_current_span()
    if success:
        span.set_status(Status(StatusCode.OK, message))
    else:
        span.set_status(Status(StatusCode.ERROR, message))
