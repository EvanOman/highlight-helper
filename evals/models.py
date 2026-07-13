"""Data models for the evaluation framework.

An :class:`EvalCase` carries ground truth known *by construction* (the dataset
generator composites a highlight at a known character span). A pipeline produces
an :class:`ExtractionOutput`; scoring compares the two into an :class:`EvalResult`.
:class:`MetricSummary` rolls results up (overall and per category tag) and
:class:`EvalReport` is the whole run.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class EvalCase:
    """A single evaluation case with ground truth known by construction."""

    id: str
    image_path: str
    instruction: str
    full_text: str  # the clean, faithful page text
    expected_highlight: str  # verbatim substring of full_text ("" for negatives)
    expected_start: int  # char offset into full_text (0 for negatives)
    expected_end: int
    expected_page_number: str | None = None
    modality: str = "marker"  # marker | underline | instruction | none
    difficulty: str = "clean"  # clean | warped | degraded
    density: str = "short"  # short | dense
    edge_case: str | None = None  # hyphenated | repeated-phrase | multi-sentence | ambiguous
    is_negative: bool = False
    description: str = ""
    # Augmentation provenance (additive phone-photo variants; see
    # evals.augment_dataset). Absent on the 48 original cases.
    parent_id: str | None = None
    augmentation: str | None = None  # easy | medium | hard

    @property
    def tags(self) -> list[str]:
        """Category tags this case rolls up under.

        Augmented cases keep every parent label (modality/difficulty/density/edge)
        *and* gain an ``augmentation:{level}`` tag, so rollups slice both ways.
        """
        tags = [
            f"modality:{self.modality}",
            f"difficulty:{self.difficulty}",
            f"density:{self.density}",
        ]
        if self.edge_case:
            tags.append(f"edge:{self.edge_case}")
        if self.is_negative:
            tags.append("edge:negative")
        if self.augmentation:
            tags.append(f"augmentation:{self.augmentation}")
        return tags

    @property
    def expected_span(self) -> tuple[int, int]:
        return (self.expected_start, self.expected_end)

    def load_image_bytes(self, base_path: Path | None = None) -> bytes:
        path = Path(self.image_path)
        if base_path and not path.is_absolute():
            path = base_path / path
        return path.read_bytes()

    @classmethod
    def from_dict(cls, data: dict) -> EvalCase:
        return cls(
            id=data["id"],
            image_path=data["image_path"],
            instruction=data["instruction"],
            full_text=data["full_text"],
            expected_highlight=data["expected_highlight"],
            expected_start=data["expected_start"],
            expected_end=data["expected_end"],
            expected_page_number=data.get("expected_page_number"),
            modality=data.get("modality", "marker"),
            difficulty=data.get("difficulty", "clean"),
            density=data.get("density", "short"),
            edge_case=data.get("edge_case"),
            is_negative=data.get("is_negative", False),
            description=data.get("description", ""),
            parent_id=data.get("parent_id"),
            augmentation=data.get("augmentation"),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ExtractionOutput:
    """What a pipeline returns for one image. Decoupled from the app service so
    the cache stores genuine model outputs and future pipelines can plug in."""

    full_text: str = ""
    highlight_text: str = ""
    page_number: str | None = None
    highlight_start: int = 0
    highlight_end: int = 0
    match_status: str = "not_found"
    match_quality: float = 0.0
    cost_usd: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> ExtractionOutput:
        return cls(
            full_text=data.get("full_text", ""),
            highlight_text=data.get("highlight_text", ""),
            page_number=data.get("page_number"),
            highlight_start=data.get("highlight_start", 0),
            highlight_end=data.get("highlight_end", 0),
            match_status=data.get("match_status", "not_found"),
            match_quality=data.get("match_quality", 0.0),
            cost_usd=data.get("cost_usd", 0.0),
        )


@dataclass
class EvalResult:
    """Scored result for one case. Metrics that don't apply to a case are None
    (e.g. F1/IoU on a negative case; hallucination on a positive case)."""

    case_id: str
    tags: list[str]
    is_negative: bool
    expected_highlight: str
    actual_highlight: str
    match_status: str
    latency_ms: float
    cost_usd: float
    full_text_cer: float
    highlight_f1: float | None = None
    span_iou: float | None = None
    span_located: bool | None = None
    verbatim: bool | None = None
    page_number_correct: bool | None = None
    hallucinated: bool | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _mean_or_none(values: list[float]) -> float | None:
    """Mean, or None when no value applies to the group (renders as '—')."""
    return sum(values) / len(values) if values else None


@dataclass
class MetricSummary:
    """Aggregate metrics over a set of results (overall or one category tag).

    Metrics that don't apply to any case in the group are None (e.g. F1/IoU on
    an all-negative group, hallucination on an all-positive group) and render as
    '—' rather than a misleading 0.0.
    """

    label: str
    n_cases: int
    highlight_f1: float | None
    span_iou: float | None
    span_located_rate: float | None
    verbatim_rate: float | None
    full_text_cer: float
    page_number_accuracy: float | None
    hallucination_rate: float | None
    latency_p50_ms: float
    cost_per_case_usd: float

    @classmethod
    def from_results(cls, label: str, results: list[EvalResult]) -> MetricSummary:
        from evals.metrics import percentile

        def collect(attr: str) -> list[float]:
            return [
                float(getattr(r, attr))
                for r in results
                if getattr(r, attr) is not None and r.error is None
            ]

        return cls(
            label=label,
            n_cases=len(results),
            highlight_f1=_mean_or_none(collect("highlight_f1")),
            span_iou=_mean_or_none(collect("span_iou")),
            span_located_rate=_mean_or_none(collect("span_located")),
            verbatim_rate=_mean_or_none(collect("verbatim")),
            full_text_cer=_mean([r.full_text_cer for r in results if r.error is None]),
            page_number_accuracy=_mean_or_none(collect("page_number_correct")),
            hallucination_rate=_mean_or_none(collect("hallucinated")),
            latency_p50_ms=percentile([r.latency_ms for r in results], 50),
            cost_per_case_usd=_mean([r.cost_usd for r in results]),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EvalReport:
    """A full evaluation run: overall + per-tag rollups plus every result."""

    timestamp: datetime
    mode: str  # "online" | "offline"
    pipeline_id: str
    model: str
    overall: MetricSummary
    by_tag: dict[str, MetricSummary]
    results: list[EvalResult] = field(default_factory=list)
    total_cost_usd: float = 0.0
    error_cases: int = 0

    def to_json_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "mode": self.mode,
            "pipeline_id": self.pipeline_id,
            "model": self.model,
            "total_cost_usd": self.total_cost_usd,
            "error_cases": self.error_cases,
            "overall": self.overall.to_dict(),
            "by_tag": {k: v.to_dict() for k, v in self.by_tag.items()},
            "results": [r.to_dict() for r in self.results],
        }
