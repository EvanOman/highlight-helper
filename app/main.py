"""Main FastAPI application."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.books import router as books_router
from app.api.chat import router as chat_router
from app.api.highlights import router as highlights_router
from app.api.readwise import router as readwise_router
from app.api.settings import router as settings_router
from app.api.views import router as views_router
from app.core.config import get_settings
from app.core.database import init_db
from app.core.exceptions import NotFoundError
from app.core.telemetry import instrument_fastapi, instrument_httpx, setup_telemetry
from app.services.book_lookup import book_lookup_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    setup_telemetry()
    instrument_httpx()
    await init_db()
    yield
    # Shutdown
    await book_lookup_service.close()


settings = get_settings()

app = FastAPI(
    title="Highlight Helper",
    description=(
        "A mobile-friendly web app for collecting book highlights "
        "using AI-powered image recognition"
    ),
    version="0.1.0",
    lifespan=lifespan,
    root_path=settings.root_path,
)


@app.exception_handler(NotFoundError)
async def not_found_handler(request: Request, exc: NotFoundError):
    if request.url.path.startswith("/api/"):
        return JSONResponse(status_code=404, content={"detail": exc.detail})
    from app.api.views._common import templates

    return templates.TemplateResponse(
        request,
        "error.html",
        {"status_code": 404, "detail": exc.detail},
        status_code=404,
    )


# Instrument FastAPI for tracing
instrument_fastapi(app)

# Mount static files at /static (and also at {root_path}/static for direct access)
app.mount("/static", StaticFiles(directory="static"), name="static")
if settings.root_path:
    app.mount(f"{settings.root_path}/static", StaticFiles(directory="static"), name="static_root")

# Include routers
app.include_router(views_router)
app.include_router(chat_router)
app.include_router(books_router)
app.include_router(highlights_router)
app.include_router(readwise_router)
app.include_router(settings_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.is_development,
    )
