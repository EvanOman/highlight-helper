"""Background job worker and handler registry.

Provides a minimal asyncio-based job queue backed by the ``jobs`` SQLite table.
A single worker task polls for queued jobs and dispatches them to registered
handler functions, each running inside its own database session.

Usage::

    from app.services.jobs import enqueue, job_handler

    @job_handler("my.task")
    async def handle_my_task(db: AsyncSession, payload: dict) -> dict | None:
        ...

    # Inside a request handler:
    await enqueue(request_db, "my.task", {"key": "value"}, max_attempts=3)
"""

import asyncio
import contextlib
import json
import logging
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.models.job import Job

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Handler registry
# ---------------------------------------------------------------------------

_handlers: dict[str, Callable[[AsyncSession, dict], Coroutine[Any, Any, Any]]] = {}


def job_handler(kind: str):
    """Decorator to register a job handler for a given ``kind``."""

    def decorator(
        func: Callable[[AsyncSession, dict], Coroutine[Any, Any, Any]],
    ) -> Callable[[AsyncSession, dict], Coroutine[Any, Any, Any]]:
        _handlers[kind] = func
        return func

    return decorator


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


async def enqueue(
    db: AsyncSession,
    kind: str,
    payload: dict | None = None,
    max_attempts: int = 1,
) -> Job:
    """Create a new job.  Flushes but does **not** commit (the caller's session
    commit handles that)."""
    job = Job(
        kind=kind,
        payload=json.dumps(payload) if payload else "{}",
        status="queued",
        max_attempts=max_attempts,
    )
    db.add(job)
    await db.flush()
    return job


async def has_pending_job(db: AsyncSession, kind: str) -> bool:
    """Return ``True`` if at least one queued/running job of *kind* exists."""
    result = await db.execute(
        select(Job.id).where(Job.kind == kind, Job.status.in_(["queued", "running"])).limit(1)
    )
    return result.scalar_one_or_none() is not None


# ---------------------------------------------------------------------------
# Worker internals
# ---------------------------------------------------------------------------


async def _run_one_job() -> bool:
    """Claim and execute one pending job.  Returns ``True`` when a job was
    processed (success or failure); ``False`` when the queue was empty."""

    # 1. Claim a job -------------------------------------------------------
    async with get_async_session() as db:
        now = datetime.now(UTC)
        result = await db.execute(
            select(Job)
            .where(
                Job.status == "queued",
                or_(Job.run_after == None, Job.run_after <= now),  # noqa: E711
            )
            .order_by(Job.created_at)
            .limit(1)
        )
        job = result.scalar_one_or_none()
        if not job:
            return False

        job_id = job.id
        job_kind = job.kind
        job_payload = job.payload

        job.status = "running"
        job.attempts += 1
        job.updated_at = now
        # session commits on context-manager exit

    # 2. Look up handler ---------------------------------------------------
    handler = _handlers.get(job_kind)
    if not handler:
        async with get_async_session() as db:
            j = await db.get(Job, job_id)
            if j:
                j.status = "failed"
                j.error = f"No handler registered for kind '{job_kind}'"
                j.updated_at = datetime.now(UTC)
        logger.error("No handler for job kind '%s' (job %d)", job_kind, job_id)
        return True

    # 3. Execute handler in its own session --------------------------------
    payload = json.loads(job_payload) if job_payload else {}
    try:
        async with get_async_session() as handler_db:
            handler_result = await handler(handler_db, payload)

        # Mark done
        async with get_async_session() as db:
            j = await db.get(Job, job_id)
            if j:
                j.status = "done"
                j.result = json.dumps(handler_result) if handler_result else None
                j.error = None
                j.updated_at = datetime.now(UTC)

        logger.info("Job %d (%s) completed successfully", job_id, job_kind)

    except Exception as exc:
        logger.exception("Job %d (%s) failed", job_id, job_kind)
        async with get_async_session() as db:
            j = await db.get(Job, job_id)
            if j:
                if j.attempts < j.max_attempts:
                    j.status = "queued"
                    backoff = timedelta(seconds=2**j.attempts)
                    j.run_after = datetime.now(UTC) + backoff
                    logger.info(
                        "Job %d will retry in %s (attempt %d/%d)",
                        job_id,
                        backoff,
                        j.attempts,
                        j.max_attempts,
                    )
                else:
                    j.status = "failed"
                    logger.warning(
                        "Job %d failed permanently after %d attempts",
                        job_id,
                        j.attempts,
                    )
                j.error = str(exc)
                j.updated_at = datetime.now(UTC)

    return True


# ---------------------------------------------------------------------------
# Worker lifecycle
# ---------------------------------------------------------------------------

_worker_task: asyncio.Task[None] | None = None
_shutdown_event: asyncio.Event | None = None


async def _worker_loop() -> None:
    """Poll for queued jobs; sleep 1 s when idle."""
    global _shutdown_event
    _shutdown_event = asyncio.Event()
    logger.info("Job worker started")

    while not _shutdown_event.is_set():
        try:
            found = await _run_one_job()
            if not found:
                # Nothing to do -- wait up to 1 s (or until shutdown signal)
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(_shutdown_event.wait(), timeout=1.0)
        except Exception:
            logger.exception("Unexpected error in job worker loop")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(_shutdown_event.wait(), timeout=5.0)

    logger.info("Job worker stopped")


def start_worker() -> None:
    """Launch the background worker task (idempotent)."""
    global _worker_task
    if _worker_task is None or _worker_task.done():
        _worker_task = asyncio.create_task(_worker_loop())


async def stop_worker() -> None:
    """Gracefully shut down the background worker."""
    global _worker_task, _shutdown_event
    if _shutdown_event:
        _shutdown_event.set()
    if _worker_task and not _worker_task.done():
        await _worker_task
    _worker_task = None
    _shutdown_event = None


# ---------------------------------------------------------------------------
# Built-in handlers (imported at module load so they register automatically)
# ---------------------------------------------------------------------------


@job_handler("coaching.generate")
async def _handle_coaching_generate(db: AsyncSession, payload: dict) -> dict | None:
    """Generate a coaching card via ``CoachingService.select_and_generate``."""
    from app.services.coaching import CoachingService

    service = CoachingService(db)
    return await service.select_and_generate()


@job_handler("readwise.sync_highlight")
async def _handle_readwise_sync(db: AsyncSession, payload: dict) -> dict | None:
    """Sync a single highlight to Readwise with retry support."""
    from app.models.highlight import Highlight, SyncStatus
    from app.services.readwise import ReadwiseService
    from app.services.settings import SettingsService

    settings_svc = SettingsService(db)
    token = await settings_svc.get_readwise_token()
    if not token:
        return {"skipped": True, "reason": "no_token"}

    service = ReadwiseService(api_token=token)
    highlighted_at = (
        datetime.fromisoformat(payload["created_at"]) if payload.get("created_at") else None
    )
    result = await service.send_highlight(
        text=payload["text"],
        title=payload["book_title"],
        author=payload.get("book_author") or "Unknown Author",
        note=payload.get("note"),
        page_number=payload.get("page_number"),
        highlighted_at=highlighted_at,
    )

    if result.success:
        highlight = await db.get(Highlight, payload["highlight_id"])
        if highlight:
            highlight.readwise_id = result.readwise_id
            highlight.synced_at = datetime.now(tz=UTC)
            highlight.sync_status = SyncStatus.SYNCED
            logger.info("Auto-synced highlight %d to Readwise", payload["highlight_id"])
        return {"readwise_id": result.readwise_id}

    raise RuntimeError(f"Readwise sync failed: {result.error}")
