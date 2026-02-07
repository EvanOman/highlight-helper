"""Highlight API routes."""

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    ExtractHighlightResponse,
    HighlightCreate,
    HighlightResponse,
    HighlightUpdate,
    HighlightWithBookResponse,
    NoteCreate,
)
from app.core.database import get_db
from app.models.highlight import AnnotationType
from app.repositories.book import BookRepository, get_book_repo
from app.repositories.highlight import HighlightRepository, get_highlight_repo
from app.services.highlight_extractor import (
    HighlightExtractorService,
    get_highlight_extractor_service,
)
from app.services.settings import get_settings_service

router = APIRouter(prefix="/api/highlights", tags=["highlights"])


@router.get("/book/{book_id}", response_model=list[HighlightResponse])
async def list_highlights_for_book(
    book_id: int,
    book_repo: BookRepository = Depends(get_book_repo),
    highlight_repo: HighlightRepository = Depends(get_highlight_repo),
) -> list[HighlightResponse]:
    """List all highlights for a specific book."""
    await book_repo.get_or_404(book_id)
    highlights = await highlight_repo.list_for_book(book_id)

    return [
        HighlightResponse(
            id=h.id,
            book_id=h.book_id,
            text=h.text,
            note=h.note,
            page_number=h.page_number,
            created_at=h.created_at,
            type=h.type.value,
            readwise_id=h.readwise_id,
            synced_at=h.synced_at,
        )
        for h in highlights
    ]


@router.get("", response_model=list[HighlightWithBookResponse])
async def list_all_highlights(
    skip: int = 0,
    limit: int = 50,
    highlight_repo: HighlightRepository = Depends(get_highlight_repo),
) -> list[HighlightWithBookResponse]:
    """List all highlights across all books."""
    rows = await highlight_repo.list_all_with_books(skip=skip, limit=limit)

    return [
        HighlightWithBookResponse(
            id=highlight.id,
            book_id=highlight.book_id,
            text=highlight.text,
            note=highlight.note,
            page_number=highlight.page_number,
            created_at=highlight.created_at,
            type=highlight.type.value,
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
    background_tasks: BackgroundTasks,
    book_repo: BookRepository = Depends(get_book_repo),
    highlight_repo: HighlightRepository = Depends(get_highlight_repo),
) -> HighlightResponse:
    """Create a new highlight for a book."""
    book = await book_repo.get_or_404(book_id)

    highlight = await highlight_repo.create(
        book_id=book_id,
        text=highlight_data.text,
        note=highlight_data.note,
        page_number=highlight_data.page_number,
    )

    # Schedule auto-sync to Readwise if enabled in app settings
    app_settings = await get_settings_service(highlight_repo.db)
    auto_sync = await app_settings.get_readwise_auto_sync()
    token = await app_settings.get_readwise_token()
    if auto_sync and token:
        from app.services.readwise import sync_highlight_background_with_token

        # ty type checker has a ParamSpec bug: even str() casts are reported as str|None
        # See: book.author is Mapped[str] (non-nullable), function accepts str|None
        background_tasks.add_task(
            sync_highlight_background_with_token,
            highlight_id=highlight.id,
            book_title=book.title,
            book_author=book.author,  # type: ignore[arg-type]
            text=highlight.text,
            note=highlight.note,
            page_number=highlight.page_number,
            created_at=highlight.created_at,
            api_token=token,
        )

    return HighlightResponse(
        id=highlight.id,
        book_id=highlight.book_id,
        text=highlight.text,
        note=highlight.note,
        page_number=highlight.page_number,
        created_at=highlight.created_at,
        type=highlight.type.value,
        readwise_id=highlight.readwise_id,
        synced_at=highlight.synced_at,
    )


@router.post(
    "/book/{book_id}/note",
    response_model=HighlightResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_note(
    book_id: int,
    note_data: NoteCreate,
    book_repo: BookRepository = Depends(get_book_repo),
    highlight_repo: HighlightRepository = Depends(get_highlight_repo),
) -> HighlightResponse:
    """Create a standalone note for a book."""
    await book_repo.get_or_404(book_id)

    note = await highlight_repo.create(
        book_id=book_id,
        text=note_data.text,
        note=note_data.note,
        page_number=note_data.page_number,
        type=AnnotationType.NOTE,
    )

    return HighlightResponse(
        id=note.id,
        book_id=note.book_id,
        text=note.text,
        note=note.note,
        page_number=note.page_number,
        created_at=note.created_at,
        type=note.type.value,
        readwise_id=note.readwise_id,
        synced_at=note.synced_at,
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
    book_repo: BookRepository = Depends(get_book_repo),
    extractor: HighlightExtractorService = Depends(get_highlight_extractor_service),
) -> ExtractHighlightResponse:
    """
    Extract highlighted text from an uploaded image.

    This endpoint uses OpenAI Vision to extract text from a book page image
    based on the provided instructions.
    """
    await book_repo.get_or_404(book_id)

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

    # Extract highlight (pass db for usage tracking)
    result = await extractor.extract_highlight(
        image_bytes=image_bytes,
        filename=image.filename or "image.jpg",
        instructions=instructions,
        db=db,
    )

    return ExtractHighlightResponse(
        full_text=result.full_text,
        highlight_text=result.highlight_text,
        confidence=result.confidence,
        page_number=result.page_number,
        highlight_start=result.highlight_start,
        highlight_end=result.highlight_end,
    )


@router.get("/{highlight_id}", response_model=HighlightResponse)
async def get_highlight(
    highlight_id: int,
    highlight_repo: HighlightRepository = Depends(get_highlight_repo),
) -> HighlightResponse:
    """Get a specific highlight by ID."""
    highlight = await highlight_repo.get_or_404(highlight_id)

    return HighlightResponse(
        id=highlight.id,
        book_id=highlight.book_id,
        text=highlight.text,
        note=highlight.note,
        page_number=highlight.page_number,
        created_at=highlight.created_at,
        type=highlight.type.value,
        readwise_id=highlight.readwise_id,
        synced_at=highlight.synced_at,
    )


@router.patch("/{highlight_id}", response_model=HighlightResponse)
async def update_highlight(
    highlight_id: int,
    highlight_data: HighlightUpdate,
    highlight_repo: HighlightRepository = Depends(get_highlight_repo),
) -> HighlightResponse:
    """Update a highlight."""
    highlight = await highlight_repo.get_or_404(highlight_id)

    update_data = highlight_data.model_dump(exclude_unset=True)
    highlight = await highlight_repo.update(highlight, **update_data)

    return HighlightResponse(
        id=highlight.id,
        book_id=highlight.book_id,
        text=highlight.text,
        note=highlight.note,
        page_number=highlight.page_number,
        created_at=highlight.created_at,
        type=highlight.type.value,
        readwise_id=highlight.readwise_id,
        synced_at=highlight.synced_at,
    )


@router.delete("/{highlight_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_highlight(
    highlight_id: int,
    highlight_repo: HighlightRepository = Depends(get_highlight_repo),
) -> None:
    """Delete a highlight."""
    highlight = await highlight_repo.get_or_404(highlight_id)
    await highlight_repo.delete(highlight)
