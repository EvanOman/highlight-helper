"""Pluggable extraction pipelines for the eval harness.

A pipeline is any object exposing an ``id``, a ``model`` label, and an async
``extract(image_bytes, filename, instruction) -> ExtractionOutput``. The runner
depends only on this protocol, so future pipelines can be A/B'd via the
``--pipeline`` CLI flag without editing the runner. The default pipeline wraps
the app's :class:`HighlightExtractorService`.
"""

from __future__ import annotations

from typing import Protocol

from evals.models import ExtractionOutput


class Pipeline(Protocol):
    """Extraction pipeline the runner can drive and cache against."""

    id: str
    model: str

    async def extract(
        self, image_bytes: bytes, filename: str, instruction: str
    ) -> ExtractionOutput: ...


class ServicePipeline:
    """Default pipeline: the production :class:`HighlightExtractorService`.

    ``enable_cache`` is exposed so eval variants can turn DSPy's disk cache off
    and measure real latency/cost; production keeps it on (harmless — each photo
    is unique and discarded).
    """

    id = "service"
    enable_cache = True

    def __init__(self) -> None:
        # Imported lazily so offline runs never need the app's LLM config.
        from app.core.config import get_settings
        from app.services.highlight_extractor import HighlightExtractorService

        self._service = HighlightExtractorService(enable_cache=self.enable_cache)
        self.model = get_settings().vision_model

    async def extract(
        self, image_bytes: bytes, filename: str, instruction: str
    ) -> ExtractionOutput:
        result = await self._service.extract_highlight(
            image_bytes=image_bytes,
            filename=filename,
            instructions=instruction,
        )
        cost = float(result.usage.cost_usd) if result.usage else 0.0
        return ExtractionOutput(
            full_text=result.full_text,
            highlight_text=result.highlight_text,
            page_number=result.page_number,
            highlight_start=result.highlight_start,
            highlight_end=result.highlight_end,
            match_status=result.match_status,
            match_quality=result.match_quality,
            cost_usd=cost,
        )


class ServiceV2Pipeline(ServicePipeline):
    """W3 measurement pipeline: the same (now-improved) production service, but
    with the DSPy cache OFF so every online run reports genuine latency and cost.

    It carries a distinct ``id`` purely so its cached outputs live in their own
    key namespace and never overwrite or replay the frozen ``service`` baseline.
    Behaviourally it is identical to :class:`ServicePipeline`; the production
    default therefore already ships the improved pipeline.
    """

    id = "service-v2"
    enable_cache = False


# Registry of pipeline factories selectable via --pipeline. Add new pipelines
# here (or register at runtime) to A/B them against the baseline.
PIPELINE_FACTORIES: dict[str, type] = {
    "service": ServicePipeline,
    "service-v2": ServiceV2Pipeline,
}


def build_pipeline(pipeline_id: str) -> Pipeline:
    """Instantiate the named pipeline."""
    factory = PIPELINE_FACTORIES.get(pipeline_id)
    if factory is None:
        known = ", ".join(sorted(PIPELINE_FACTORIES))
        raise ValueError(f"Unknown pipeline '{pipeline_id}'. Known pipelines: {known}")
    return factory()
