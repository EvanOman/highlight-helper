"""Main FastAPI application."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.books import router as books_router
from app.api.highlights import router as highlights_router
from app.api.readwise import router as readwise_router
from app.api.views import router as views_router
from app.core.config import get_settings
from app.core.database import init_db
from app.core.tracing import setup_tracing, shutdown_tracing
from app.services.book_lookup import book_lookup_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    await init_db()
    yield
    # Shutdown
    await book_lookup_service.close()
    shutdown_tracing()


settings = get_settings()

app = FastAPI(
    title="Highlight Helper",
    description=(
        "A mobile-friendly web app for collecting book highlights "
        "using AI-powered image recognition"
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# Setup OpenTelemetry tracing (must be done before adding routes)
setup_tracing(app)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Include routers
app.include_router(views_router)
app.include_router(books_router)
app.include_router(highlights_router)
app.include_router(readwise_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.is_development,
    )
