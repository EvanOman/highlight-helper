"""Readwise integration API routes."""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    ReadwiseBatchSyncResponse,
    ReadwiseStatusResponse,
    ReadwiseSyncResponse,
)
from app.core.database import get_db
from app.models.highlight import AnnotationType, SyncStatus
from app.repositories.book import BookRepository, get_book_repo
from app.repositories.highlight import HighlightRepository, get_highlight_repo
from app.services.readwise import ReadwiseService, sync_pending_highlights
from app.services.settings import get_settings_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/readwise", tags=["readwise"])


@router.get("/status", response_model=ReadwiseStatusResponse)
async def get_readwise_status(
    db: AsyncSession = Depends(get_db),
) -> ReadwiseStatusResponse:
    """Get Readwise integration status."""
    settings = await get_settings_service(db)
    token = await settings.get_readwise_token()
    configured = bool(token)

    token_valid = None
    if configured:
        async with ReadwiseService(api_token=token) as service:
            token_valid = await service.validate_token()

    return ReadwiseStatusResponse(
        configured=configured,
        token_valid=token_valid,
    )


@router.post("/validate", response_model=ReadwiseStatusResponse)
async def validate_readwise_token(
    db: AsyncSession = Depends(get_db),
) -> ReadwiseStatusResponse:
    """Validate the Readwise API token."""
    settings = await get_settings_service(db)
    token = await settings.get_readwise_token()
    if not token:
        return ReadwiseStatusResponse(configured=False, token_valid=None)

    async with ReadwiseService(api_token=token) as service:
        token_valid = await service.validate_token()
        return ReadwiseStatusResponse(configured=True, token_valid=token_valid)


@router.post("/sync/all", response_model=ReadwiseBatchSyncResponse)
async def sync_all_highlights(
    db: AsyncSession = Depends(get_db),
) -> ReadwiseBatchSyncResponse:
    """Sync all unsynced highlights to Readwise."""
    settings = await get_settings_service(db)
    token = await settings.get_readwise_token()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Readwise API token not configured",
        )
    result = await sync_pending_highlights(db, token)
    return ReadwiseBatchSyncResponse(
        total=result.total,
        synced=result.synced,
        failed=result.failed,
    )


@router.post("/sync/{highlight_id}", response_model=ReadwiseSyncResponse)
async def sync_highlight(
    highlight_id: int,
    db: AsyncSession = Depends(get_db),
    highlight_repo: HighlightRepository = Depends(get_highlight_repo),
) -> ReadwiseSyncResponse:
    """Sync a single highlight to Readwise.

    If the highlight was previously synced (has readwise_id), uses PATCH to update.
    Otherwise, uses POST to create a new highlight on Readwise.
    """
    settings = await get_settings_service(db)
    token = await settings.get_readwise_token()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Readwise API token not configured",
        )
    # Get highlight with book
    highlight, book = await highlight_repo.get_with_book_or_raise(highlight_id)

    # Notes cannot be synced to Readwise
    if highlight.type == AnnotationType.NOTE:
        logger.info(
            "Rejecting sync request for note id=%d - notes are not supported by Readwise",
            highlight_id,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Notes cannot be synced to Readwise",
        )

    # Use PATCH if highlight was previously synced, otherwise POST
    async with ReadwiseService(api_token=token) as service:
        if highlight.readwise_id:
            # Update existing highlight on Readwise
            sync_result = await service.update_highlight(
                readwise_id=highlight.readwise_id,
                text=highlight.text,
                note=highlight.note,
                page_number=highlight.page_number,
            )
        else:
            # Create new highlight on Readwise
            sync_result = await service.send_highlight(
                text=highlight.text or "",
                title=book.title,
                author=book.author,
                note=highlight.note,
                page_number=highlight.page_number,
                highlighted_at=highlight.created_at,
            )

    if sync_result.success:
        # Update highlight with sync info
        if sync_result.readwise_id:
            highlight.readwise_id = sync_result.readwise_id
        highlight.synced_at = datetime.now(tz=UTC)
        highlight.sync_status = SyncStatus.SYNCED
        await highlight_repo.flush()

    return ReadwiseSyncResponse(
        success=sync_result.success,
        readwise_id=sync_result.readwise_id or highlight.readwise_id,
        error=sync_result.error,
    )


@router.post("/sync/book/{book_id}", response_model=ReadwiseBatchSyncResponse)
async def sync_book_highlights(
    book_id: int,
    db: AsyncSession = Depends(get_db),
    book_repo: BookRepository = Depends(get_book_repo),
) -> ReadwiseBatchSyncResponse:
    """Sync all unsynced highlights for a book to Readwise."""
    settings = await get_settings_service(db)
    token = await settings.get_readwise_token()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Readwise API token not configured",
        )
    # Verify book exists
    await book_repo.get_or_raise(book_id)

    result = await sync_pending_highlights(db, token, book_id=book_id)
    return ReadwiseBatchSyncResponse(
        total=result.total,
        synced=result.synced,
        failed=result.failed,
    )
