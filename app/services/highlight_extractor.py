"""Highlight extraction service using DSPy with OpenAI Vision API."""

import logging

import dspy
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.telemetry import add_span_attributes, create_span, set_span_status
from app.models.api_usage import APIUsage, calculate_cost
from app.services.image_utils import convert_to_jpeg
from app.services.text_matching import MatchStatus, locate_highlight

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
    usage: TokenUsage | None = Field(default=None, description="Token usage for this extraction")


class HighlightExtractionSignature(dspy.Signature):
    """Extract text from a book page image.

    You are a precise text extraction assistant. Given an image of a book page:

    1. Extract ALL readable text from the page into `full_text`. Clean up
       any cut-off fragments at the top/bottom but preserve the text faithfully.

    2. Based on the user's instructions, identify the specific highlighted,
       underlined, circled, or requested portion and return it as `highlight_text`.
       This should be a verbatim substring of `full_text`.

    The user may ask for:
    - HIGHLIGHTED TEXT: "highlighted", "underlined", "circled", or "marked" text
    - INSTRUCTION-BASED: "the sentence about love", "first paragraph", etc.

    Rules:
    - Preserve the exact wording from the book - do not paraphrase or modify
    - `highlight_text` must appear verbatim within `full_text`
    - If you can see a page number, include it
    - Rate confidence as "high" (exact match), "medium" (best guess), or "low"
    - Return empty strings with "low" confidence if nothing matches
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


def _build_fallback_lm() -> dspy.LM | None:
    """Build a fallback LM using Groq, if configured."""
    settings = get_settings()
    if not settings.groq_api_key:
        return None
    return dspy.LM(
        settings.vision_fallback_model,
        api_key=settings.groq_api_key,
        max_tokens=2000,
    )


class HighlightExtractorService:
    """Service for extracting highlights from images using DSPy."""

    def __init__(self, lm: dspy.LM | None = None) -> None:
        """Initialize the service.

        Args:
            lm: Optional DSPy language model. If not provided, creates one from settings.
        """
        settings = get_settings()
        self._model_name = settings.vision_model
        if lm is None:
            lm = dspy.LM(
                self._model_name,
                api_key=settings.openai_api_key,
                max_tokens=2000,
            )
        self._lm = lm
        self._fallback_lm = _build_fallback_lm()
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
                    jpeg_bytes = convert_to_jpeg(image_bytes)
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
                # Fallback for errors
                return ExtractedHighlight(
                    full_text="",
                    highlight_text="",
                    confidence="low",
                    page_number=None,
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
    """Dependency that provides the highlight extractor service."""
    return _get_service()
