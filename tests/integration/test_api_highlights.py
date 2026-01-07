"""Integration tests for the Highlights API."""

import io
import pytest
from httpx import AsyncClient


class TestHighlightsAPI:
    """Integration tests for the Highlights API endpoints."""

    async def test_list_highlights_for_book(
        self, client: AsyncClient, sample_book, sample_highlight
    ):
        """Test listing highlights for a specific book."""
        response = await client.get(f"/api/highlights/book/{sample_book.id}")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["text"] == sample_highlight.text
        assert data[0]["book_id"] == sample_book.id

    async def test_list_highlights_for_nonexistent_book(self, client: AsyncClient):
        """Test listing highlights for a non-existent book."""
        response = await client.get("/api/highlights/book/99999")
        assert response.status_code == 404

    async def test_list_all_highlights(
        self, client: AsyncClient, sample_book, sample_highlight
    ):
        """Test listing all highlights."""
        response = await client.get("/api/highlights")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["book_title"] == sample_book.title
        assert data[0]["book_author"] == sample_book.author

    async def test_create_highlight(self, client: AsyncClient, sample_book):
        """Test creating a new highlight."""
        response = await client.post(
            f"/api/highlights/book/{sample_book.id}",
            json={
                "text": "New highlight text",
                "note": "My note",
                "page_number": "123",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["text"] == "New highlight text"
        assert data["note"] == "My note"
        assert data["page_number"] == "123"
        assert data["book_id"] == sample_book.id

    async def test_create_highlight_minimal(self, client: AsyncClient, sample_book):
        """Test creating a highlight with minimal fields."""
        response = await client.post(
            f"/api/highlights/book/{sample_book.id}",
            json={"text": "Just the text"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["text"] == "Just the text"
        assert data["note"] is None

    async def test_create_highlight_for_nonexistent_book(self, client: AsyncClient):
        """Test creating a highlight for a non-existent book."""
        response = await client.post(
            "/api/highlights/book/99999",
            json={"text": "Some text"},
        )
        assert response.status_code == 404

    async def test_create_highlight_invalid(self, client: AsyncClient, sample_book):
        """Test creating a highlight with invalid data."""
        response = await client.post(
            f"/api/highlights/book/{sample_book.id}",
            json={"text": ""},
        )
        assert response.status_code == 422

    async def test_get_highlight(self, client: AsyncClient, sample_highlight):
        """Test getting a specific highlight."""
        response = await client.get(f"/api/highlights/{sample_highlight.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == sample_highlight.id
        assert data["text"] == sample_highlight.text

    async def test_get_highlight_not_found(self, client: AsyncClient):
        """Test getting a non-existent highlight."""
        response = await client.get("/api/highlights/99999")
        assert response.status_code == 404

    async def test_update_highlight(self, client: AsyncClient, sample_highlight):
        """Test updating a highlight."""
        response = await client.patch(
            f"/api/highlights/{sample_highlight.id}",
            json={"text": "Updated text", "note": "Updated note"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["text"] == "Updated text"
        assert data["note"] == "Updated note"

    async def test_update_highlight_partial(self, client: AsyncClient, sample_highlight):
        """Test partial update of a highlight."""
        original_text = sample_highlight.text
        response = await client.patch(
            f"/api/highlights/{sample_highlight.id}",
            json={"note": "Just updating note"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["text"] == original_text
        assert data["note"] == "Just updating note"

    async def test_update_highlight_not_found(self, client: AsyncClient):
        """Test updating a non-existent highlight."""
        response = await client.patch(
            "/api/highlights/99999",
            json={"text": "New text"},
        )
        assert response.status_code == 404

    async def test_delete_highlight(self, client: AsyncClient, sample_highlight):
        """Test deleting a highlight."""
        response = await client.delete(f"/api/highlights/{sample_highlight.id}")
        assert response.status_code == 204

        # Verify it's gone
        response = await client.get(f"/api/highlights/{sample_highlight.id}")
        assert response.status_code == 404

    async def test_delete_highlight_not_found(self, client: AsyncClient):
        """Test deleting a non-existent highlight."""
        response = await client.delete("/api/highlights/99999")
        assert response.status_code == 404

    async def test_extract_highlight_from_image(
        self, client: AsyncClient, sample_book, mock_highlight_extractor_service
    ):
        """Test extracting highlight from an image."""
        # Create a fake image file
        fake_image = io.BytesIO(b"fake image data")

        response = await client.post(
            f"/api/highlights/book/{sample_book.id}/extract",
            data={"instructions": "Extract the highlighted text"},
            files={"image": ("test.jpg", fake_image, "image/jpeg")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["text"] == "This is an extracted highlight."
        assert data["confidence"] == "high"
        assert data["page_number"] == "42"

    async def test_extract_highlight_invalid_file_type(
        self, client: AsyncClient, sample_book
    ):
        """Test extracting highlight with non-image file."""
        fake_file = io.BytesIO(b"not an image")

        response = await client.post(
            f"/api/highlights/book/{sample_book.id}/extract",
            data={"instructions": "Extract text"},
            files={"image": ("test.txt", fake_file, "text/plain")},
        )
        assert response.status_code == 400

    async def test_extract_highlight_nonexistent_book(self, client: AsyncClient):
        """Test extracting highlight for a non-existent book."""
        fake_image = io.BytesIO(b"fake image data")

        response = await client.post(
            "/api/highlights/book/99999/extract",
            data={"instructions": "Extract text"},
            files={"image": ("test.jpg", fake_image, "image/jpeg")},
        )
        assert response.status_code == 404
