"""Book lookup service using Google Books API with Open Library fallback."""

import logging
from dataclasses import dataclass

import httpx

from app.core.telemetry import add_span_attributes, create_span, set_span_status

logger = logging.getLogger(__name__)


@dataclass
class BookInfo:
    """Information about a book from Google Books API."""

    title: str
    author: str
    isbn: str | None = None
    cover_url: str | None = None
    description: str | None = None


class BookLookupService:
    """Service for looking up books using Google Books API with Open Library fallback."""

    GOOGLE_BOOKS_URL = "https://www.googleapis.com/books/v1/volumes"
    OPEN_LIBRARY_ISBN_URL = "https://openlibrary.org/isbn/{isbn}.json"
    OPEN_LIBRARY_SEARCH_URL = "https://openlibrary.org/search.json"
    OPEN_LIBRARY_COVERS_URL = "https://covers.openlibrary.org/b/isbn/{isbn}-M.jpg"

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _parse_google_volume(self, item: dict, override_isbn: str | None = None) -> BookInfo:
        """Parse a Google Books volume into BookInfo."""
        volume_info = item.get("volumeInfo", {})

        # Get ISBN
        isbn = override_isbn
        if not isbn:
            for identifier in volume_info.get("industryIdentifiers", []):
                if identifier.get("type") in ("ISBN_13", "ISBN_10"):
                    isbn = identifier.get("identifier")
                    break

        # Get cover image URL (prefer larger thumbnail)
        image_links = volume_info.get("imageLinks", {})
        cover_url = image_links.get("thumbnail") or image_links.get("smallThumbnail")
        if cover_url and cover_url.startswith("http://"):
            cover_url = cover_url.replace("http://", "https://")

        # Get authors (join multiple authors)
        authors = volume_info.get("authors", ["Unknown Author"])
        author = ", ".join(authors)

        return BookInfo(
            title=volume_info.get("title", "Unknown Title"),
            author=author,
            isbn=isbn,
            cover_url=cover_url,
            description=volume_info.get("description"),
        )

    async def _search_open_library_by_isbn(self, isbn: str) -> BookInfo | None:
        """Fallback: search Open Library by ISBN."""
        with create_span(
            "open_library_isbn_lookup",
            {"book_lookup.isbn": isbn, "book_lookup.source": "open_library"},
        ) as span:
            try:
                client = await self._get_client()
                url = self.OPEN_LIBRARY_ISBN_URL.format(isbn=isbn)
                response = await client.get(url)

                if response.status_code == 404:
                    add_span_attributes(book_lookup_found=False)
                    set_span_status(True)
                    return None

                response.raise_for_status()
                data = response.json()

                title = data.get("title", "Unknown Title")

                # Get authors - try edition first, then fall back to works endpoint
                author_keys = data.get("authors", [])
                if not author_keys:
                    # Edition lacks authors; check the linked work
                    works = data.get("works", [])
                    if works:
                        work_key = works[0].get("key", "")
                        if work_key:
                            try:
                                work_resp = await client.get(
                                    f"https://openlibrary.org{work_key}.json"
                                )
                                if work_resp.status_code == 200:
                                    work_data = work_resp.json()
                                    for wa in work_data.get("authors", []):
                                        ak = wa.get("author", {})
                                        if ak.get("key"):
                                            author_keys.append(ak)
                            except Exception:
                                pass

                authors = []
                for ak in author_keys[:3]:  # Limit to 3 authors
                    key = ak.get("key", "")
                    if key:
                        try:
                            author_resp = await client.get(f"https://openlibrary.org{key}.json")
                            if author_resp.status_code == 200:
                                author_data = author_resp.json()
                                authors.append(author_data.get("name", "Unknown Author"))
                        except Exception:
                            pass
                author = ", ".join(authors) if authors else "Unknown Author"

                cover_url = self.OPEN_LIBRARY_COVERS_URL.format(isbn=isbn)

                description = None
                if "description" in data:
                    desc = data["description"]
                    description = desc if isinstance(desc, str) else desc.get("value", "")

                book = BookInfo(
                    title=title,
                    author=author,
                    isbn=isbn,
                    cover_url=cover_url,
                    description=description,
                )

                add_span_attributes(
                    book_lookup_found=True,
                    book_lookup_title=book.title,
                    book_lookup_source="open_library",
                )
                set_span_status(True)
                logger.info(f"Open Library ISBN lookup found: {book.title}")
                return book

            except httpx.HTTPStatusError as e:
                logger.warning(f"Open Library ISBN lookup failed: {e}")
                span.record_exception(e)
                set_span_status(False, str(e))
                return None
            except Exception as e:
                logger.warning(f"Open Library ISBN lookup error: {e}")
                span.record_exception(e)
                set_span_status(False, str(e))
                return None

    async def _search_open_library(self, query: str, max_results: int = 10) -> list[BookInfo]:
        """Fallback: search Open Library by text query."""
        with create_span(
            "open_library_search",
            {"book_search.query": query, "book_search.source": "open_library"},
        ) as span:
            try:
                client = await self._get_client()
                params = {
                    "q": query,
                    "limit": min(max_results, 40),
                    "fields": "title,author_name,isbn,cover_i,first_sentence",
                }
                response = await client.get(self.OPEN_LIBRARY_SEARCH_URL, params=params)
                response.raise_for_status()
                data = response.json()

                books: list[BookInfo] = []
                for doc in data.get("docs", []):
                    isbn = None
                    isbns = doc.get("isbn", [])
                    # Prefer ISBN-13
                    for i in isbns:
                        if len(i) == 13:
                            isbn = i
                            break
                    if not isbn and isbns:
                        isbn = isbns[0]

                    cover_url = None
                    if isbn:
                        cover_url = self.OPEN_LIBRARY_COVERS_URL.format(isbn=isbn)
                    elif doc.get("cover_i"):
                        cover_url = f"https://covers.openlibrary.org/b/id/{doc['cover_i']}-M.jpg"

                    authors = doc.get("author_name", ["Unknown Author"])

                    first_sentence = doc.get("first_sentence", [])
                    description = first_sentence[0] if first_sentence else None

                    books.append(
                        BookInfo(
                            title=doc.get("title", "Unknown Title"),
                            author=", ".join(authors),
                            isbn=isbn,
                            cover_url=cover_url,
                            description=description,
                        )
                    )

                add_span_attributes(
                    book_search_results_count=len(books),
                    book_search_source="open_library",
                )
                set_span_status(True)
                logger.info(f"Open Library search found {len(books)} results for '{query}'")
                return books

            except Exception as e:
                logger.warning(f"Open Library search failed: {e}")
                span.record_exception(e)
                set_span_status(False, str(e))
                return []

    async def search_books(self, query: str, max_results: int = 10) -> list[BookInfo]:
        """
        Search for books by title, author, or ISBN.
        Falls back to Open Library if Google Books fails.

        Args:
            query: Search query (title, author, or ISBN)
            max_results: Maximum number of results to return

        Returns:
            List of BookInfo objects
        """
        with create_span(
            "book_search",
            {
                "book_search.query": query,
                "book_search.max_results": max_results,
            },
        ) as span:
            # Try Google Books first
            try:
                client = await self._get_client()
                params = {
                    "q": query,
                    "maxResults": min(max_results, 40),
                    "printType": "books",
                }
                response = await client.get(self.GOOGLE_BOOKS_URL, params=params)
                response.raise_for_status()

                data = response.json()
                books = [self._parse_google_volume(item) for item in data.get("items", [])]

                add_span_attributes(
                    book_search_results_count=len(books),
                    book_search_source="google_books",
                )
                set_span_status(True)
                return books

            except httpx.HTTPStatusError as e:
                logger.warning(
                    f"Google Books search failed ({e.response.status_code}): {e}. "
                    "Falling back to Open Library."
                )
                span.record_exception(e)
                add_span_attributes(
                    book_search_google_error=str(e),
                    book_search_google_status=e.response.status_code,
                    book_search_fallback="open_library",
                )

            except Exception as e:
                logger.warning(f"Google Books search error: {e}. Falling back to Open Library.")
                span.record_exception(e)
                add_span_attributes(
                    book_search_google_error=str(e),
                    book_search_fallback="open_library",
                )

            # Fallback to Open Library
            return await self._search_open_library(query, max_results)

    async def search_by_isbn(self, isbn: str) -> BookInfo | None:
        """
        Search for a book by ISBN.
        Falls back to Open Library if Google Books fails.

        Args:
            isbn: ISBN-10 or ISBN-13

        Returns:
            BookInfo if found, None otherwise
        """
        with create_span(
            "book_lookup_by_isbn",
            {"book_lookup.isbn": isbn},
        ) as span:
            # Try Google Books first
            try:
                client = await self._get_client()
                params = {
                    "q": f"isbn:{isbn}",
                    "maxResults": 1,
                }
                response = await client.get(self.GOOGLE_BOOKS_URL, params=params)
                response.raise_for_status()

                data = response.json()

                if data.get("totalItems", 0) == 0 or not data.get("items"):
                    add_span_attributes(
                        book_lookup_found=False,
                        book_lookup_source="google_books",
                    )
                    # Not found in Google Books, try Open Library
                    logger.info(f"ISBN {isbn} not found in Google Books, trying Open Library")
                    return await self._search_open_library_by_isbn(isbn)

                book = self._parse_google_volume(data["items"][0], override_isbn=isbn)

                add_span_attributes(
                    book_lookup_found=True,
                    book_lookup_title=book.title,
                    book_lookup_source="google_books",
                )
                set_span_status(True)
                return book

            except httpx.HTTPStatusError as e:
                logger.warning(
                    f"Google Books ISBN lookup failed ({e.response.status_code}): {e}. "
                    "Falling back to Open Library."
                )
                span.record_exception(e)
                add_span_attributes(
                    book_lookup_google_error=str(e),
                    book_lookup_google_status=e.response.status_code,
                    book_lookup_fallback="open_library",
                )

            except Exception as e:
                logger.warning(
                    f"Google Books ISBN lookup error: {e}. Falling back to Open Library."
                )
                span.record_exception(e)
                add_span_attributes(
                    book_lookup_google_error=str(e),
                    book_lookup_fallback="open_library",
                )

            # Fallback to Open Library
            return await self._search_open_library_by_isbn(isbn)


# Global instance for dependency injection
book_lookup_service = BookLookupService()


async def get_book_lookup_service() -> BookLookupService:
    """Dependency that provides the book lookup service."""
    return book_lookup_service
