"""Highlight-related views (add, extract, create, edit, update, delete, list all)."""

from datetime import UTC, datetime

from fastapi import (
    Depends,
    File,
    Form,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.highlight import AnnotationType
from app.repositories.book import BookRepository, get_book_repo
from app.repositories.highlight import HighlightRepository, get_highlight_repo
from app.services.highlight_extractor import (
    HighlightExtractorService,
    get_highlight_extractor_service,
)
from app.services.readwise import ReadwiseService, schedule_auto_sync
from app.services.settings import get_settings_service

from ._common import router, settings, templates


@router.get("/books/{book_id}/add-highlight", response_class=HTMLResponse)
async def add_highlight_page(
    request: Request,
    book_id: int,
    book_repo: BookRepository = Depends(get_book_repo),
):
    """Page for adding a new highlight to a book."""
    book = await book_repo.get_or_raise(book_id)

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
    book_repo: BookRepository = Depends(get_book_repo),
):
    """Page for adding a standalone note to a book."""
    book = await book_repo.get_or_raise(book_id)

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
    book_repo: BookRepository = Depends(get_book_repo),
    extractor: HighlightExtractorService = Depends(get_highlight_extractor_service),
):
    """Extract highlight from uploaded image."""
    book = await book_repo.get_or_raise(book_id)

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
                error_message = f"Error extracting text: {e!s}"

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
    text: str = Form(...),
    note: str = Form(""),
    page_number: str = Form(""),
    db: AsyncSession = Depends(get_db),
    book_repo: BookRepository = Depends(get_book_repo),
    highlight_repo: HighlightRepository = Depends(get_highlight_repo),
):
    """Create a new highlight from form submission."""
    book = await book_repo.get_or_raise(book_id)

    highlight = await highlight_repo.create(
        book_id=book_id,
        text=text,
        note=note if note else None,
        page_number=page_number if page_number else None,
    )

    # Schedule auto-sync to Readwise if enabled (check app settings)
    await schedule_auto_sync(
        db,
        highlight,
        book_title=book.title,
        book_author=book.author,
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
    book_repo: BookRepository = Depends(get_book_repo),
    highlight_repo: HighlightRepository = Depends(get_highlight_repo),
):
    """Create a new note for a book."""
    await book_repo.get_or_raise(book_id)

    await highlight_repo.create(
        book_id=book_id,
        text=text if text.strip() else None,
        note=note,
        page_number=page_number,
        type=AnnotationType.NOTE,
    )

    return RedirectResponse(
        url=f"{settings.root_path}/books/{book_id}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.post("/highlights/{highlight_id}/delete")
async def delete_highlight_form(
    highlight_id: int,
    highlight_repo: HighlightRepository = Depends(get_highlight_repo),
):
    """Delete a highlight."""
    highlight = await highlight_repo.get_or_raise(highlight_id)
    book_id = highlight.book_id
    await highlight_repo.delete(highlight)

    return RedirectResponse(
        url=f"{settings.root_path}/books/{book_id}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.get("/books/{book_id}/highlights/{highlight_id}/edit", response_class=HTMLResponse)
async def edit_highlight_page(
    request: Request,
    book_id: int,
    highlight_id: int,
    db: AsyncSession = Depends(get_db),
    highlight_repo: HighlightRepository = Depends(get_highlight_repo),
):
    """Page for editing an existing highlight."""
    highlight, book = await highlight_repo.get_with_book_or_raise(highlight_id, book_id)

    # Check if Readwise is configured in app settings
    app_settings = await get_settings_service(db)
    readwise_configured = bool(await app_settings.get_readwise_token())

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
    highlight_repo: HighlightRepository = Depends(get_highlight_repo),
):
    """Update an existing highlight from form submission."""
    highlight, _book = await highlight_repo.get_with_book_or_raise(highlight_id, book_id)

    # Update local fields
    highlight.text = text
    highlight.note = note if note else None
    highlight.page_number = page_number if page_number else None

    # If highlight was previously synced, try to update on Readwise
    if highlight.readwise_id:
        settings_service = await get_settings_service(db)
        token = await settings_service.get_readwise_token()
        if token:
            try:
                async with ReadwiseService(token) as service:
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
        else:
            # No token configured, mark as needing re-sync
            highlight.synced_at = None

    return RedirectResponse(
        url=f"{settings.root_path}/books/{book_id}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.get("/highlights", response_class=HTMLResponse)
async def all_highlights(
    request: Request,
    page: int = Query(1, ge=1),
    highlight_repo: HighlightRepository = Depends(get_highlight_repo),
):
    """Page showing all highlights across all books."""
    per_page = 20
    total = await highlight_repo.get_total_count()
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, total_pages)

    rows = await highlight_repo.list_all_with_books(skip=(page - 1) * per_page, limit=per_page)

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
        {
            "highlights": highlights,
            "current_page": page,
            "total_pages": total_pages,
            "total_highlights": total,
            "page_path": "/highlights",
        },
    )
