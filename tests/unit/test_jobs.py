"""Unit tests for the background job worker."""

from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.job import Job
from app.services.jobs import (
    _handlers,
    _run_one_job,
    enqueue,
    has_pending_job,
    job_handler,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def _session_factory(test_engine):
    """Create a context-manager factory that yields sessions on the test DB,
    matching the ``get_async_session`` signature."""
    maker = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    @asynccontextmanager
    async def _factory():
        async with maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    return _factory


@pytest.fixture(autouse=True)
def _clean_test_handlers():
    """Preserve the production handler registry across tests."""
    saved = _handlers.copy()
    yield
    _handlers.clear()
    _handlers.update(saved)


# ---------------------------------------------------------------------------
# enqueue / has_pending_job
# ---------------------------------------------------------------------------


class TestEnqueue:
    async def test_creates_queued_job(self, test_session: AsyncSession):
        job = await enqueue(test_session, "test.echo", {"msg": "hi"})
        assert job.id is not None
        assert job.kind == "test.echo"
        assert job.status == "queued"
        assert job.max_attempts == 1
        assert job.attempts == 0

    async def test_custom_max_attempts(self, test_session: AsyncSession):
        job = await enqueue(test_session, "test.retry", {"x": 1}, max_attempts=5)
        assert job.max_attempts == 5


class TestHasPendingJob:
    async def test_returns_false_when_empty(self, test_session: AsyncSession):
        assert not await has_pending_job(test_session, "nonexistent")

    async def test_returns_true_for_queued(self, test_session: AsyncSession):
        await enqueue(test_session, "test.kind")
        assert await has_pending_job(test_session, "test.kind")

    async def test_returns_true_for_running(self, test_session: AsyncSession):
        job = await enqueue(test_session, "test.kind")
        job.status = "running"
        await test_session.flush()
        assert await has_pending_job(test_session, "test.kind")

    async def test_returns_false_for_done(self, test_session: AsyncSession):
        job = await enqueue(test_session, "test.kind")
        job.status = "done"
        await test_session.flush()
        assert not await has_pending_job(test_session, "test.kind")


# ---------------------------------------------------------------------------
# Worker (_run_one_job)
# ---------------------------------------------------------------------------


class TestRunOneJob:
    async def test_empty_queue_returns_false(self, _session_factory):
        with patch("app.services.jobs.get_async_session", _session_factory):
            assert not await _run_one_job()

    async def test_handler_runs_and_marks_done(self, test_session, _session_factory):
        called = {}

        @job_handler("test.echo")
        async def _handler(db: AsyncSession, payload: dict):
            called["payload"] = payload
            return {"echoed": True}

        await enqueue(test_session, "test.echo", {"msg": "hello"})
        await test_session.commit()

        with patch("app.services.jobs.get_async_session", _session_factory):
            found = await _run_one_job()

        assert found is True
        assert called["payload"] == {"msg": "hello"}

        # Verify status is done
        async with _session_factory() as db:
            j = (await db.execute(select(Job).where(Job.kind == "test.echo"))).scalar_one()
            assert j.status == "done"
            assert j.error is None
            assert j.attempts == 1

    async def test_failing_handler_retries(self, test_session, _session_factory):
        call_count = {"n": 0}

        @job_handler("test.fail")
        async def _handler(db: AsyncSession, payload: dict):
            call_count["n"] += 1
            raise RuntimeError("boom")

        await enqueue(test_session, "test.fail", max_attempts=3)
        await test_session.commit()

        with patch("app.services.jobs.get_async_session", _session_factory):
            # First attempt: fails, re-queued with backoff
            await _run_one_job()

        async with _session_factory() as db:
            j = (await db.execute(select(Job).where(Job.kind == "test.fail"))).scalar_one()
            assert j.status == "queued"
            assert j.attempts == 1
            assert j.error == "boom"
            assert j.run_after is not None
            # Clear run_after so next poll picks it up immediately
            j.run_after = None

        with patch("app.services.jobs.get_async_session", _session_factory):
            await _run_one_job()

        async with _session_factory() as db:
            j = (await db.execute(select(Job).where(Job.kind == "test.fail"))).scalar_one()
            assert j.status == "queued"
            assert j.attempts == 2
            j.run_after = None

        with patch("app.services.jobs.get_async_session", _session_factory):
            await _run_one_job()

        async with _session_factory() as db:
            j = (await db.execute(select(Job).where(Job.kind == "test.fail"))).scalar_one()
            assert j.status == "failed"
            assert j.attempts == 3
            assert j.error == "boom"

        assert call_count["n"] == 3

    async def test_no_handler_marks_failed(self, test_session, _session_factory):
        await enqueue(test_session, "test.missing_handler")
        await test_session.commit()

        with patch("app.services.jobs.get_async_session", _session_factory):
            found = await _run_one_job()

        assert found is True

        async with _session_factory() as db:
            j = (
                await db.execute(select(Job).where(Job.kind == "test.missing_handler"))
            ).scalar_one()
            assert j.status == "failed"
            assert "No handler" in (j.error or "")

    async def test_backoff_prevents_immediate_retry(self, test_session, _session_factory):
        """A re-queued job with run_after in the future is not picked up."""

        @job_handler("test.backoff")
        async def _handler(db: AsyncSession, payload: dict):
            raise RuntimeError("fail")

        await enqueue(test_session, "test.backoff", max_attempts=2)
        await test_session.commit()

        with patch("app.services.jobs.get_async_session", _session_factory):
            await _run_one_job()

        # Job is re-queued with run_after set
        async with _session_factory() as db:
            j = (await db.execute(select(Job).where(Job.kind == "test.backoff"))).scalar_one()
            assert j.status == "queued"
            assert j.run_after is not None

        # Next poll should NOT pick it up (run_after is in future)
        with patch("app.services.jobs.get_async_session", _session_factory):
            found = await _run_one_job()
        assert found is False

    async def test_handler_result_stored(self, test_session, _session_factory):
        @job_handler("test.result")
        async def _handler(db: AsyncSession, payload: dict):
            return {"answer": 42}

        await enqueue(test_session, "test.result")
        await test_session.commit()

        with patch("app.services.jobs.get_async_session", _session_factory):
            await _run_one_job()

        async with _session_factory() as db:
            j = (await db.execute(select(Job).where(Job.kind == "test.result"))).scalar_one()
            assert j.status == "done"
            assert '"answer": 42' in (j.result or "")
