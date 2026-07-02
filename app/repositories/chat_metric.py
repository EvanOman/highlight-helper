"""Chat metric repository for database access."""

from decimal import Decimal

from fastapi import Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.chat_metric import ChatMetric


class ChatMetricRepository:
    """Repository for ChatMetric database operations."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        *,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        total_tokens: int = 0,
        cost_usd: float | Decimal = 0.0,
        thread_id: int | None = None,
        book_id: int | None = None,
        ttft_ms: float | None = None,
        total_latency_ms: float | None = None,
        tokens_per_sec: float | None = None,
        stop_reason: str | None = None,
        message_count: int | None = None,
        context_utilization_pct: float | None = None,
    ) -> ChatMetric:
        """Create a new chat metric record."""
        metric = ChatMetric(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cost_usd=cost_usd,
            thread_id=thread_id,
            book_id=book_id,
            ttft_ms=ttft_ms,
            total_latency_ms=total_latency_ms,
            tokens_per_sec=tokens_per_sec,
            stop_reason=stop_reason,
            message_count=message_count,
            context_utilization_pct=context_utilization_pct,
        )
        self.db.add(metric)
        await self.db.flush()
        await self.db.refresh(metric)
        return metric

    async def list_recent(self, limit: int = 100) -> list[ChatMetric]:
        """List recent metrics, newest first."""
        query = (
            select(ChatMetric)
            .order_by(ChatMetric.timestamp.desc(), ChatMetric.id.desc())
            .limit(limit)
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_summary(self) -> dict:
        """Get aggregate summary stats."""
        query = select(
            func.count(ChatMetric.id).label("total_requests"),
            func.avg(ChatMetric.ttft_ms).label("avg_ttft_ms"),
            func.avg(ChatMetric.total_latency_ms).label("avg_latency_ms"),
            func.avg(ChatMetric.tokens_per_sec).label("avg_tokens_per_sec"),
            func.sum(ChatMetric.cost_usd).label("total_cost"),
            func.sum(ChatMetric.total_tokens).label("total_tokens"),
            func.sum(ChatMetric.input_tokens).label("total_input_tokens"),
            func.sum(ChatMetric.output_tokens).label("total_output_tokens"),
        )
        result = await self.db.execute(query)
        row = result.one()

        total_requests = row.total_requests or 0
        total_cost = float(row.total_cost or Decimal("0"))

        return {
            "total_requests": total_requests,
            "avg_ttft_ms": round(float(row.avg_ttft_ms or 0), 1),
            "avg_latency_ms": round(float(row.avg_latency_ms or 0), 1),
            "avg_tokens_per_sec": round(float(row.avg_tokens_per_sec or 0), 1),
            "total_cost": round(total_cost, 6),
            "total_tokens": int(row.total_tokens or 0),
            "total_input_tokens": int(row.total_input_tokens or 0),
            "total_output_tokens": int(row.total_output_tokens or 0),
            "avg_cost_per_request": round(total_cost / total_requests, 6)
            if total_requests > 0
            else 0,
        }


async def get_chat_metric_repo(
    db: AsyncSession = Depends(get_db),
) -> ChatMetricRepository:
    """FastAPI dependency that provides a ChatMetricRepository."""
    return ChatMetricRepository(db)
