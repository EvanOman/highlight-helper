"""Integration tests for chat metrics endpoints."""

from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat_metric import ChatMetric
from app.repositories.chat_metric import ChatMetricRepository


class TestMetricsPage:
    """Tests for the metrics HTML page."""

    async def test_metrics_page_empty(self, client: AsyncClient):
        """Test metrics page renders with no data."""
        response = await client.get("/metrics")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "Chat Metrics" in response.text
        assert "No chat metrics yet" in response.text

    async def test_metrics_page_with_data(self, client: AsyncClient, test_session: AsyncSession):
        """Test metrics page renders with metric records."""
        metric = ChatMetric(
            model="claude-haiku-4-5-20251001",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            cost_usd=Decimal("0.00028"),
            ttft_ms=250.0,
            total_latency_ms=1500.0,
            tokens_per_sec=33.3,
            stop_reason="end_turn",
            message_count=2,
            context_utilization_pct=0.05,
        )
        test_session.add(metric)
        await test_session.flush()

        response = await client.get("/metrics")
        assert response.status_code == 200
        assert "haiku" in response.text
        assert "end_turn" in response.text


class TestMetricsAPI:
    """Tests for the metrics JSON API."""

    async def test_chat_metrics_api_empty(self, client: AsyncClient):
        """Test JSON endpoint with no data."""
        response = await client.get("/api/metrics/chat")
        assert response.status_code == 200
        data = response.json()
        assert "summary" in data
        assert "metrics" in data
        assert data["summary"]["total_requests"] == 0
        assert len(data["metrics"]) == 0

    async def test_chat_metrics_api_with_data(
        self, client: AsyncClient, test_session: AsyncSession
    ):
        """Test JSON endpoint with metric records."""
        metric = ChatMetric(
            model="claude-sonnet-4-5-20250929",
            input_tokens=500,
            output_tokens=200,
            total_tokens=700,
            cost_usd=Decimal("0.0045"),
            ttft_ms=300.0,
            total_latency_ms=5000.0,
            tokens_per_sec=40.0,
            stop_reason="end_turn",
            message_count=4,
            context_utilization_pct=0.25,
        )
        test_session.add(metric)
        await test_session.flush()

        response = await client.get("/api/metrics/chat")
        assert response.status_code == 200
        data = response.json()
        assert data["summary"]["total_requests"] == 1
        assert data["summary"]["total_tokens"] == 700
        assert len(data["metrics"]) == 1
        assert data["metrics"][0]["model"] == "claude-sonnet-4-5-20250929"
        assert data["metrics"][0]["stop_reason"] == "end_turn"


class TestChatMetricRepository:
    """Tests for ChatMetricRepository aggregation."""

    async def test_get_summary_aggregation(self, test_session: AsyncSession):
        """Test summary aggregation is correct."""
        repo = ChatMetricRepository(test_session)

        await repo.create(
            model="claude-haiku-4-5-20251001",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            cost_usd=0.001,
            ttft_ms=200.0,
            total_latency_ms=1000.0,
            tokens_per_sec=50.0,
            stop_reason="end_turn",
        )
        await repo.create(
            model="claude-haiku-4-5-20251001",
            input_tokens=200,
            output_tokens=100,
            total_tokens=300,
            cost_usd=0.002,
            ttft_ms=400.0,
            total_latency_ms=3000.0,
            tokens_per_sec=30.0,
            stop_reason="end_turn",
        )

        summary = await repo.get_summary()
        assert summary["total_requests"] == 2
        assert summary["total_tokens"] == 450
        assert summary["total_input_tokens"] == 300
        assert summary["total_output_tokens"] == 150
        assert summary["avg_ttft_ms"] == 300.0
        assert summary["avg_latency_ms"] == 2000.0
        assert summary["avg_tokens_per_sec"] == 40.0
        assert summary["total_cost"] == 0.003
        assert summary["avg_cost_per_request"] == 0.0015

    async def test_list_recent_ordering(self, test_session: AsyncSession):
        """Test list_recent returns newest first."""
        repo = ChatMetricRepository(test_session)

        m1 = await repo.create(
            model="model-a",
            input_tokens=10,
            output_tokens=5,
            total_tokens=15,
            cost_usd=0.0001,
        )
        m2 = await repo.create(
            model="model-b",
            input_tokens=20,
            output_tokens=10,
            total_tokens=30,
            cost_usd=0.0002,
        )

        results = await repo.list_recent(limit=10)
        assert len(results) == 2
        # Newest first (m2 was created after m1)
        assert results[0].id == m2.id
        assert results[1].id == m1.id
