"""Short-lived server-side stash of uploaded page photos.

Lets the add-highlight flow re-run extraction with edited instructions
without asking the user to re-upload the photo. Images live as temp files
under the system temp dir (never the database), keyed by a random token
embedded in the Phase-2 form. Entries expire after a TTL and the stash is
bounded, so it can never grow without limit.
"""

import logging
import re
import secrets
import tempfile
import time
from pathlib import Path

logger = logging.getLogger(__name__)

STASH_TTL_SECONDS = 30 * 60  # 30 minutes; refreshed on each successful get()
STASH_MAX_ENTRIES = 20

_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


class ImageStash:
    """Bounded, TTL-expiring file stash for uploaded images."""

    def __init__(
        self,
        directory: Path | None = None,
        ttl_seconds: float = STASH_TTL_SECONDS,
        max_entries: int = STASH_MAX_ENTRIES,
    ) -> None:
        self._dir = directory or Path(tempfile.gettempdir()) / "highlight_helper_image_stash"
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        self._dir.mkdir(parents=True, exist_ok=True)

    def put(self, image_bytes: bytes) -> str:
        """Store image bytes, returning the token used to retrieve them."""
        self._prune()
        token = secrets.token_urlsafe(16)
        (self._dir / f"{token}.img").write_bytes(image_bytes)
        return token

    def get(self, token: str) -> bytes | None:
        """Retrieve stashed bytes, or None if the token is invalid or expired.

        A successful get refreshes the entry's TTL (sliding expiry), so an
        active editing session keeps its photo alive.
        """
        if not _TOKEN_RE.match(token or ""):
            return None
        path = self._dir / f"{token}.img"
        try:
            if time.time() - path.stat().st_mtime > self._ttl:
                path.unlink(missing_ok=True)
                return None
            data = path.read_bytes()
            path.touch()
            return data
        except FileNotFoundError:
            return None
        except OSError as e:
            logger.warning(f"Image stash read failed for token {token[:8]}…: {e}")
            return None

    def _prune(self) -> None:
        """Drop expired entries, then oldest entries beyond the size bound."""
        try:
            entries = sorted(self._dir.glob("*.img"), key=lambda p: p.stat().st_mtime)
        except OSError:
            return
        now = time.time()
        kept: list[Path] = []
        for path in entries:
            try:
                if now - path.stat().st_mtime > self._ttl:
                    path.unlink(missing_ok=True)
                else:
                    kept.append(path)
            except OSError:
                continue
        # Evict oldest first so a new put() stays within the bound.
        excess = len(kept) - (self._max_entries - 1)
        for path in kept[:excess] if excess > 0 else []:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                continue


_image_stash: ImageStash | None = None


def get_image_stash() -> ImageStash:
    """Dependency that provides the process-wide image stash."""
    global _image_stash
    if _image_stash is None:
        _image_stash = ImageStash()
    return _image_stash
