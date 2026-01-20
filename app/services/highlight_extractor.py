"""Highlight extraction service using DSPy with OpenAI Vision API."""

import io
import logging

import dspy
from PIL import Image
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.telemetry import add_span_attributes, create_span, set_span_status
from app.models.api_usage import APIUsage, calculate_cost

logger = logging.getLogger(__name__)


def convert_to_jpeg(image_bytes: bytes) -> bytes:
    """Convert image bytes to JPEG format for compatibility.

    Handles formats like MPO, HEIC, etc. that may not be recognized by dspy.Image.
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))
        # Convert to RGB if necessary (handles RGBA, P mode, etc.)
        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")
        elif img.mode != "RGB":
            img = img.convert("RGB")

        # Save as JPEG
        output = io.BytesIO()
        img.save(output, format="JPEG", quality=95)
        return output.getvalue()
    except Exception:
        # If conversion fails, return original bytes and let dspy handle it
        return image_bytes


class TokenUsage(BaseModel):
    """Token usage information from an API call."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    model: str = ""


class ExtractedHighlight(BaseModel):
    """Extracted highlight from an image."""

    text: str = Field(default="", description="The extracted text exactly as it appears")
    confidence: str = Field(
        default="low", description="Confidence level: 'high', 'medium', or 'low'"
    )
    page_number: str | None = Field(default=None, description="Page number if visible in the image")
    usage: TokenUsage | None = Field(default=None, description="Token usage for this extraction")


class HighlightExtractionSignature(dspy.Signature):
    """Extract text from a book page image based on user instructions.

    You are a precise text extraction assistant. Your job is to extract
    specific text from book page images based on user instructions.

    You can handle TWO types of requests:

    1. HIGHLIGHTED TEXT: If the user asks for "highlighted", "underlined",
       "circled", or "marked" text, look for visually marked passages.

    2. INSTRUCTION-BASED: If the user describes text without referring to
       visual marks, find and extract the matching text. Examples:
       - "grab the sentence about love" -> find a sentence mentioning love
       - "extract the first paragraph" -> get the first paragraph
       - "get the quote starting with 'In the beginning'" -> find that quote

    Instructions:
    - Preserve the exact wording from the book - do not paraphrase or modify
    - If you can see a page number, include it
    - Rate confidence as "high" (exact match), "medium" (best guess), or "low"
    - Return empty text with "low" confidence if nothing matches
    """

    image: dspy.Image = dspy.InputField()
    user_instructions: str = dspy.InputField()
    result: ExtractedHighlight = dspy.OutputField()


class HighlightExtractorModule(dspy.Module):
    """DSPy module for extracting highlights from book page images."""

    def __init__(self):
        super().__init__()
        self.extract = dspy.ChainOfThought(HighlightExtractionSignature)

    def forward(self, image: dspy.Image, user_instructions: str) -> ExtractedHighlight:
        prediction = self.extract(image=image, user_instructions=user_instructions)
        return prediction.result


class HighlightExtractorService:
    """Service for extracting highlights from images using DSPy."""

    MODEL_NAME = "openai/gpt-5.2"

    def __init__(self, lm: dspy.LM | None = None) -> None:
        """Initialize the service.

        Args:
            lm: Optional DSPy language model. If not provided, creates one from settings.
        """
        if lm is None:
            settings = get_settings()
            lm = dspy.LM(
                self.MODEL_NAME,
                api_key=settings.openai_api_key,
                max_tokens=2000,
            )
        self._lm = lm
        self._extractor = HighlightExtractorModule()

    def _extract_usage_from_history(self) -> TokenUsage | None:
        """Extract token usage from the LM's history.

        Returns:
            TokenUsage object if usage info found, None otherwise.
        """
        try:
            if not self._lm.history:
                return None

            # Get the most recent entry
            last_entry = self._lm.history[-1]
            usage_data = last_entry.get("usage", {})

            if not usage_data:
                return None

            input_tokens = usage_data.get("prompt_tokens", 0) or usage_data.get("input_tokens", 0)
            output_tokens = usage_data.get("completion_tokens", 0) or usage_data.get(
                "output_tokens", 0
            )
            total_tokens = usage_data.get("total_tokens", 0) or (input_tokens + output_tokens)

            # Calculate cost
            cost = calculate_cost(self.MODEL_NAME, input_tokens, output_tokens)

            return TokenUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                cost_usd=cost,
                model=self.MODEL_NAME,
            )
        except Exception as e:
            logger.warning(f"Failed to extract usage from history: {e}")
            return None

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

                # Call the LLM via DSPy
                with create_span(
                    "dspy_llm_call",
                    {
                        "model": self.MODEL_NAME,
                        "instructions_preview": instructions[:100],
                    },
                ) as llm_span:
                    # Use dspy.context for thread-safe LM configuration with usage tracking
                    with dspy.context(lm=self._lm, track_usage=True):
                        # Use dspy.asyncify for async execution
                        async_extract = dspy.asyncify(self._extractor)
                        result = await async_extract(image=image, user_instructions=instructions)

                    # Add result preview to LLM span
                    llm_span.set_attribute(
                        "result_text_preview", result.text[:200] if result.text else ""
                    )
                    llm_span.set_attribute("result_confidence", result.confidence)

                # Extract usage info (outside LLM span)
                with create_span("extract_usage_info") as usage_span:
                    usage = self._extract_usage_from_history()
                    if usage:
                        result.usage = usage
                        logger.info(
                            f"Extraction used {usage.total_tokens} tokens (${usage.cost_usd:.6f})"
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
                    extraction_text_length=len(result.text),
                    extraction_has_page_number=result.page_number is not None,
                )
                set_span_status(True)
                return result
            except Exception as e:
                logger.error(f"Extraction failed: {e}")
                span.record_exception(e)
                set_span_status(False, str(e))
                # Fallback for errors
                return ExtractedHighlight(
                    text="",
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
