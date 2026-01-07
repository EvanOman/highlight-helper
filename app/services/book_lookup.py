"""Book lookup service using Google Books API."""

from dataclasses import dataclass

import httpx


@dataclass
class BookInfo:
    """Information about a book from Google Books API."""

    title: str
    author: str
    isbn: str | None = None
    cover_url: str | None = None
    description: str | None = None


class BookLookupService:
    """Service for looking up books using Google Books API."""

    BASE_URL = "https://www.googleapis.com/books/v1/volumes"

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def search_books(self, query: str, max_results: int = 10) -> list[BookInfo]:
        """
        Search for books by title, author, or ISBN.

        Args:
            query: Search query (title, author, or ISBN)
            max_results: Maximum number of results to return

        Returns:
            List of BookInfo objects
        """
        client = await self._get_client()

        params = {
            "q": query,
            "maxResults": min(max_results, 40),
            "printType": "books",
        }

        response = await client.get(self.BASE_URL, params=params)
        response.raise_for_status()

        data = response.json()
        books: list[BookInfo] = []

        for item in data.get("items", []):
            volume_info = item.get("volumeInfo", {})

            # Get ISBN
            isbn = None
            for identifier in volume_info.get("industryIdentifiers", []):
                if identifier.get("type") in ("ISBN_13", "ISBN_10"):
                    isbn = identifier.get("identifier")
                    break

            # Get cover image URL (prefer larger thumbnail)
            image_links = volume_info.get("imageLinks", {})
            cover_url = image_links.get("thumbnail") or image_links.get("smallThumbnail")
            # Convert to HTTPS if available
            if cover_url and cover_url.startswith("http://"):
                cover_url = cover_url.replace("http://", "https://")

            # Get authors (join multiple authors)
            authors = volume_info.get("authors", ["Unknown Author"])
            author = ", ".join(authors)

            books.append(
                BookInfo(
                    title=volume_info.get("title", "Unknown Title"),
                    author=author,
                    isbn=isbn,
                    cover_url=cover_url,
                    description=volume_info.get("description"),
                )
            )

        return books

    async def search_by_isbn(self, isbn: str) -> BookInfo | None:
        """
        Search for a book by ISBN.

        Args:
            isbn: ISBN-10 or ISBN-13

        Returns:
            BookInfo if found, None otherwise
        """
        client = await self._get_client()

        params = {
            "q": f"isbn:{isbn}",
            "maxResults": 1,
        }

        response = await client.get(self.BASE_URL, params=params)
        response.raise_for_status()

        data = response.json()

        if data.get("totalItems", 0) == 0:
            return None

        items = data.get("items", [])
        if not items:
            return None

        volume_info = items[0].get("volumeInfo", {})

        # Get authors
        authors = volume_info.get("authors", ["Unknown Author"])
        author = ", ".join(authors)

        # Get cover URL
        image_links = volume_info.get("imageLinks", {})
        cover_url = image_links.get("thumbnail") or image_links.get("smallThumbnail")
        if cover_url and cover_url.startswith("http://"):
            cover_url = cover_url.replace("http://", "https://")

        return BookInfo(
            title=volume_info.get("title", "Unknown Title"),
            author=author,
            isbn=isbn,
            cover_url=cover_url,
            description=volume_info.get("description"),
        )


# Global instance for dependency injection
book_lookup_service = BookLookupService()


async def get_book_lookup_service() -> BookLookupService:
    """Dependency that provides the book lookup service."""
    return book_lookup_service
