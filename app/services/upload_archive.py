"""Upload retention: persist every uploaded page photo as an eval-corpus candidate.

Each extraction (success OR failure) writes the uploaded image bytes as received
by the server, plus a JSON sidecar capturing the instructions and the full
extraction outcome. Together they form a near-ready eval case that
``scripts/promote_upload.py`` can turn into a labelled case under
``evals/samples/real/``.

Retention is best-effort and must NEVER break extraction: all I/O is wrapped so
that any failure is logged and swallowed, and the request proceeds.

See ``docs/decisions/2026-07-12-image-retention.md`` for the storage layout and
dedupe rationale.
"""

import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.services.highlight_extractor import ExtractedHighlight

logger = logging.getLogger(__name__)

# Sidecar schema version — bump if the JSON shape changes so downstream
# consumers (promotion script, eval miners) can adapt.
SIDECAR_SCHEMA_VERSION = 1


def _image_extension(filename: str | None) -> str:
    """Return the storage extension for an upload.

    JPEG-family uploads normalise to ``.jpg``; anything else keeps its original
    extension so the raw bytes remain faithfully decodable (e.g. PNG, HEIC, MPO).
    """
    suffix = Path(filename or "").suffix.lower().lstrip(".")
    if suffix in ("", "jpg", "jpeg"):
        return ".jpg"
    return f".{suffix}"


class UploadArchiveService:
    """Persists uploaded images + extraction sidecars for eval-corpus mining."""

    def __init__(self, *, enabled: bool, base_dir: str | Path) -> None:
        self._enabled = enabled
        self._base_dir = Path(base_dir)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def archive_extraction(
        self,
        *,
        image_bytes: bytes,
        filename: str | None,
        book_id: int,
        instructions: str,
        result: ExtractedHighlight | None = None,
        model: str | None = None,
        error: str | None = None,
    ) -> Path | None:
        """Persist an upload + its extraction outcome. Best-effort, never raises.

        Args:
            image_bytes: The uploaded image AS RECEIVED by the server (pre-vision
                normalisation) — this is what an eval must replay against.
            filename: Original client filename, used only for the extension and
                recorded in the sidecar.
            book_id: Book the upload was for.
            instructions: The user's extraction instructions.
            result: The extraction result, if extraction produced one.
            model: Vision model used, if known (falls back to configured default).
            error: Error message if extraction failed.

        Returns:
            Path to the written sidecar, or ``None`` if retention is disabled or
            failed (failures are logged, not raised).
        """
        if not self._enabled:
            return None
        try:
            return self._write(
                image_bytes=image_bytes,
                filename=filename,
                book_id=book_id,
                instructions=instructions,
                result=result,
                model=model,
                error=error,
            )
        except Exception as exc:
            logger.warning("Upload retention failed (extraction unaffected): %s", exc)
            return None

    def _write(
        self,
        *,
        image_bytes: bytes,
        filename: str | None,
        book_id: int,
        instructions: str,
        result: ExtractedHighlight | None,
        model: str | None,
        error: str | None,
    ) -> Path:
        sha256 = hashlib.sha256(image_bytes).hexdigest()
        short = sha256[:8]
        now = datetime.now(UTC)
        # Microsecond-precision compact timestamp keeps sidecar stems unique even
        # when the same image is re-extracted twice within one second.
        ts = now.strftime("%Y%m%dT%H%M%S%fZ")
        ext = _image_extension(filename)

        self._base_dir.mkdir(parents=True, exist_ok=True)

        # Image is content-addressed by sha: write once, reuse across sidecars.
        # This dedupes bytes when the same photo is re-extracted with different
        # instructions (see decision doc). The sidecar records the full sha and
        # the image filename so the two stay associated.
        image_name = f"{short}{ext}"
        image_path = self._base_dir / image_name
        if not image_path.exists():
            image_path.write_bytes(image_bytes)

        sidecar = self._build_sidecar(
            timestamp=now,
            book_id=book_id,
            filename=filename,
            instructions=instructions,
            sha256=sha256,
            image_name=image_name,
            result=result,
            model=model,
            error=error,
        )
        sidecar_path = self._base_dir / f"{ts}-{short}.json"
        sidecar_path.write_text(json.dumps(sidecar, indent=2, ensure_ascii=False))
        logger.info("Archived upload %s (sidecar %s)", image_name, sidecar_path.name)
        return sidecar_path

    def _build_sidecar(
        self,
        *,
        timestamp: datetime,
        book_id: int,
        filename: str | None,
        instructions: str,
        sha256: str,
        image_name: str,
        result: ExtractedHighlight | None,
        model: str | None,
        error: str | None,
    ) -> dict[str, Any]:
        # Resolve model: prefer an explicit override, then the model recorded in
        # the extraction's usage, then the configured default.
        resolved_model = model
        if resolved_model is None and result is not None and result.usage is not None:
            resolved_model = result.usage.model or None
        if resolved_model is None:
            resolved_model = get_settings().vision_model

        extraction: dict[str, Any] = {
            "full_text": None,
            "highlight_text": None,
            "highlight_start": None,
            "highlight_end": None,
            "confidence": None,
            "page_number": None,
            # Forward-compatible: these fields don't exist on ExtractedHighlight
            # yet on this branch but are populated once the honesty tracks merge.
            "match_status": None,
            "match_quality": None,
            "error": error,
        }
        if result is not None:
            extraction.update(
                full_text=result.full_text,
                highlight_text=result.highlight_text,
                highlight_start=result.highlight_start,
                highlight_end=result.highlight_end,
                confidence=result.confidence,
                page_number=result.page_number,
                match_status=getattr(result, "match_status", None),
                match_quality=getattr(result, "match_quality", None),
            )
            # A result-carried error (if the model surfaces one) takes precedence.
            extraction["error"] = getattr(result, "error", None) or error

        return {
            "schema_version": SIDECAR_SCHEMA_VERSION,
            "timestamp": timestamp.isoformat(),
            "book_id": book_id,
            "original_filename": filename,
            "instructions": instructions,
            "sha256": sha256,
            "image": image_name,
            "model": resolved_model,
            "extraction": extraction,
            # A stored upload is a NEAR-ready eval case: labels are model-drafted
            # and must be human-verified before promotion.
            "needs_verification": True,
        }


# Lazy singleton so the service reads settings once and reuses the base dir.
_upload_archive_service: UploadArchiveService | None = None


def _get_service() -> UploadArchiveService:
    global _upload_archive_service
    if _upload_archive_service is None:
        settings = get_settings()
        _upload_archive_service = UploadArchiveService(
            enabled=settings.store_uploaded_images,
            base_dir=settings.uploaded_images_dir,
        )
    return _upload_archive_service


def get_upload_archive_service() -> UploadArchiveService:
    """FastAPI dependency that provides the upload archive service."""
    return _get_service()
