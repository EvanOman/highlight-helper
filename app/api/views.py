"""Web views for HTML pages."""

from fastapi import (
    APIRouter,
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
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.models.book import Book
from app.models.highlight import Highlight
from app.services.book_lookup import BookLookupService, get_book_lookup_service
from app.services.highlight_extractor import (
    HighlightExtractorService,
    get_highlight_extractor_service,
)
from app.services.isbn_extractor import (
    ISBNExtractorService,
    get_isbn_extractor_service,
)
from app.services.settings import get_settings_service

router = APIRouter(tags=["views"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def home(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Home page showing all books."""
    # Get books with highlight counts
    highlight_count_subq = (
        select(Highlight.book_id, func.count(Highlight.id).label("count"))
        .group_by(Highlight.book_id)
        .subquery()
    )

    query = (
        select(Book, func.coalesce(highlight_count_subq.c.count, 0).label("highlight_count"))
        .outerjoin(highlight_count_subq, Book.id == highlight_count_subq.c.book_id)
        .order_by(Book.created_at.desc())
    )

    result = await db.execute(query)
    rows = result.all()

    books = [
        {
            "id": book.id,
            "title": book.title,
            "author": book.author,
            "cover_url": book.cover_url,
            "highlight_count": highlight_count,
        }
        for book, highlight_count in rows
    ]

    return templates.TemplateResponse(
        request,
        "home.html",
        {"books": books},
    )


@router.get("/books/add", response_class=HTMLResponse)
async def add_book_page(request: Request):
    """Page for adding a new book."""
    return templates.TemplateResponse(
        request,
        "add_book.html",
        {"search_results": None, "query": ""},
    )


@router.post("/books/search", response_class=HTMLResponse)
async def search_books_page(
    request: Request,
    query: str = Form(""),
    book_lookup: BookLookupService = Depends(get_book_lookup_service),
):
    """Search for books and display results."""
    search_results = []
    if query and len(query) >= 2:
        results = await book_lookup.search_books(query)
        search_results = [
            {
                "title": r.title,
                "author": r.author,
                "isbn": r.isbn,
                "cover_url": r.cover_url,
            }
            for r in results
        ]

    return templates.TemplateResponse(
        request,
        "add_book.html",
        {"search_results": search_results, "query": query},
    )


@router.post("/books/scan-isbn", response_class=HTMLResponse)
async def scan_isbn_page(
    request: Request,
    image: UploadFile = File(...),
    isbn_extractor: ISBNExtractorService = Depends(get_isbn_extractor_service),
    book_lookup: BookLookupService = Depends(get_book_lookup_service),
):
    """Extract ISBN from image and search for the book."""
    error_message = None
    search_results = []
    extracted_isbn = ""
    confidence = ""

    if not image.content_type or not image.content_type.startswith("image/"):
        error_message = "Please upload an image file"
    else:
        image_bytes = await image.read()
        if len(image_bytes) > 20 * 1024 * 1024:
            error_message = "Image file too large (max 20MB)"
        else:
            try:
                result = await isbn_extractor.extract_isbn(
                    image_bytes=image_bytes,
                    filename=image.filename or "image.jpg",
                )
                extracted_isbn = result.isbn
                confidence = result.confidence

                # If we got an ISBN, search for the book
                if extracted_isbn:
                    book_result = await book_lookup.search_by_isbn(extracted_isbn)
                    if book_result:
                        search_results = [
                            {
                                "title": book_result.title,
                                "author": book_result.author,
                                "isbn": book_result.isbn,
                                "cover_url": book_result.cover_url,
                            }
                        ]
                    else:
                        # Try searching with the ISBN as query
                        results = await book_lookup.search_books(extracted_isbn)
                        search_results = [
                            {
                                "title": r.title,
                                "author": r.author,
                                "isbn": r.isbn,
                                "cover_url": r.cover_url,
                            }
                            for r in results
                        ]
                        if not search_results:
                            error_message = (
                                f"Found ISBN {extracted_isbn} but couldn't find book info. "
                                "Try searching manually."
                            )
                else:
                    error_message = (
                        "Could not extract ISBN from image. Try a clearer photo of the barcode."
                    )
            except Exception as e:
                error_message = f"Error extracting ISBN: {str(e)}"

    return templates.TemplateResponse(
        request,
        "add_book.html",
        {
            "search_results": search_results if search_results else None,
            "query": extracted_isbn,
            "extracted_isbn": extracted_isbn,
            "isbn_confidence": confidence,
            "error_message": error_message,
        },
    )


@router.post("/books/create")
async def create_book_form(
    title: str = Form(...),
    author: str = Form(...),
    isbn: str = Form(""),
    cover_url: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    """Create a new book from form submission."""
    book = Book(
        title=title,
        author=author,
        isbn=isbn if isbn else None,
        cover_url=cover_url if cover_url else None,
    )
    db.add(book)
    await db.flush()
    await db.refresh(book)

    return RedirectResponse(url=f"/books/{book.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/books/{book_id}", response_class=HTMLResponse)
async def book_detail(
    request: Request,
    book_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Book detail page showing all highlights."""
    query = select(Book).where(Book.id == book_id)
    result = await db.execute(query)
    book = result.scalar_one_or_none()

    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    # Get highlights
    highlights_query = (
        select(Highlight).where(Highlight.book_id == book_id).order_by(Highlight.created_at.desc())
    )
    highlights_result = await db.execute(highlights_query)
    highlights = highlights_result.scalars().all()

    return templates.TemplateResponse(
        request,
        "book_detail.html",
        {
            "book": book,
            "highlights": highlights,
        },
    )


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
            "confidence": "",
            "page_number": "",
        },
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
                )
                extracted_text = result.text
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

        background_tasks.add_task(
            sync_highlight_background_with_token,
            highlight_id=highlight.id,
            book_title=book.title,
            book_author=book.author,
            text=highlight.text,
            note=highlight.note,
            page_number=highlight.page_number,
            created_at=highlight.created_at,
            api_token=token,
        )

    return RedirectResponse(url=f"/books/{book_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/books/{book_id}/delete")
async def delete_book_form(
    book_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete a book."""
    query = select(Book).where(Book.id == book_id)
    result = await db.execute(query)
    book = result.scalar_one_or_none()

    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    await db.delete(book)

    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


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

    return RedirectResponse(url=f"/books/{book_id}", status_code=status.HTTP_303_SEE_OTHER)


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
    settings = get_settings()
    readwise_configured = bool(settings.readwise_api_token)

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
    from datetime import datetime, timezone

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
        settings = get_settings()
        if settings.readwise_api_token:
            service = ReadwiseService(settings.readwise_api_token)
            try:
                result = await service.update_highlight(
                    readwise_id=highlight.readwise_id,
                    text=text,
                    note=note if note else None,
                    page_number=page_number if page_number else None,
                )
                if result.success:
                    highlight.synced_at = datetime.now(tz=timezone.utc)
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

    return RedirectResponse(url=f"/books/{book_id}", status_code=status.HTTP_303_SEE_OTHER)


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


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Settings page for configuring the application."""
    settings = await get_settings_service(db)

    token = await settings.get_readwise_token()
    auto_sync = await settings.get_readwise_auto_sync()

    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "token_configured": bool(token),
            "auto_sync": auto_sync,
        },
    )
