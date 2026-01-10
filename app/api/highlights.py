"""Highlight API routes."""

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    ExtractHighlightResponse,
    HighlightCreate,
    HighlightResponse,
    HighlightUpdate,
    HighlightWithBookResponse,
)
from app.core.database import get_db
from app.models.book import Book
from app.models.highlight import Highlight
from app.services.highlight_extractor import (
    HighlightExtractorService,
    get_highlight_extractor_service,
)

router = APIRouter(prefix="/api/highlights", tags=["highlights"])


@router.get("/book/{book_id}", response_model=list[HighlightResponse])
async def list_highlights_for_book(
    book_id: int,
    db: AsyncSession = Depends(get_db),
) -> list[HighlightResponse]:
    """List all highlights for a specific book."""
    # Verify book exists
    book_query = select(Book).where(Book.id == book_id)
    book_result = await db.execute(book_query)
    if not book_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Book not found",
        )

    query = (
        select(Highlight).where(Highlight.book_id == book_id).order_by(Highlight.created_at.desc())
    )

    result = await db.execute(query)
    highlights = result.scalars().all()

    return [
        HighlightResponse(
            id=h.id,
            book_id=h.book_id,
            text=h.text,
            note=h.note,
            page_number=h.page_number,
            created_at=h.created_at,
            readwise_id=h.readwise_id,
            synced_at=h.synced_at,
        )
        for h in highlights
    ]


@router.get("", response_model=list[HighlightWithBookResponse])
async def list_all_highlights(
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
) -> list[HighlightWithBookResponse]:
    """List all highlights across all books."""
    query = (
        select(Highlight, Book)
        .join(Book)
        .order_by(Highlight.created_at.desc())
        .offset(skip)
        .limit(limit)
    )

    result = await db.execute(query)
    rows = result.all()

    return [
        HighlightWithBookResponse(
            id=highlight.id,
            book_id=highlight.book_id,
            text=highlight.text,
            note=highlight.note,
            page_number=highlight.page_number,
            created_at=highlight.created_at,
            readwise_id=highlight.readwise_id,
            synced_at=highlight.synced_at,
            book_title=book.title,
            book_author=book.author,
        )
        for highlight, book in rows
    ]


@router.post(
    "/book/{book_id}",
    response_model=HighlightResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_highlight(
    book_id: int,
    highlight_data: HighlightCreate,
    db: AsyncSession = Depends(get_db),
) -> HighlightResponse:
    """Create a new highlight for a book."""
    # Verify book exists
    book_query = select(Book).where(Book.id == book_id)
    book_result = await db.execute(book_query)
    if not book_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Book not found",
        )

    highlight = Highlight(
        book_id=book_id,
        text=highlight_data.text,
        note=highlight_data.note,
        page_number=highlight_data.page_number,
    )
    db.add(highlight)
    await db.flush()
    await db.refresh(highlight)

    return HighlightResponse(
        id=highlight.id,
        book_id=highlight.book_id,
        text=highlight.text,
        note=highlight.note,
        page_number=highlight.page_number,
        created_at=highlight.created_at,
        readwise_id=highlight.readwise_id,
        synced_at=highlight.synced_at,
    )


@router.post(
    "/book/{book_id}/extract",
    response_model=ExtractHighlightResponse,
)
async def extract_highlight_from_image(
    book_id: int,
    instructions: str = Form(...),
    image: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    extractor: HighlightExtractorService = Depends(get_highlight_extractor_service),
) -> ExtractHighlightResponse:
    """
    Extract highlighted text from an uploaded image.

    This endpoint uses OpenAI Vision to extract text from a book page image
    based on the provided instructions.
    """
    # Verify book exists
    book_query = select(Book).where(Book.id == book_id)
    book_result = await db.execute(book_query)
    if not book_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Book not found",
        )

    # Validate file type
    if not image.content_type or not image.content_type.startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be an image",
        )

    # Read image
    image_bytes = await image.read()

    if len(image_bytes) > 20 * 1024 * 1024:  # 20MB limit
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Image file too large (max 20MB)",
        )

    # Extract highlight
    result = await extractor.extract_highlight(
        image_bytes=image_bytes,
        filename=image.filename or "image.jpg",
        instructions=instructions,
    )

    return ExtractHighlightResponse(
        text=result.text,
        confidence=result.confidence,
        page_number=result.page_number,
    )


@router.get("/{highlight_id}", response_model=HighlightResponse)
async def get_highlight(
    highlight_id: int,
    db: AsyncSession = Depends(get_db),
) -> HighlightResponse:
    """Get a specific highlight by ID."""
    query = select(Highlight).where(Highlight.id == highlight_id)
    result = await db.execute(query)
    highlight = result.scalar_one_or_none()

    if not highlight:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Highlight not found",
        )

    return HighlightResponse(
        id=highlight.id,
        book_id=highlight.book_id,
        text=highlight.text,
        note=highlight.note,
        page_number=highlight.page_number,
        created_at=highlight.created_at,
        readwise_id=highlight.readwise_id,
        synced_at=highlight.synced_at,
    )


@router.patch("/{highlight_id}", response_model=HighlightResponse)
async def update_highlight(
    highlight_id: int,
    highlight_data: HighlightUpdate,
    db: AsyncSession = Depends(get_db),
) -> HighlightResponse:
    """Update a highlight."""
    query = select(Highlight).where(Highlight.id == highlight_id)
    result = await db.execute(query)
    highlight = result.scalar_one_or_none()

    if not highlight:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Highlight not found",
        )

    update_data = highlight_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(highlight, field, value)

    await db.flush()
    await db.refresh(highlight)

    return HighlightResponse(
        id=highlight.id,
        book_id=highlight.book_id,
        text=highlight.text,
        note=highlight.note,
        page_number=highlight.page_number,
        created_at=highlight.created_at,
        readwise_id=highlight.readwise_id,
        synced_at=highlight.synced_at,
    )


@router.delete("/{highlight_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_highlight(
    highlight_id: int,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a highlight."""
    query = select(Highlight).where(Highlight.id == highlight_id)
    result = await db.execute(query)
    highlight = result.scalar_one_or_none()

    if not highlight:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Highlight not found",
        )

    await db.delete(highlight)
