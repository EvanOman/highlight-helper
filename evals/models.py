"""Data models for the evaluation framework."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class EvalCase:
    """A single evaluation test case."""

    id: str
    image_path: str
    instruction: str
    expected_text: str
    expected_page_number: str | None = None
    category: str = "general"  # e.g., "highlighted", "instruction-based", "edge-case"
    description: str = ""

    def load_image_bytes(self, base_path: Path | None = None) -> bytes:
        """Load the image bytes from disk."""
        path = Path(self.image_path)
        if base_path and not path.is_absolute():
            path = base_path / path
        return path.read_bytes()


@dataclass
class EvalResult:
    """Result of running a single evaluation case."""

    case_id: str
    expected_text: str
    actual_text: str
    expected_page_number: str | None
    actual_page_number: str | None
    confidence: str
    exact_match: bool
    char_accuracy: float  # 0.0 to 1.0
    latency_ms: float
    error: str | None = None

    @property
    def passed(self) -> bool:
        """Consider passed if char accuracy > 0.9 or exact match."""
        return self.exact_match or self.char_accuracy >= 0.9


@dataclass
class EvalReport:
    """Summary report of an evaluation run."""

    timestamp: datetime
    total_cases: int
    passed_cases: int
    failed_cases: int
    error_cases: int
    avg_char_accuracy: float
    avg_latency_ms: float
    results: list[EvalResult] = field(default_factory=list)
    mode: str = "online"  # "online" or "offline"

    @property
    def pass_rate(self) -> float:
        """Calculate the pass rate as a percentage."""
        if self.total_cases == 0:
            return 0.0
        return (self.passed_cases / self.total_cases) * 100

    @property
    def success(self) -> bool:
        """Report is successful if pass rate >= 80%."""
        return self.pass_rate >= 80.0
