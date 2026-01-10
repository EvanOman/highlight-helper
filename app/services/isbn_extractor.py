"""ISBN extraction service using DSPy with OpenAI Vision API."""

import dspy
from pydantic import BaseModel, Field

from app.core.config import get_settings


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
        # Create dspy.Image from bytes
        image = dspy.Image(image_bytes)

        try:
            # Use dspy.context for thread-safe LM configuration
            with dspy.context(lm=self._lm):
                # Use dspy.asyncify for async execution
                async_extract = dspy.asyncify(self._extractor)
                result = await async_extract(image=image)

                # Clean the ISBN (remove any remaining non-digits)
                if result.isbn:
                    result.isbn = "".join(c for c in result.isbn if c.isdigit())

                return result
        except Exception:
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
