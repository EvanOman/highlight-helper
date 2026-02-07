"""Highlight-related views (add, extract, create, edit, update, delete, list all)."""

from datetime import UTC

from fastapi import (
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.models.book import Book
from app.models.highlight import Highlight
from app.services.highlight_extractor import (
    HighlightExtractorService,
    get_highlight_extractor_service,
)
from app.services.settings import get_settings_service

from ._common import router, settings, templates


@router.get("/books/{book_id}/add-highlight", response_class=HTMLResponse)
async def add_highlight_page(
    request: Request,
    book_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Page for adding a new highlight to a book."""
    query = select(Book).where(Book.id == book_id)
    result = await db.execute(query)
    book = result.scalar_one_or_none()

    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    return templates.TemplateResponse(
        request,
        "add_highlight.html",
        {
            "book": book,
            "extracted_text": "",
            "full_text": "",
            "highlight_text": "",
            "highlight_start": 0,
            "highlight_end": 0,
            "confidence": "",
            "page_number": "",
        },
    )


@router.get("/books/{book_id}/add-note", response_class=HTMLResponse)
async def add_note_page(
    request: Request,
    book_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Page for adding a standalone note to a book."""
    query = select(Book).where(Book.id == book_id)
    result = await db.execute(query)
    book = result.scalar_one_or_none()

    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    return templates.TemplateResponse(
        request,
        "add_note.html",
        {"book": book},
    )


@router.post("/books/{book_id}/extract", response_class=HTMLResponse)
async def extract_highlight_form(
    request: Request,
    book_id: int,
    instructions: str = Form(...),
    image: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    extractor: HighlightExtractorService = Depends(get_highlight_extractor_service),
):
    """Extract highlight from uploaded image."""
    query = select(Book).where(Book.id == book_id)
    result = await db.execute(query)
    book = result.scalar_one_or_none()

    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    # Validate file type
    error_message = None
    extracted_text = ""
    full_text = ""
    highlight_text = ""
    highlight_start = 0
    highlight_end = 0
    confidence = ""
    page_number = ""

    if not image.content_type or not image.content_type.startswith("image/"):
        error_message = "Please upload an image file"
    else:
        image_bytes = await image.read()
        if len(image_bytes) > 20 * 1024 * 1024:
            error_message = "Image file too large (max 20MB)"
        else:
            try:
                result = await extractor.extract_highlight(
                    image_bytes=image_bytes,
                    filename=image.filename or "image.jpg",
                    instructions=instructions,
                    db=db,
                )
                extracted_text = result.highlight_text
                full_text = result.full_text
                highlight_text = result.highlight_text
                highlight_start = result.highlight_start
                highlight_end = result.highlight_end
                confidence = result.confidence
                page_number = result.page_number or ""
            except Exception as e:
                error_message = f"Error extracting text: {str(e)}"

    return templates.TemplateResponse(
        request,
        "add_highlight.html",
        {
            "book": book,
            "extracted_text": extracted_text,
            "full_text": full_text,
            "highlight_text": highlight_text,
            "highlight_start": highlight_start,
            "highlight_end": highlight_end,
            "confidence": confidence,
            "page_number": page_number,
            "instructions": instructions,
            "error_message": error_message,
        },
    )


@router.post("/books/{book_id}/highlights/create")
async def create_highlight_form(
    book_id: int,
    background_tasks: BackgroundTasks,
    text: str = Form(...),
    note: str = Form(""),
    page_number: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    """Create a new highlight from form submission."""
    # Verify book exists
    query = select(Book).where(Book.id == book_id)
    result = await db.execute(query)
    book = result.scalar_one_or_none()

    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    highlight = Highlight(
        book_id=book_id,
        text=text,
        note=note if note else None,
        page_number=page_number if page_number else None,
    )
    db.add(highlight)
    await db.flush()
    await db.refresh(highlight)

    # Schedule auto-sync to Readwise if enabled (check app settings)
    app_settings = await get_settings_service(db)
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

    return RedirectResponse(
        url=f"{settings.root_path}/books/{book_id}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.post("/books/{book_id}/notes/create")
async def create_note_form(
    book_id: int,
    page_number: str = Form(...),
    note: str = Form(...),
    text: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    """Create a new note for a book."""
    from app.models.highlight import AnnotationType

    query = select(Book).where(Book.id == book_id)
    result = await db.execute(query)
    book = result.scalar_one_or_none()

    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    # Create note (a highlight with type=NOTE)
    new_note = Highlight(
        book_id=book_id,
        text=text if text.strip() else None,
        note=note,
        page_number=page_number,
        type=AnnotationType.NOTE,
    )
    db.add(new_note)
    await db.flush()

    return RedirectResponse(
        url=f"{settings.root_path}/books/{book_id}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.post("/highlights/{highlight_id}/delete")
async def delete_highlight_form(
    highlight_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete a highlight."""
    query = select(Highlight).where(Highlight.id == highlight_id)
    result = await db.execute(query)
    highlight = result.scalar_one_or_none()

    if not highlight:
        raise HTTPException(status_code=404, detail="Highlight not found")

    book_id = highlight.book_id
    await db.delete(highlight)

    return RedirectResponse(
        url=f"{settings.root_path}/books/{book_id}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.get("/books/{book_id}/highlights/{highlight_id}/edit", response_class=HTMLResponse)
async def edit_highlight_page(
    request: Request,
    book_id: int,
    highlight_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Page for editing an existing highlight."""
    # Get the book
    book_query = select(Book).where(Book.id == book_id)
    book_result = await db.execute(book_query)
    book = book_result.scalar_one_or_none()

    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    # Get the highlight
    highlight_query = select(Highlight).where(
        Highlight.id == highlight_id, Highlight.book_id == book_id
    )
    highlight_result = await db.execute(highlight_query)
    highlight = highlight_result.scalar_one_or_none()

    if not highlight:
        raise HTTPException(status_code=404, detail="Highlight not found")

    # Check if Readwise is configured
    env_settings = get_settings()
    readwise_configured = bool(env_settings.readwise_api_token)

    return templates.TemplateResponse(
        request,
        "edit_highlight.html",
        {
            "book": book,
            "highlight": highlight,
            "readwise_configured": readwise_configured,
        },
    )


@router.post("/books/{book_id}/highlights/{highlight_id}/update")
async def update_highlight_form(
    book_id: int,
    highlight_id: int,
    text: str = Form(...),
    note: str = Form(""),
    page_number: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    """Update an existing highlight from form submission."""
    from datetime import datetime

    from app.services.readwise import ReadwiseService

    # Verify book exists
    book_query = select(Book).where(Book.id == book_id)
    book_result = await db.execute(book_query)
    book = book_result.scalar_one_or_none()

    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    # Get the highlight
    highlight_query = select(Highlight).where(
        Highlight.id == highlight_id, Highlight.book_id == book_id
    )
    highlight_result = await db.execute(highlight_query)
    highlight = highlight_result.scalar_one_or_none()

    if not highlight:
        raise HTTPException(status_code=404, detail="Highlight not found")

    # Update local fields
    highlight.text = text
    highlight.note = note if note else None
    highlight.page_number = page_number if page_number else None

    # If highlight was previously synced, try to update on Readwise
    if highlight.readwise_id:
        app_settings = get_settings()
        if app_settings.readwise_api_token:
            service = ReadwiseService(app_settings.readwise_api_token)
            try:
                result = await service.update_highlight(
                    readwise_id=highlight.readwise_id,
                    text=text,
                    note=note if note else None,
                    page_number=page_number if page_number else None,
                )
                if result.success:
                    highlight.synced_at = datetime.now(tz=UTC)
                else:
                    # Readwise update failed, mark as needing re-sync
                    highlight.synced_at = None
            except Exception:
                # On error, mark as needing re-sync
                highlight.synced_at = None
            finally:
                await service.close()
        else:
            # No token configured, mark as needing re-sync
            highlight.synced_at = None

    return RedirectResponse(
        url=f"{settings.root_path}/books/{book_id}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.get("/highlights", response_class=HTMLResponse)
async def all_highlights(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Page showing all highlights across all books."""
    query = select(Highlight, Book).join(Book).order_by(Highlight.created_at.desc())

    result = await db.execute(query)
    rows = result.all()

    highlights = [
        {
            "id": highlight.id,
            "text": highlight.text,
            "note": highlight.note,
            "page_number": highlight.page_number,
            "created_at": highlight.created_at,
            "synced_at": highlight.synced_at,
            "readwise_id": highlight.readwise_id,
            "book_id": book.id,
            "book_title": book.title,
            "book_author": book.author,
        }
        for highlight, book in rows
    ]

    return templates.TemplateResponse(
        request,
        "all_highlights.html",
        {"highlights": highlights},
    )
