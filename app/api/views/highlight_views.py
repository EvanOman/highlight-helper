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
    ExtractedHighlight,
    HighlightExtractorService,
    get_highlight_extractor_service,
)
from app.services.image_stash import ImageStash, get_image_stash
from app.services.readwise import ReadwiseService, schedule_auto_sync
from app.services.settings import get_settings_service
from app.services.text_matching import MatchStatus
from app.services.upload_archive import (
    UploadArchiveService,
    get_upload_archive_service,
)

from ._common import router, settings, templates

EXTRACTION_FAILED_MESSAGE = (
    "Couldn't read the page. The photo may be blurry, dark, or not a book page — "
    "try again with a clearer photo, or enter the highlight manually below."
)
IMAGE_EXPIRED_MESSAGE = "That photo is no longer available on the server — please upload it again."


def _ui_match_status(result: ExtractedHighlight) -> str:
    """Translate the matcher's native ``match_status`` into the editor's
    vocabulary.

    The span locator (``text_matching.locate_highlight``) reports one of
    ``exact | normalized | fuzzy | not_found``. The editor only needs to know
    whether a passage was located at all: ``not_found`` becomes ``"failed"``
    (no pre-selection, manual selection required); every located status is
    passed through unchanged so the confidence rule below can grade it.
    """
    status = result.match_status or MatchStatus.NOT_FOUND.value
    return "failed" if status == MatchStatus.NOT_FOUND.value else status


def _display_confidence(llm_confidence: str, match_status: str) -> str:
    """Combine LLM self-rated confidence with span-match quality.

    A failed match shows no badge at all (the failed-match notice replaces it);
    any non-exact match — including a normalized or fuzzy one — caps the badge
    at "medium" (yellow), since only a verbatim exact hit earns green.
    """
    if match_status == "failed":
        return ""
    if match_status != "exact" and llm_confidence == "high":
        return "medium"
    return llm_confidence


def _phase1_context(book, instructions: str, error_message: str | None) -> dict:
    """Template context for the upload form (Phase 1), with an optional error."""
    return {
        "book": book,
        "extracted_text": "",
        "full_text": "",
        "highlight_text": "",
        "highlight_start": 0,
        "highlight_end": 0,
        "confidence": "",
        "page_number": "",
        "match_status": "",
        "image_token": "",
        "instructions": instructions,
        "error_message": error_message,
    }


async def _run_extraction(
    request: Request,
    book,
    instructions: str,
    image_bytes: bytes,
    filename: str,
    image_token: str,
    db,
    extractor: HighlightExtractorService,
    archive: UploadArchiveService,
):
    """Run extraction and render the honest result (Phase 2 or explicit failure)."""
    try:
        result = await extractor.extract_highlight(
            image_bytes=image_bytes,
            filename=filename,
            instructions=instructions,
            db=db,
        )
    except Exception as e:
        archive.archive_extraction(
            image_bytes=image_bytes,
            filename=filename,
            book_id=book.id,
            instructions=instructions,
            error=str(e),
        )
        return templates.TemplateResponse(
            request,
            "add_highlight.html",
            _phase1_context(book, instructions, f"Error extracting text: {e!s}"),
        )

    # Retain the upload as an eval-corpus candidate (best-effort, never raises)
    # — successes and failures both get mined.
    archive.archive_extraction(
        image_bytes=image_bytes,
        filename=filename,
        book_id=book.id,
        instructions=instructions,
        result=result,
        error=result.error,
    )

    if not result.full_text.strip():
        # The service returns an empty result on any failure — surface it
        # instead of silently re-rendering the upload form.
        return templates.TemplateResponse(
            request,
            "add_highlight.html",
            _phase1_context(book, instructions, EXTRACTION_FAILED_MESSAGE),
        )

    match_status = _ui_match_status(result)
    return templates.TemplateResponse(
        request,
        "add_highlight.html",
        {
            "book": book,
            "extracted_text": result.highlight_text,
            "full_text": result.full_text,
            "highlight_text": result.highlight_text if match_status != "failed" else "",
            "highlight_start": result.highlight_start,
            "highlight_end": result.highlight_end,
            "confidence": _display_confidence(result.confidence, match_status),
            "page_number": result.page_number or "",
            "match_status": match_status,
            "image_token": image_token,
            "instructions": instructions,
            "error_message": None,
        },
    )


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
        _phase1_context(book, "", None),
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
    stash: ImageStash = Depends(get_image_stash),
    archive: UploadArchiveService = Depends(get_upload_archive_service),
):
    """Extract highlight from uploaded image."""
    book = await book_repo.get_or_raise(book_id)

    if not image.content_type or not image.content_type.startswith("image/"):
        return templates.TemplateResponse(
            request,
            "add_highlight.html",
            _phase1_context(book, instructions, "Please upload an image file"),
        )

    image_bytes = await image.read()
    if len(image_bytes) > 20 * 1024 * 1024:
        return templates.TemplateResponse(
            request,
            "add_highlight.html",
            _phase1_context(book, instructions, "Image file too large (max 20MB)"),
        )

    # Stash the photo so "Re-extract" can re-run without a re-upload.
    image_token = stash.put(image_bytes)

    return await _run_extraction(
        request,
        book,
        instructions,
        image_bytes,
        image.filename or "image.jpg",
        image_token,
        db,
        extractor,
        archive,
    )


@router.post("/books/{book_id}/re-extract", response_class=HTMLResponse)
async def re_extract_highlight_form(
    request: Request,
    book_id: int,
    instructions: str = Form(...),
    image_token: str = Form(...),
    db: AsyncSession = Depends(get_db),
    book_repo: BookRepository = Depends(get_book_repo),
    extractor: HighlightExtractorService = Depends(get_highlight_extractor_service),
    stash: ImageStash = Depends(get_image_stash),
    archive: UploadArchiveService = Depends(get_upload_archive_service),
):
    """Re-run extraction against the stashed photo with (possibly edited) instructions."""
    book = await book_repo.get_or_raise(book_id)

    image_bytes = stash.get(image_token)
    if image_bytes is None:
        return templates.TemplateResponse(
            request,
            "add_highlight.html",
            _phase1_context(book, instructions, IMAGE_EXPIRED_MESSAGE),
        )

    return await _run_extraction(
        request,
        book,
        instructions,
        image_bytes,
        "re-extract.jpg",
        image_token,
        db,
        extractor,
        archive,
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
