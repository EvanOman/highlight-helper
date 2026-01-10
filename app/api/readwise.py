"""Readwise integration API routes."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    ReadwiseBatchSyncResponse,
    ReadwiseStatusResponse,
    ReadwiseSyncResponse,
)
from app.core.database import get_db
from app.models.book import Book
from app.models.highlight import Highlight
from app.services.readwise import ReadwiseService, get_readwise_service

router = APIRouter(prefix="/api/readwise", tags=["readwise"])


@router.get("/status", response_model=ReadwiseStatusResponse)
async def get_readwise_status(
    readwise: ReadwiseService = Depends(get_readwise_service),
) -> ReadwiseStatusResponse:
    """Get Readwise integration status."""
    configured = readwise.is_configured

    token_valid = None
    if configured:
        token_valid = await readwise.validate_token()

    return ReadwiseStatusResponse(
        configured=configured,
        token_valid=token_valid,
    )


@router.post("/validate", response_model=ReadwiseStatusResponse)
async def validate_readwise_token(
    readwise: ReadwiseService = Depends(get_readwise_service),
) -> ReadwiseStatusResponse:
    """Validate the Readwise API token."""
    if not readwise.is_configured:
        return ReadwiseStatusResponse(configured=False, token_valid=None)

    token_valid = await readwise.validate_token()
    return ReadwiseStatusResponse(configured=True, token_valid=token_valid)


@router.post("/sync/all", response_model=ReadwiseBatchSyncResponse)
async def sync_all_highlights(
    db: AsyncSession = Depends(get_db),
    readwise: ReadwiseService = Depends(get_readwise_service),
) -> ReadwiseBatchSyncResponse:
    """Sync all unsynced highlights to Readwise."""
    if not readwise.is_configured:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Readwise API token not configured",
        )

    # Get all unsynced highlights with their books
    query = select(Highlight, Book).join(Book).where(Highlight.synced_at.is_(None))
    result = await db.execute(query)
    rows = result.all()

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
    batch_result = await readwise.send_highlights(highlight_data)

    # Update synced highlights
    now = datetime.now(tz=timezone.utc)
    for (highlight, _), sync_result in zip(rows, batch_result.results):
        if sync_result.success:
            highlight.readwise_id = sync_result.readwise_id
            highlight.synced_at = now

    await db.flush()

    return ReadwiseBatchSyncResponse(
        total=batch_result.total,
        synced=batch_result.synced,
        failed=batch_result.failed,
    )


@router.post("/sync/{highlight_id}", response_model=ReadwiseSyncResponse)
async def sync_highlight(
    highlight_id: int,
    db: AsyncSession = Depends(get_db),
    readwise: ReadwiseService = Depends(get_readwise_service),
) -> ReadwiseSyncResponse:
    """Sync a single highlight to Readwise."""
    if not readwise.is_configured:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Readwise API token not configured",
        )

    # Get highlight with book
    query = select(Highlight, Book).join(Book).where(Highlight.id == highlight_id)
    result = await db.execute(query)
    row = result.first()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Highlight not found",
        )

    highlight, book = row

    # Send to Readwise
    sync_result = await readwise.send_highlight(
        text=highlight.text,
        title=book.title,
        author=book.author,
        note=highlight.note,
        page_number=highlight.page_number,
        highlighted_at=highlight.created_at,
    )

    if sync_result.success:
        # Update highlight with sync info
        highlight.readwise_id = sync_result.readwise_id
        highlight.synced_at = datetime.now(tz=timezone.utc)
        await db.flush()

    return ReadwiseSyncResponse(
        success=sync_result.success,
        readwise_id=sync_result.readwise_id,
        error=sync_result.error,
    )


@router.post("/sync/book/{book_id}", response_model=ReadwiseBatchSyncResponse)
async def sync_book_highlights(
    book_id: int,
    db: AsyncSession = Depends(get_db),
    readwise: ReadwiseService = Depends(get_readwise_service),
) -> ReadwiseBatchSyncResponse:
    """Sync all unsynced highlights for a book to Readwise."""
    if not readwise.is_configured:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Readwise API token not configured",
        )

    # Verify book exists
    book_query = select(Book).where(Book.id == book_id)
    book_result = await db.execute(book_query)
    book = book_result.scalar_one_or_none()

    if not book:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Book not found",
        )

    # Get unsynced highlights for this book
    query = (
        select(Highlight).where(Highlight.book_id == book_id).where(Highlight.synced_at.is_(None))
    )
    result = await db.execute(query)
    highlights = result.scalars().all()

    if not highlights:
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
        for h in highlights
    ]

    # Send to Readwise
    batch_result = await readwise.send_highlights(highlight_data)

    # Update synced highlights
    now = datetime.now(tz=timezone.utc)
    for i, (highlight, sync_result) in enumerate(zip(highlights, batch_result.results)):
        if sync_result.success:
            highlight.readwise_id = sync_result.readwise_id
            highlight.synced_at = now

    await db.flush()

    return ReadwiseBatchSyncResponse(
        total=batch_result.total,
        synced=batch_result.synced,
        failed=batch_result.failed,
    )
