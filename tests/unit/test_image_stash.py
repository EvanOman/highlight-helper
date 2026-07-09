"""Tests for the short-lived image stash behind the re-extract flow."""

import os
import time

from app.services.image_stash import ImageStash


def _stash(tmp_path, **kwargs) -> ImageStash:
    return ImageStash(directory=tmp_path / "stash", **kwargs)


class TestImageStash:
    def test_put_get_roundtrip(self, tmp_path):
        stash = _stash(tmp_path)
        token = stash.put(b"jpeg bytes here")
        assert stash.get(token) == b"jpeg bytes here"

    def test_tokens_are_unique(self, tmp_path):
        stash = _stash(tmp_path)
        assert stash.put(b"a") != stash.put(b"b")

    def test_unknown_token_returns_none(self, tmp_path):
        stash = _stash(tmp_path)
        assert stash.get("aaaaaaaaaaaaaaaaaaaaaa") is None

    def test_malformed_tokens_are_rejected(self, tmp_path):
        stash = _stash(tmp_path)
        stash.put(b"data")
        for bad in ["", "../../etc/passwd", "a/b", "x" * 100, "short", "tok en"]:
            assert stash.get(bad) is None

    def test_expired_entry_returns_none_and_is_deleted(self, tmp_path):
        stash = _stash(tmp_path, ttl_seconds=60)
        token = stash.put(b"old data")
        path = tmp_path / "stash" / f"{token}.img"
        # Age the file past the TTL
        past = time.time() - 120
        os.utime(path, (past, past))
        assert stash.get(token) is None
        assert not path.exists()

    def test_bounded_size_evicts_oldest(self, tmp_path):
        stash = _stash(tmp_path, max_entries=3)
        tokens = []
        for i in range(5):
            tokens.append(stash.put(f"data {i}".encode()))
            # Ensure distinct mtimes so eviction order is deterministic
            path = tmp_path / "stash" / f"{tokens[-1]}.img"
            ts = time.time() - (5 - i)
            os.utime(path, (ts, ts))
        files = list((tmp_path / "stash").glob("*.img"))
        assert len(files) <= 3
        # The newest entry always survives
        assert stash.get(tokens[-1]) == b"data 4"

    def test_get_refreshes_ttl(self, tmp_path):
        stash = _stash(tmp_path, ttl_seconds=60)
        token = stash.put(b"data")
        path = tmp_path / "stash" / f"{token}.img"
        past = time.time() - 50
        os.utime(path, (past, past))
        assert stash.get(token) == b"data"
        # mtime was refreshed by the successful get
        assert time.time() - path.stat().st_mtime < 10
