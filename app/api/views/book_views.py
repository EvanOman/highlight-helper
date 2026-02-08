"""Book-related views (add, detail, search, create, delete)."""

from fastapi import Depends, File, Form, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.repositories.book import BookRepository, get_book_repo
from app.repositories.highlight import HighlightRepository, get_highlight_repo
from app.services.book_lookup import BookLookupService, get_book_lookup_service
from app.services.isbn_extractor import (
    ISBNExtractorService,
    get_isbn_extractor_service,
)

from ._common import router, settings, templates


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
                error_message = f"Error extracting ISBN: {e!s}"

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
    book_repo: BookRepository = Depends(get_book_repo),
):
    """Create a new book from form submission."""
    book = await book_repo.create(
        title=title,
        author=author,
        isbn=isbn if isbn else None,
        cover_url=cover_url if cover_url else None,
    )

    return RedirectResponse(
        url=f"{settings.root_path}/books/{book.id}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.get("/books/{book_id}", response_class=HTMLResponse)
async def book_detail(
    request: Request,
    book_id: int,
    book_repo: BookRepository = Depends(get_book_repo),
    highlight_repo: HighlightRepository = Depends(get_highlight_repo),
):
    """Book detail page showing all highlights."""
    book = await book_repo.get_or_raise(book_id)
    highlights = await highlight_repo.list_for_book(book_id)

    # Build timeline data for highlights with page numbers
    timeline_items = []
    page_numbers = []

    for h in highlights:
        if h.page_number:
            try:
                # Handle page ranges like "42-43" by taking the first number
                page_num = int(h.page_number.split("-")[0].strip())
                page_numbers.append(page_num)
                preview_text = h.text or h.note or ""
                if len(preview_text) > 50:
                    preview_text = preview_text[:50] + "..."
                timeline_items.append(
                    {
                        "id": h.id,
                        "page_number": page_num,
                        "type": h.type.value if hasattr(h.type, "value") else str(h.type),
                        "preview": preview_text,
                    }
                )
            except (ValueError, AttributeError):
                # Skip highlights with non-numeric page numbers
                pass

    min_page = min(page_numbers) if page_numbers else 0
    max_page = max(page_numbers) if page_numbers else 0

    for item in timeline_items:
        if max_page > min_page:
            item["position"] = ((item["page_number"] - min_page) / (max_page - min_page)) * 100
        else:
            item["position"] = 50  # Center single item

    # Handle overlapping dots: group items on the same page and offset nearby items
    # Sort by page number for consistent positioning
    timeline_items.sort(key=lambda x: (x["page_number"], x["id"]))

    # Add vertical offset for items on same or nearby pages
    page_count: dict[int, int] = {}
    for item in timeline_items:
        page = item["page_number"]
        count = page_count.get(page, 0)
        item["offset_index"] = count
        page_count[page] = count + 1

    return templates.TemplateResponse(
        request,
        "book_detail.html",
        {
            "book": book,
            "highlights": highlights,
            "timeline_items": timeline_items,
            "timeline_min_page": min_page,
            "timeline_max_page": max_page,
        },
    )


@router.post("/books/{book_id}/delete")
async def delete_book_form(
    book_id: int,
    book_repo: BookRepository = Depends(get_book_repo),
):
    """Delete a book."""
    book = await book_repo.get_or_raise(book_id)
    await book_repo.delete(book)

    return RedirectResponse(url=f"{settings.root_path}/", status_code=status.HTTP_303_SEE_OTHER)
