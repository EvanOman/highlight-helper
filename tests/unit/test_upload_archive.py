"""Unit tests for the upload retention service."""

import hashlib
import json
from pathlib import Path

from app.services.highlight_extractor import ExtractedHighlight, TokenUsage
from app.services.upload_archive import UploadArchiveService, _image_extension


def _make_result(usage: TokenUsage | None = None) -> ExtractedHighlight:
    return ExtractedHighlight(
        full_text="The full page text.",
        highlight_text="page text",
        confidence="high",
        page_number="42",
        highlight_start=9,
        highlight_end=18,
        usage=usage,
    )


class TestFlagOff:
    def test_disabled_writes_nothing(self, tmp_path: Path):
        service = UploadArchiveService(enabled=False, base_dir=tmp_path)
        out = service.archive_extraction(
            image_bytes=b"imgbytes",
            filename="photo.jpg",
            book_id=1,
            instructions="extract",
            result=_make_result(),
        )
        assert out is None
        assert list(tmp_path.iterdir()) == []


class TestSuccessfulArchive:
    def test_writes_image_and_sidecar(self, tmp_path: Path):
        service = UploadArchiveService(enabled=True, base_dir=tmp_path)
        image_bytes = b"the raw image bytes as received"
        sha = hashlib.sha256(image_bytes).hexdigest()

        sidecar_path = service.archive_extraction(
            image_bytes=image_bytes,
            filename="IMG_1234.jpeg",
            book_id=7,
            instructions="the highlighted sentence",
            result=_make_result(),
            model="openai/gpt-5.4",
        )

        assert sidecar_path is not None
        assert sidecar_path.exists()

        # Image content-addressed by sha8, jpeg-family normalised to .jpg, and
        # holds the exact raw bytes received (pre-vision normalisation).
        image_path = tmp_path / f"{sha[:8]}.jpg"
        assert image_path.exists()
        assert image_path.read_bytes() == image_bytes

        data = json.loads(sidecar_path.read_text())
        assert data["book_id"] == 7
        assert data["original_filename"] == "IMG_1234.jpeg"
        assert data["instructions"] == "the highlighted sentence"
        assert data["sha256"] == sha
        assert data["image"] == f"{sha[:8]}.jpg"
        assert data["model"] == "openai/gpt-5.4"
        assert data["needs_verification"] is True

        extraction = data["extraction"]
        assert extraction["full_text"] == "The full page text."
        assert extraction["highlight_text"] == "page text"
        assert extraction["highlight_start"] == 9
        assert extraction["highlight_end"] == 18
        assert extraction["confidence"] == "high"
        assert extraction["page_number"] == "42"
        # Forward-compatible fields present even though absent on this branch.
        assert extraction["match_status"] is None
        assert extraction["match_quality"] is None
        assert extraction["error"] is None

    def test_model_falls_back_to_usage(self, tmp_path: Path):
        service = UploadArchiveService(enabled=True, base_dir=tmp_path)
        result = _make_result(TokenUsage(model="groq/fallback"))
        sidecar_path = service.archive_extraction(
            image_bytes=b"x",
            filename="p.jpg",
            book_id=1,
            instructions="i",
            result=result,
        )
        assert sidecar_path is not None
        assert json.loads(sidecar_path.read_text())["model"] == "groq/fallback"

    def test_non_jpeg_keeps_extension(self, tmp_path: Path):
        service = UploadArchiveService(enabled=True, base_dir=tmp_path)
        image_bytes = b"pngdata"
        sha = hashlib.sha256(image_bytes).hexdigest()
        service.archive_extraction(
            image_bytes=image_bytes,
            filename="scan.PNG",
            book_id=1,
            instructions="i",
            result=_make_result(),
        )
        assert (tmp_path / f"{sha[:8]}.png").exists()

    def test_failure_outcome_is_archived(self, tmp_path: Path):
        """Failed extractions (result=None + error) are still mined."""
        service = UploadArchiveService(enabled=True, base_dir=tmp_path)
        sidecar_path = service.archive_extraction(
            image_bytes=b"boom",
            filename="p.jpg",
            book_id=3,
            instructions="i",
            result=None,
            error="Error extracting text: kaboom",
        )
        assert sidecar_path is not None
        data = json.loads(sidecar_path.read_text())
        assert data["extraction"]["error"] == "Error extracting text: kaboom"
        assert data["extraction"]["full_text"] is None


class TestDedupe:
    def test_same_bytes_one_image_two_sidecars(self, tmp_path: Path):
        service = UploadArchiveService(enabled=True, base_dir=tmp_path)
        image_bytes = b"identical photo bytes"
        sha = hashlib.sha256(image_bytes).hexdigest()

        service.archive_extraction(
            image_bytes=image_bytes,
            filename="p.jpg",
            book_id=1,
            instructions="instructions A",
            result=_make_result(),
        )
        service.archive_extraction(
            image_bytes=image_bytes,
            filename="p.jpg",
            book_id=1,
            instructions="instructions B",
            result=_make_result(),
        )

        images = list(tmp_path.glob("*.jpg"))
        sidecars = list(tmp_path.glob("*.json"))
        assert len(images) == 1
        assert images[0].name == f"{sha[:8]}.jpg"
        assert len(sidecars) == 2
        instructions = {json.loads(s.read_text())["instructions"] for s in sidecars}
        assert instructions == {"instructions A", "instructions B"}


class TestFailureInjection:
    def test_write_failure_is_swallowed(self, tmp_path: Path, monkeypatch):
        """A retention I/O failure must never propagate to the caller."""
        service = UploadArchiveService(enabled=True, base_dir=tmp_path)

        def boom(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr("app.services.upload_archive.Path.write_bytes", boom, raising=True)

        # Must not raise; returns None on failure.
        out = service.archive_extraction(
            image_bytes=b"x",
            filename="p.jpg",
            book_id=1,
            instructions="i",
            result=_make_result(),
        )
        assert out is None


def test_image_extension_helper():
    assert _image_extension("a.jpg") == ".jpg"
    assert _image_extension("a.JPEG") == ".jpg"
    assert _image_extension("a.png") == ".png"
    assert _image_extension("a.heic") == ".heic"
    assert _image_extension(None) == ".jpg"
    assert _image_extension("noext") == ".jpg"
