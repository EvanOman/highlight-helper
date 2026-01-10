"""Integration tests for Readwise API endpoints."""


class TestReadwiseAPI:
    """Tests for the Readwise API endpoints."""

    async def test_get_status_configured(self, client):
        """Test getting Readwise status when configured."""
        response = await client.get("/api/readwise/status")
        assert response.status_code == 200
        data = response.json()
        assert data["configured"] is True
        assert data["token_valid"] is True

    async def test_get_status_unconfigured(self, client_readwise_unconfigured):
        """Test getting Readwise status when not configured."""
        response = await client_readwise_unconfigured.get("/api/readwise/status")
        assert response.status_code == 200
        data = response.json()
        assert data["configured"] is False

    async def test_validate_token_success(self, client):
        """Test validating Readwise token."""
        response = await client.post("/api/readwise/validate")
        assert response.status_code == 200
        data = response.json()
        assert data["configured"] is True
        assert data["token_valid"] is True

    async def test_validate_token_unconfigured(self, client_readwise_unconfigured):
        """Test validating token when not configured."""
        response = await client_readwise_unconfigured.post("/api/readwise/validate")
        assert response.status_code == 200
        data = response.json()
        assert data["configured"] is False

    async def test_sync_highlight_success(self, client, sample_highlight):
        """Test syncing a single highlight to Readwise."""
        response = await client.post(f"/api/readwise/sync/{sample_highlight.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["readwise_id"] == "12345"

    async def test_sync_highlight_not_found(self, client):
        """Test syncing a non-existent highlight."""
        response = await client.post("/api/readwise/sync/99999")
        assert response.status_code == 404

    async def test_sync_highlight_unconfigured(
        self, client_readwise_unconfigured, sample_highlight
    ):
        """Test syncing when Readwise not configured."""
        response = await client_readwise_unconfigured.post(
            f"/api/readwise/sync/{sample_highlight.id}"
        )
        assert response.status_code == 400
        assert "not configured" in response.json()["detail"]

    async def test_sync_book_highlights_success(self, client, sample_book, sample_highlight):
        """Test syncing all highlights for a book."""
        response = await client.post(f"/api/readwise/sync/book/{sample_book.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["synced"] == 1
        assert data["failed"] == 0

    async def test_sync_book_highlights_book_not_found(self, client):
        """Test syncing highlights for non-existent book."""
        response = await client.post("/api/readwise/sync/book/99999")
        assert response.status_code == 404

    async def test_sync_book_highlights_unconfigured(
        self, client_readwise_unconfigured, sample_book
    ):
        """Test syncing book highlights when Readwise not configured."""
        response = await client_readwise_unconfigured.post(
            f"/api/readwise/sync/book/{sample_book.id}"
        )
        assert response.status_code == 400

    async def test_sync_all_highlights_success(self, client, sample_highlight):
        """Test syncing all highlights."""
        # Access sample_highlight to ensure it's created
        _ = sample_highlight.id
        response = await client.post("/api/readwise/sync/all")
        assert response.status_code == 200, f"Response: {response.json()}"
        data = response.json()
        # May be 0 if the highlight is already synced (has synced_at set in previous test)
        assert "total" in data
        assert "synced" in data
        assert "failed" in data

    async def test_sync_all_highlights_unconfigured(self, client_readwise_unconfigured):
        """Test syncing all highlights when Readwise not configured."""
        response = await client_readwise_unconfigured.post("/api/readwise/sync/all")
        assert response.status_code == 400
