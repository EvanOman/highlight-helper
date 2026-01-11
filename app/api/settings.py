"""Settings API routes."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.highlight import Highlight, SyncStatus
from app.services.readwise import ReadwiseService
from app.services.settings import get_settings_service

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsResponse(BaseModel):
    """Response model for settings."""

    readwise_token_configured: bool
    readwise_auto_sync: bool


class UpdateSettingsRequest(BaseModel):
    """Request model for updating settings."""

    readwise_token: str | None = None
    readwise_auto_sync: bool | None = None


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

    return SettingsResponse(
        readwise_token_configured=bool(token),
        readwise_auto_sync=auto_sync,
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

    # Return updated settings
    token = await settings.get_readwise_token()
    auto_sync = await settings.get_readwise_auto_sync()

    return SettingsResponse(
        readwise_token_configured=bool(token),
        readwise_auto_sync=auto_sync,
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

    service = ReadwiseService(api_token=token)
    try:
        is_valid = await service.validate_token()
        return {"valid": is_valid, "error": None if is_valid else "Invalid token"}
    finally:
        await service.close()


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

    # Get all pending highlights (not yet synced and not removed externally)
    query = (
        select(Highlight)
        .where(Highlight.sync_status == SyncStatus.PENDING)
        .options(selectinload(Highlight.book))
    )
    result = await db.execute(query)
    pending = result.scalars().all()

    # Count already synced (SYNCED status)
    count_query = select(Highlight).where(Highlight.sync_status == SyncStatus.SYNCED)
    count_result = await db.execute(count_query)
    already_synced = len(count_result.scalars().all())

    if not pending:
        return SyncAllResponse(
            total=0,
            synced=0,
            failed=0,
            already_synced=already_synced,
        )

    # Build highlights list for batch sync
    highlights_data = []
    for h in pending:
        highlights_data.append(
            {
                "text": h.text,
                "title": h.book.title,
                "author": h.book.author,
                "note": h.note,
                "page_number": h.page_number,
                "highlighted_at": h.created_at,
            }
        )

    # Send to Readwise
    service = ReadwiseService(api_token=token)
    try:
        batch_result = await service.send_highlights(highlights_data)

        # Update synced highlights in database
        synced_count = 0
        for i, sync_result in enumerate(batch_result.results):
            if sync_result.success and i < len(pending):
                pending[i].synced_at = datetime.now(tz=timezone.utc)
                pending[i].sync_status = SyncStatus.SYNCED
                if sync_result.readwise_id:
                    pending[i].readwise_id = sync_result.readwise_id
                synced_count += 1

        await db.commit()

        return SyncAllResponse(
            total=len(pending),
            synced=synced_count,
            failed=len(pending) - synced_count,
            already_synced=already_synced,
        )
    finally:
        await service.close()
