"""Chat metrics dashboard view."""

from fastapi import Depends, Request
from fastapi.responses import HTMLResponse

from app.repositories.chat_metric import ChatMetricRepository, get_chat_metric_repo

from ._common import router, templates


@router.get("/metrics", response_class=HTMLResponse)
async def metrics_page(
    request: Request,
    metric_repo: ChatMetricRepository = Depends(get_chat_metric_repo),
):
    """Chat metrics dashboard page."""
    summary = await metric_repo.get_summary()
    metrics = await metric_repo.list_recent(limit=100)

    return templates.TemplateResponse(
        request,
        "metrics.html",
        {
            "summary": summary,
            "metrics": metrics,
        },
    )


@router.get("/api/metrics/chat")
async def chat_metrics_api(
    metric_repo: ChatMetricRepository = Depends(get_chat_metric_repo),
):
    """JSON endpoint for chat metrics (used by JS refresh)."""
    summary = await metric_repo.get_summary()
    metrics = await metric_repo.list_recent(limit=100)

    return {
        "summary": summary,
        "metrics": [
            {
                "id": m.id,
                "timestamp": m.timestamp.isoformat() if m.timestamp else None,
                "thread_id": m.thread_id,
                "book_id": m.book_id,
                "model": m.model,
                "input_tokens": m.input_tokens,
                "output_tokens": m.output_tokens,
                "total_tokens": m.total_tokens,
                "cost_usd": float(m.cost_usd) if m.cost_usd else 0,
                "ttft_ms": m.ttft_ms,
                "total_latency_ms": m.total_latency_ms,
                "tokens_per_sec": m.tokens_per_sec,
                "stop_reason": m.stop_reason,
                "message_count": m.message_count,
                "context_utilization_pct": m.context_utilization_pct,
            }
            for m in metrics
        ],
    }
