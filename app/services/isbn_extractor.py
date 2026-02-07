"""ISBN extraction service using DSPy with OpenAI Vision API."""

import logging

import dspy
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.telemetry import add_span_attributes, create_span, set_span_status
from app.services.image_utils import convert_to_jpeg

logger = logging.getLogger(__name__)


class ExtractedISBN(BaseModel):
    """Extracted ISBN from an image."""

    isbn: str = Field(default="", description="The extracted ISBN (10 or 13 digits)")
    confidence: str = Field(
        default="low", description="Confidence level: 'high', 'medium', or 'low'"
    )
    source: str = Field(
        default="unknown",
        description="Source of ISBN: 'barcode', 'text', or 'unknown'",
    )


class ISBNExtractionSignature(dspy.Signature):
    """Extract ISBN from a book cover or barcode image.

    You are an ISBN extraction assistant. Your job is to find and extract
    ISBN numbers from images of book covers, back covers, or barcodes.

    ISBNs can appear in several forms:
    1. BARCODE: Look for EAN-13 barcodes (usually on back cover). The number
       below or above the barcode starting with 978 or 979 is the ISBN-13.
    2. PRINTED TEXT: Look for text like "ISBN: xxx" or "ISBN-13: xxx" or
       "ISBN-10: xxx" printed on the cover or copyright page.
    3. INFERRED: If you can clearly identify the book, you may recognize
       a well-known edition's ISBN.

    Instructions:
    - Extract ONLY the digits (remove hyphens, spaces, "ISBN" prefix)
    - ISBN-13 has 13 digits, ISBN-10 has 10 digits
    - Prefer ISBN-13 if both are visible
    - Rate confidence as "high" (clear barcode/text), "medium" (partial/unclear),
      or "low" (guessing or not found)
    - Indicate whether the ISBN came from a 'barcode', 'text', or is 'unknown'
    - Return empty isbn with "low" confidence if no ISBN is found
    """

    image: dspy.Image = dspy.InputField()
    result: ExtractedISBN = dspy.OutputField()


class ISBNExtractorModule(dspy.Module):
    """DSPy module for extracting ISBN from book images."""

    def __init__(self):
        super().__init__()
        self.extract = dspy.ChainOfThought(ISBNExtractionSignature)

    def forward(self, image: dspy.Image) -> ExtractedISBN:
        prediction = self.extract(image=image)
        return prediction.result


class ISBNExtractorService:
    """Service for extracting ISBN from images using DSPy."""

    def __init__(self, lm: dspy.LM | None = None) -> None:
        """Initialize the service.

        Args:
            lm: Optional DSPy language model. If not provided, creates one from settings.
        """
        if lm is None:
            settings = get_settings()
            lm = dspy.LM(
                "openai/gpt-5.2",
                api_key=settings.openai_api_key,
                max_tokens=500,
            )
        self._lm = lm
        self._extractor = ISBNExtractorModule()

    async def extract_isbn(
        self,
        image_bytes: bytes,
        filename: str,
    ) -> ExtractedISBN:
        """
        Extract ISBN from a book cover or barcode image.

        Args:
            image_bytes: Raw image bytes
            filename: Original filename (for reference)

        Returns:
            ExtractedISBN containing the extracted ISBN
        """
        with create_span(
            "isbn_extraction",
            {
                "extraction.filename": filename,
                "extraction.image_size_bytes": len(image_bytes),
            },
        ) as span:
            try:
                # Convert to JPEG to handle unusual formats (MPO, HEIC, etc.)
                with create_span("image_conversion", {"input_size": len(image_bytes)}) as conv_span:
                    jpeg_bytes = convert_to_jpeg(image_bytes)
                    conv_span.set_attribute("output_size", len(jpeg_bytes))

                # Parse image for DSPy
                with create_span("dspy_image_parse", {"jpeg_size": len(jpeg_bytes)}):
                    image = dspy.Image(jpeg_bytes)

                add_span_attributes(extraction_jpeg_size_bytes=len(jpeg_bytes))

                # Call the LLM via DSPy
                with create_span("dspy_llm_call", {"model": "openai/gpt-5.2"}) as llm_span:
                    # Use dspy.context for thread-safe LM configuration
                    with dspy.context(lm=self._lm):
                        # Use dspy.asyncify for async execution
                        async_extract = dspy.asyncify(self._extractor)
                        result = await async_extract(image=image)

                    llm_span.set_attribute("result_isbn", result.isbn or "")
                    llm_span.set_attribute("result_confidence", result.confidence)
                    llm_span.set_attribute("result_source", result.source)

                # Clean the ISBN (remove any remaining non-digits)
                if result.isbn:
                    original_isbn = result.isbn
                    result.isbn = "".join(c for c in result.isbn if c.isdigit())
                    if original_isbn != result.isbn:
                        add_span_attributes(isbn_cleaned=True, isbn_original=original_isbn)

                # Add final result to span
                add_span_attributes(
                    extraction_isbn=result.isbn or "",
                    extraction_confidence=result.confidence,
                    extraction_source=result.source,
                )
                set_span_status(True)
                logger.info(
                    f"ISBN extraction: {result.isbn or 'none'} (confidence: {result.confidence})"
                )
                return result

            except Exception as e:
                logger.error(f"ISBN extraction failed: {e}")
                span.record_exception(e)
                set_span_status(False, str(e))
                # Fallback for errors
                return ExtractedISBN(
                    isbn="",
                    confidence="low",
                    source="unknown",
                )


# Lazy initialization to avoid configuration issues at import time
_isbn_extractor_service: ISBNExtractorService | None = None


def _get_service() -> ISBNExtractorService:
    """Get or create the singleton service instance."""
    global _isbn_extractor_service
    if _isbn_extractor_service is None:
        _isbn_extractor_service = ISBNExtractorService()
    return _isbn_extractor_service


async def get_isbn_extractor_service() -> ISBNExtractorService:
    """Dependency that provides the ISBN extractor service."""
    return _get_service()
