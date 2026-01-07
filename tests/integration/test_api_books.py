"""Integration tests for the Books API."""

from httpx import AsyncClient


class TestBooksAPI:
    """Integration tests for the Books API endpoints."""

    async def test_list_books_empty(self, client: AsyncClient):
        """Test listing books when none exist."""
        response = await client.get("/api/books")
        assert response.status_code == 200
        data = response.json()
        assert data["books"] == []
        assert data["total"] == 0

    async def test_create_book(self, client: AsyncClient):
        """Test creating a new book."""
        response = await client.post(
            "/api/books",
            json={
                "title": "Test Book",
                "author": "Test Author",
                "isbn": "1234567890",
                "cover_url": "https://example.com/cover.jpg",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "Test Book"
        assert data["author"] == "Test Author"
        assert data["isbn"] == "1234567890"
        assert data["highlight_count"] == 0
        assert "id" in data
        assert "created_at" in data

    async def test_create_book_minimal(self, client: AsyncClient):
        """Test creating a book with minimal fields."""
        response = await client.post(
            "/api/books",
            json={"title": "Minimal Book", "author": "Unknown"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "Minimal Book"
        assert data["isbn"] is None

    async def test_create_book_invalid(self, client: AsyncClient):
        """Test creating a book with invalid data."""
        response = await client.post(
            "/api/books",
            json={"title": "", "author": "Author"},
        )
        assert response.status_code == 422

    async def test_get_book(self, client: AsyncClient, sample_book):
        """Test getting a specific book."""
        response = await client.get(f"/api/books/{sample_book.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == sample_book.id
        assert data["title"] == sample_book.title

    async def test_get_book_not_found(self, client: AsyncClient):
        """Test getting a non-existent book."""
        response = await client.get("/api/books/99999")
        assert response.status_code == 404

    async def test_update_book(self, client: AsyncClient, sample_book):
        """Test updating a book."""
        response = await client.patch(
            f"/api/books/{sample_book.id}",
            json={"title": "Updated Title"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Updated Title"
        assert data["author"] == sample_book.author

    async def test_update_book_not_found(self, client: AsyncClient):
        """Test updating a non-existent book."""
        response = await client.patch(
            "/api/books/99999",
            json={"title": "New Title"},
        )
        assert response.status_code == 404

    async def test_delete_book(self, client: AsyncClient, sample_book):
        """Test deleting a book."""
        response = await client.delete(f"/api/books/{sample_book.id}")
        assert response.status_code == 204

        # Verify it's gone
        response = await client.get(f"/api/books/{sample_book.id}")
        assert response.status_code == 404

    async def test_delete_book_not_found(self, client: AsyncClient):
        """Test deleting a non-existent book."""
        response = await client.delete("/api/books/99999")
        assert response.status_code == 404

    async def test_list_books_with_highlights(
        self, client: AsyncClient, sample_book, sample_highlight
    ):
        """Test listing books shows highlight count."""
        response = await client.get("/api/books")
        assert response.status_code == 200
        data = response.json()
        assert len(data["books"]) == 1
        assert data["books"][0]["highlight_count"] == 1

    async def test_search_books(self, client: AsyncClient, mock_book_lookup_service):
        """Test book search endpoint."""
        from app.services.book_lookup import BookInfo

        mock_book_lookup_service.search_books.return_value = [
            BookInfo(
                title="Found Book",
                author="Found Author",
                isbn="1234567890",
                cover_url="https://example.com/cover.jpg",
                description="A description",
            )
        ]

        response = await client.get("/api/books/search?q=test+query")
        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) == 1
        assert data["results"][0]["title"] == "Found Book"

    async def test_search_books_query_too_short(self, client: AsyncClient):
        """Test book search with query too short."""
        response = await client.get("/api/books/search?q=a")
        assert response.status_code == 400
