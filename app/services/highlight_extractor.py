"""Highlight extraction service using DSPy with OpenAI Vision API."""

import logging

import dspy
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.telemetry import add_span_attributes, create_span, set_span_status
from app.models.api_usage import APIUsage, calculate_cost
from app.services.image_utils import prepare_image_for_vision
from app.services.text_matching import MatchResult, MatchStatus, locate_highlight

logger = logging.getLogger(__name__)


class TokenUsage(BaseModel):
    """Token usage information from an API call."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    model: str = ""


class ExtractedHighlight(BaseModel):
    """Extracted highlight from an image."""

    full_text: str = Field(default="", description="All readable text from the page, cleaned up")
    highlight_text: str = Field(default="", description="The specific highlighted/selected portion")
    confidence: str = Field(
        default="low", description="Confidence level: 'high', 'medium', or 'low'"
    )
    page_number: str | None = Field(default=None, description="Page number if visible in the image")
    highlight_start: int = Field(
        default=0, description="Character offset of highlight in full_text"
    )
    highlight_end: int = Field(default=0, description="Character end offset")
    match_status: str = Field(
        default=MatchStatus.NOT_FOUND.value,
        description="How the highlight was located in full_text: exact, normalized, fuzzy, or not_found",
    )
    match_quality: float = Field(
        default=0.0, description="Similarity (0.0-1.0) of the located span vs highlight_text"
    )
    error: str | None = Field(
        default=None,
        description=(
            "Populated only when extraction itself failed (model/transport error). "
            "None on success, including a genuinely blank page. Lets callers tell "
            "'the model failed' apart from 'nothing was highlighted'."
        ),
    )
    usage: TokenUsage | None = Field(default=None, description="Token usage for this extraction")


class HighlightExtractionSignature(dspy.Signature):
    """Extract text from a book page image.

    You are a precise text extraction assistant. Given an image of a book page:

    1. Transcribe ALL readable text on the page into `full_text`. Read the whole
       page top to bottom, including dense or tightly-set paragraphs; do not stop
       early. Transcribe the page FAITHFULLY: keep line breaks and, when a word
       is split across a line break with a hyphen (e.g. "beau-" at the end of one
       line and "tiful" at the start of the next), keep that hyphen and break in
       `full_text` exactly as printed. Only trim fragments cut off at the very
       top or bottom edge of the image.

    2. Based on the user's instructions, identify the specific highlighted,
       underlined, circled, or requested portion and return it as `highlight_text`.

    The user may ask for:
    - HIGHLIGHTED TEXT: "highlighted", "underlined", "circled", or "marked" text
    - INSTRUCTION-BASED: "the sentence about love", "first paragraph", etc.

    Rules for `highlight_text`:
    - Preserve the book's exact wording — never paraphrase, reorder, or reword.
    - MATCH THE MARK'S BOUNDARIES. Return exactly the words the marking covers —
      no more, no less. Do not round the selection out to the start or end of the
      sentence, and do not append a trailing comma, period, semicolon, or other
      punctuation that sits outside the marked words. Equally, do not drop a
      marked word at the start or end just because it is small.
    - REJOIN HYPHENATED WORDS. If the marked passage includes a word split across
      a line break by a hyphen, write that word closed up as it reads in
      `highlight_text` ("beau-tiful" across a line break becomes "beautiful"),
      and drop the intervening line break. `full_text` still shows the split form
      (rule 1); `highlight_text` shows the natural reading form.
    - PICK THE MARKED OCCURRENCE. If the same phrase appears several times on the
      page, return only the single occurrence that is actually marked — judge by
      the surrounding words, not by returning the first match or a longer span.
    - UNDERLINES sit beneath the words: read the text directly above the line and
      return those words verbatim.

    Other rules:
    - If you can see a page number, include it.
    - Rate confidence as "high" (exact match), "medium" (best guess), or "low".
    - If nothing on the page matches the request, return empty strings with
      "low" confidence — never invent text that is not on the page.
    """

    image: dspy.Image = dspy.InputField()
    user_instructions: str = dspy.InputField()
    result: ExtractedHighlight = dspy.OutputField()


class HighlightExtractorModule(dspy.Module):
    """DSPy module for extracting highlights from book page images."""

    def __init__(self):
        super().__init__()
        self.extract = dspy.ChainOfThought(HighlightExtractionSignature)

    def forward(self, image: dspy.Image, user_instructions: str) -> dspy.Prediction:
        return self.extract(image=image, user_instructions=user_instructions)


def _build_fallback_lm(max_tokens: int, cache: bool) -> dspy.LM | None:
    """Build a fallback LM using Groq, if configured."""
    settings = get_settings()
    if not settings.groq_api_key:
        return None
    return dspy.LM(
        settings.vision_fallback_model,
        api_key=settings.groq_api_key,
        max_tokens=max_tokens,
        cache=cache,
    )


def _repair_locate(full_text: str, highlight_text: str) -> MatchResult | None:
    """One cheap, deterministic repair pass for an unlocatable highlight.

    Runs only after :func:`locate_highlight` returns ``NOT_FOUND``. The model
    occasionally brackets the real passage with a stray token — an OCR variant
    word, or a fragment just outside the mark — that drags the whole span below
    the fuzzy threshold. We trim up to two words from each end and re-locate,
    returning the best-quality locatable core. Returns ``None`` when nothing
    locatable is found, so the caller keeps the honest ``NOT_FOUND`` rather than
    inventing a span. No LLM call, so it adds no cost or latency to the common
    (already-located) path.
    """
    words = highlight_text.split()
    if len(words) < 4:
        return None
    best: MatchResult | None = None
    for lead in range(3):  # drop 0, 1 or 2 leading words
        for trail in range(3):  # drop 0, 1 or 2 trailing words
            if lead == 0 and trail == 0:
                continue  # the full string already failed
            core = words[lead : len(words) - trail]
            if len(core) < 2:
                continue
            match = locate_highlight(full_text, " ".join(core))
            if match.status is not MatchStatus.NOT_FOUND and (
                best is None or match.quality > best.quality
            ):
                best = match
    return best


class HighlightExtractorService:
    """Service for extracting highlights from images using DSPy."""

    def __init__(self, lm: dspy.LM | None = None, *, enable_cache: bool = True) -> None:
        """Initialize the service.

        Args:
            lm: Optional DSPy language model. If not provided, creates one from settings.
            enable_cache: Whether the DSPy LM caches responses on disk. Production
                keeps this on (harmless: each photo is unique and discarded).
                The eval harness turns it OFF so repeated runs report real
                latency and cost instead of replaying a cached response.
        """
        settings = get_settings()
        self._model_name = settings.vision_model
        max_tokens = settings.vision_max_tokens
        if lm is None:
            lm = dspy.LM(
                self._model_name,
                api_key=settings.openai_api_key,
                max_tokens=max_tokens,
                cache=enable_cache,
            )
        self._lm = lm
        self._fallback_lm = _build_fallback_lm(max_tokens, enable_cache)
        self._extractor = HighlightExtractorModule()

    def _extract_usage_from_lm(self, lm: dspy.LM, model_name: str) -> TokenUsage | None:
        """Extract token usage from a specific LM's history."""
        try:
            if not lm.history:
                return None

            last_entry = lm.history[-1]
            usage_data = last_entry.get("usage", {})

            if not usage_data:
                return None

            input_tokens = usage_data.get("prompt_tokens", 0) or usage_data.get("input_tokens", 0)
            output_tokens = usage_data.get("completion_tokens", 0) or usage_data.get(
                "output_tokens", 0
            )
            total_tokens = usage_data.get("total_tokens", 0) or (input_tokens + output_tokens)

            cost = calculate_cost(model_name, input_tokens, output_tokens)

            return TokenUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                cost_usd=cost,
                model=model_name,
            )
        except Exception as e:
            logger.warning(f"Failed to extract usage from history: {e}")
            return None

    async def _call_extractor(
        self, image: dspy.Image, instructions: str, lm: dspy.LM
    ) -> ExtractedHighlight:
        """Run the extractor with a specific LM and return the result."""
        with dspy.context(lm=lm, track_usage=True):
            async_extract = dspy.asyncify(self._extractor)
            prediction = await async_extract(image=image, user_instructions=instructions)
        result: ExtractedHighlight = prediction.result

        # Compute highlight offsets within full_text. On NOT_FOUND the offsets
        # are the (0, 0) sentinel — never a whole-page span.
        if result.full_text and result.highlight_text:
            match = locate_highlight(result.full_text, result.highlight_text)
            # Verbatim self-check + one cheap repair: if the highlight can't be
            # located, try trimming stray edge tokens before giving up.
            if match.status is MatchStatus.NOT_FOUND:
                repaired = _repair_locate(result.full_text, result.highlight_text)
                if repaired is not None:
                    match = repaired
            result.highlight_start = match.start
            result.highlight_end = match.end
            result.match_status = match.status.value
            result.match_quality = match.quality

        return result

    async def extract_highlight(
        self,
        image_bytes: bytes,
        filename: str,
        instructions: str,
        db: AsyncSession | None = None,
        highlight_id: int | None = None,
    ) -> ExtractedHighlight:
        """
        Extract highlighted text from an image.

        Args:
            image_bytes: Raw image bytes
            filename: Original filename (for reference)
            instructions: User instructions describing what to extract
            db: Optional database session for storing usage data
            highlight_id: Optional highlight ID to associate with usage

        Returns:
            ExtractedHighlight containing the extracted text and usage info
        """
        with create_span(
            "highlight_extraction",
            {
                "extraction.filename": filename,
                "extraction.image_size_bytes": len(image_bytes),
                "extraction.instructions_length": len(instructions),
                "extraction.instructions": instructions[:200],  # Truncate for span
            },
        ) as span:
            try:
                # Convert to JPEG to handle unusual formats (MPO, HEIC, etc.)
                with create_span("image_conversion", {"input_size": len(image_bytes)}) as conv_span:
                    jpeg_bytes = prepare_image_for_vision(image_bytes)
                    conv_span.set_attribute("output_size", len(jpeg_bytes))
                    conv_span.set_attribute(
                        "size_reduction_pct",
                        round((1 - len(jpeg_bytes) / len(image_bytes)) * 100, 1)
                        if image_bytes
                        else 0,
                    )

                # Parse image for DSPy
                with create_span("dspy_image_parse", {"jpeg_size": len(jpeg_bytes)}):
                    image = dspy.Image(jpeg_bytes)

                add_span_attributes(extraction_jpeg_size_bytes=len(jpeg_bytes))

                # Call the LLM via DSPy (with fallback)
                model_used = self._model_name
                lm_used = self._lm
                with create_span(
                    "dspy_llm_call",
                    {
                        "model": self._model_name,
                        "instructions_preview": instructions[:100],
                    },
                ) as llm_span:
                    try:
                        result = await self._call_extractor(image, instructions, self._lm)
                    except Exception as primary_err:
                        if self._fallback_lm is None:
                            raise
                        settings = get_settings()
                        model_used = settings.vision_fallback_model
                        lm_used = self._fallback_lm
                        logger.warning(
                            f"Primary vision model failed: {primary_err}. "
                            f"Falling back to {model_used}."
                        )
                        llm_span.set_attribute("primary_model_error", str(primary_err))
                        llm_span.set_attribute("fallback_model", model_used)
                        result = await self._call_extractor(image, instructions, self._fallback_lm)

                    llm_span.set_attribute("model_used", model_used)
                    llm_span.set_attribute(
                        "result_text_preview",
                        result.highlight_text[:200] if result.highlight_text else "",
                    )
                    llm_span.set_attribute("result_full_text_length", len(result.full_text))
                    llm_span.set_attribute("result_confidence", result.confidence)

                # Extract usage info (outside LLM span)
                with create_span("extract_usage_info") as usage_span:
                    usage = self._extract_usage_from_lm(lm_used, model_used)
                    if usage:
                        result.usage = usage
                        logger.info(
                            f"Extraction used {usage.total_tokens} tokens "
                            f"(${usage.cost_usd:.6f}, model: {model_used})"
                        )

                        # Add usage to span attributes
                        usage_span.set_attribute("input_tokens", usage.input_tokens)
                        usage_span.set_attribute("output_tokens", usage.output_tokens)
                        usage_span.set_attribute("total_tokens", usage.total_tokens)
                        usage_span.set_attribute("cost_usd", float(usage.cost_usd))
                        add_span_attributes(
                            extraction_input_tokens=usage.input_tokens,
                            extraction_output_tokens=usage.output_tokens,
                            extraction_total_tokens=usage.total_tokens,
                            extraction_cost_usd=float(usage.cost_usd),
                        )

                        # Store usage in database if session provided
                        if db is not None:
                            with create_span("store_api_usage"):
                                api_usage = APIUsage(
                                    model=usage.model,
                                    operation="highlight_extraction",
                                    input_tokens=usage.input_tokens,
                                    output_tokens=usage.output_tokens,
                                    total_tokens=usage.total_tokens,
                                    cost_usd=usage.cost_usd,
                                    highlight_id=highlight_id,
                                )
                                db.add(api_usage)
                                await db.flush()  # Let request handler manage commit

                # Add result attributes to parent span
                add_span_attributes(
                    extraction_confidence=result.confidence,
                    extraction_text_length=len(result.highlight_text),
                    extraction_full_text_length=len(result.full_text),
                    extraction_has_page_number=result.page_number is not None,
                    extraction_model_used=model_used,
                )
                set_span_status(True)
                return result
            except Exception as e:
                logger.error(f"Extraction failed: {e}")
                span.record_exception(e)
                set_span_status(False, str(e))
                # Typed failure: an empty result whose `error` field distinguishes
                # a model/transport failure from a genuinely blank page (error=None).
                return ExtractedHighlight(
                    full_text="",
                    highlight_text="",
                    confidence="low",
                    page_number=None,
                    error=str(e),
                )


# Lazy initialization to avoid configuration issues at import time
_highlight_extractor_service: HighlightExtractorService | None = None


def _get_service() -> HighlightExtractorService:
    """Get or create the singleton service instance."""
    global _highlight_extractor_service
    if _highlight_extractor_service is None:
        _highlight_extractor_service = HighlightExtractorService()
    return _highlight_extractor_service


async def get_highlight_extractor_service() -> HighlightExtractorService:
    """Dependency that provides the highlight extractor service.

    Under FAKE_LLM (full-stack self-tests) a deterministic fake is served
    instead, so the add-highlight flow can run end-to-end with no API calls.
    """
    if get_settings().fake_llm:
        from app.services.llm_fake import FakeHighlightExtractorService

        return FakeHighlightExtractorService()  # type: ignore[return-value]
    return _get_service()
