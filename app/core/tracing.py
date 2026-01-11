"""OpenTelemetry tracing setup and utilities."""

import logging
from typing import TYPE_CHECKING

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Tracer

from app.core.config import get_settings

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)

# Global tracer provider reference for shutdown
_tracer_provider: TracerProvider | None = None


def setup_tracing(app: "FastAPI") -> None:
    """Initialize OpenTelemetry tracing and instrument the FastAPI application.

    This function:
    1. Creates a TracerProvider with service resource attributes
    2. Configures the OTLP exporter based on settings
    3. Instruments FastAPI, httpx, and SQLAlchemy automatically

    Args:
        app: The FastAPI application instance to instrument.
    """
    global _tracer_provider

    settings = get_settings()

    if not settings.otel_enabled:
        logger.info("OpenTelemetry tracing is disabled")
        return

    logger.info(f"Initializing OpenTelemetry tracing for service '{settings.otel_service_name}'")

    # Create resource with service information
    resource = Resource.create(
        {
            "service.name": settings.otel_service_name,
            "service.version": "0.1.0",
            "deployment.environment": settings.environment,
        }
    )

    # Create tracer provider
    _tracer_provider = TracerProvider(resource=resource)

    # Configure exporter based on protocol
    if settings.otel_exporter_otlp_protocol == "grpc":
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )

        exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint)
    else:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )

        exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint)

    # Add batch processor for efficient span export
    _tracer_provider.add_span_processor(BatchSpanProcessor(exporter))

    # Set as global tracer provider
    trace.set_tracer_provider(_tracer_provider)

    # Instrument FastAPI
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app)

    # Instrument httpx for external API calls
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentation

    HTTPXClientInstrumentation().instrument()

    # Instrument SQLAlchemy for database queries
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

    from app.core.database import engine

    SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)

    logger.info(
        f"OpenTelemetry tracing initialized, exporting to {settings.otel_exporter_otlp_endpoint}"
    )


def shutdown_tracing() -> None:
    """Gracefully shutdown the tracer provider.

    This ensures all pending spans are flushed before the application exits.
    """
    global _tracer_provider

    if _tracer_provider is not None:
        logger.info("Shutting down OpenTelemetry tracing")
        _tracer_provider.shutdown()
        _tracer_provider = None


def get_tracer(name: str) -> Tracer:
    """Get a tracer instance for creating custom spans.

    Args:
        name: The name of the tracer, typically the module name.

    Returns:
        A Tracer instance for creating spans.
    """
    return trace.get_tracer(name)
