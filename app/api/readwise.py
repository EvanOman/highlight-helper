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
from app.models.highlight import AnnotationType
from app.repositories.book import BookRepository, get_book_repo
from app.repositories.highlight import HighlightRepository, get_highlight_repo
from app.services.readwise import ReadwiseService
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
    highlight_repo: HighlightRepository = Depends(get_highlight_repo),
) -> ReadwiseBatchSyncResponse:
    """Sync all unsynced highlights to Readwise."""
    settings = await get_settings_service(db)
    token = await settings.get_readwise_token()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Readwise API token not configured",
        )
    # Get all unsynced highlights with their books (excluding notes)
    rows = await highlight_repo.list_unsynced()

    # Log if there are notes being excluded
    notes_count = await highlight_repo.count_unsynced_notes()
    if notes_count > 0:
        logger.info(
            "Skipping %d note(s) during sync - notes are not supported by Readwise",
            notes_count,
        )

    if not rows:
        return ReadwiseBatchSyncResponse(total=0, synced=0, failed=0)

    # Build highlight data for batch sync
    highlight_data = [
        {
            "text": h.text,
            "title": b.title,
            "author": b.author,
            "note": h.note,
            "page_number": h.page_number,
            "highlighted_at": h.created_at,
        }
        for h, b in rows
    ]

    # Send to Readwise
    async with ReadwiseService(api_token=token) as service:
        batch_result = await service.send_highlights(highlight_data)

    # Update synced highlights
    now = datetime.now(tz=UTC)
    for (highlight, _), sync_result in zip(rows, batch_result.results, strict=False):
        if sync_result.success:
            highlight.readwise_id = sync_result.readwise_id
            highlight.synced_at = now

    await highlight_repo.db.flush()

    return ReadwiseBatchSyncResponse(
        total=batch_result.total,
        synced=batch_result.synced,
        failed=batch_result.failed,
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
    highlight, book = await highlight_repo.get_with_book_or_404(highlight_id)

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
        await highlight_repo.db.flush()

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
    highlight_repo: HighlightRepository = Depends(get_highlight_repo),
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
    book = await book_repo.get_or_404(book_id)

    # Get unsynced highlights for this book (excluding notes)
    rows = await highlight_repo.list_unsynced(book_id=book_id)

    # Log if there are notes being excluded
    notes_count = await highlight_repo.count_unsynced_notes(book_id=book_id)
    if notes_count > 0:
        logger.info(
            "Skipping %d note(s) for book id=%d during sync - notes are not supported by Readwise",
            notes_count,
            book_id,
        )

    if not rows:
        return ReadwiseBatchSyncResponse(total=0, synced=0, failed=0)

    # Build highlight data for batch sync
    highlight_data = [
        {
            "text": h.text,
            "title": book.title,
            "author": book.author,
            "note": h.note,
            "page_number": h.page_number,
            "highlighted_at": h.created_at,
        }
        for h, _b in rows
    ]

    # Send to Readwise
    async with ReadwiseService(api_token=token) as service:
        batch_result = await service.send_highlights(highlight_data)

    # Update synced highlights
    now = datetime.now(tz=UTC)
    for (highlight, _), sync_result in zip(rows, batch_result.results, strict=False):
        if sync_result.success:
            highlight.readwise_id = sync_result.readwise_id
            highlight.synced_at = now

    await highlight_repo.db.flush()

    return ReadwiseBatchSyncResponse(
        total=batch_result.total,
        synced=batch_result.synced,
        failed=batch_result.failed,
    )
