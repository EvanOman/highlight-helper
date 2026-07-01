"""Settings API routes."""

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.model_registry import is_valid_chat_model
from app.models.highlight import SyncStatus
from app.repositories.highlight import HighlightRepository
from app.services.readwise import ReadwiseService, sync_pending_highlights
from app.services.settings import get_settings_service

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsResponse(BaseModel):
    """Response model for settings."""

    readwise_token_configured: bool
    readwise_auto_sync: bool
    chat_model: str
    coaching_model: str


class UpdateSettingsRequest(BaseModel):
    """Request model for updating settings."""

    readwise_token: str | None = None
    readwise_auto_sync: bool | None = None
    chat_model: str | None = None
    coaching_model: str | None = None
    coaching_enabled: bool | None = None


class SyncAllResponse(BaseModel):
    """Response model for sync all operation."""

    total: int
    synced: int
    failed: int
    already_synced: int


@router.get("", response_model=SettingsResponse)
async def get_settings(
    db: AsyncSession = Depends(get_db),
) -> SettingsResponse:
    """Get current application settings."""
    settings = await get_settings_service(db)

    token = await settings.get_readwise_token()
    auto_sync = await settings.get_readwise_auto_sync()
    chat_model = await settings.get_chat_model()
    coaching_model = await settings.get_coaching_model()

    return SettingsResponse(
        readwise_token_configured=bool(token),
        readwise_auto_sync=auto_sync,
        chat_model=chat_model,
        coaching_model=coaching_model,
    )


@router.post("", response_model=SettingsResponse)
async def update_settings(
    request: UpdateSettingsRequest,
    db: AsyncSession = Depends(get_db),
) -> SettingsResponse:
    """Update application settings."""
    settings = await get_settings_service(db)

    if request.readwise_token is not None:
        # Empty string clears the token
        token = request.readwise_token if request.readwise_token else None
        await settings.set_readwise_token(token)

    if request.readwise_auto_sync is not None:
        await settings.set_readwise_auto_sync(request.readwise_auto_sync)

    if request.chat_model is not None:
        if not is_valid_chat_model(request.chat_model):
            raise HTTPException(status_code=422, detail=f"Unknown model: {request.chat_model}")
        await settings.set_chat_model(request.chat_model)

    if request.coaching_model is not None:
        if not is_valid_chat_model(request.coaching_model):
            raise HTTPException(status_code=422, detail=f"Unknown model: {request.coaching_model}")
        await settings.set_coaching_model(request.coaching_model)

    if request.coaching_enabled is not None:
        await settings.set_bool("coaching_enabled", request.coaching_enabled)

    # Return updated settings
    token = await settings.get_readwise_token()
    auto_sync = await settings.get_readwise_auto_sync()
    chat_model = await settings.get_chat_model()
    coaching_model = await settings.get_coaching_model()

    return SettingsResponse(
        readwise_token_configured=bool(token),
        readwise_auto_sync=auto_sync,
        chat_model=chat_model,
        coaching_model=coaching_model,
    )


@router.post("/readwise/validate")
async def validate_readwise_token(
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Validate the configured Readwise API token."""
    settings = await get_settings_service(db)
    token = await settings.get_readwise_token()

    if not token:
        return {"valid": False, "error": "No token configured"}

    async with ReadwiseService(api_token=token) as service:
        is_valid = await service.validate_token()
        return {"valid": is_valid, "error": None if is_valid else "Invalid token"}


@router.post("/readwise/sync-all", response_model=SyncAllResponse)
async def sync_all_highlights(
    db: AsyncSession = Depends(get_db),
) -> SyncAllResponse:
    """Sync all unsynced highlights to Readwise.

    Only syncs highlights with PENDING status. Highlights that are already
    SYNCED or REMOVED_EXTERNALLY are not re-synced.
    """
    settings = await get_settings_service(db)
    token = await settings.get_readwise_token()

    if not token:
        return SyncAllResponse(total=0, synced=0, failed=0, already_synced=0)

    highlight_repo = HighlightRepository(db)
    already_synced = await highlight_repo.count_by_sync_status(SyncStatus.SYNCED)

    result = await sync_pending_highlights(db, token)

    return SyncAllResponse(
        total=result.total,
        synced=result.synced,
        failed=result.failed,
        already_synced=already_synced,
    )


@router.post("/readwise/sync-down")
async def sync_down_from_readwise(
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Import highlights from Readwise into the local database.

    Uses Server-Sent Events (SSE) to stream progress updates.
    The final event contains the complete result.
    """

    settings = await get_settings_service(db)
    token = await settings.get_readwise_token()

    async def generate_events():
        # Prefer the UI-configured token; ReadwiseService falls back to the
        # READWISE_API_TOKEN environment variable when token is None.
        async with ReadwiseService(api_token=token) as service:
            if not service.is_configured:
                # Send error and complete
                event_data = {
                    "phase": "complete",
                    "message": "Readwise API token not configured",
                    "books_processed": 0,
                    "books_total": 0,
                    "highlights_imported": 0,
                    "highlights_skipped": 0,
                    "errors": [
                        "Readwise API token not configured. "
                        "Add a token in Settings or set READWISE_API_TOKEN."
                    ],
                }
                yield f"data: {json.dumps(event_data)}\n\n"
                return
            try:
                async for progress in service.sync_down(db):
                    event_data = {
                        "phase": progress.phase,
                        "message": progress.message,
                        "books_processed": progress.books_processed,
                        "books_total": progress.books_total,
                        "highlights_imported": progress.highlights_imported,
                        "highlights_skipped": progress.highlights_skipped,
                        "errors": progress.errors,
                    }
                    yield f"data: {json.dumps(event_data)}\n\n"

                    # Commit after processing phase completes
                    if progress.phase == "complete":
                        await db.commit()
            except Exception as e:
                error_data = {
                    "phase": "complete",
                    "message": f"Error: {e}",
                    "books_processed": 0,
                    "books_total": 0,
                    "highlights_imported": 0,
                    "highlights_skipped": 0,
                    "errors": [str(e)],
                }
                yield f"data: {json.dumps(error_data)}\n\n"

    return StreamingResponse(
        generate_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
