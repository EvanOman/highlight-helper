"""Highlight extraction service using DSPy with OpenAI Vision API."""

import dspy
from pydantic import BaseModel, Field

from app.core.config import get_settings


class ExtractedHighlight(BaseModel):
    """Extracted highlight from an image."""

    text: str = Field(default="", description="The extracted text exactly as it appears")
    confidence: str = Field(
        default="low", description="Confidence level: 'high', 'medium', or 'low'"
    )
    page_number: str | None = Field(default=None, description="Page number if visible in the image")


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
                max_tokens=2000,
            )
        self._lm = lm
        self._extractor = HighlightExtractorModule()

    async def extract_highlight(
        self,
        image_bytes: bytes,
        filename: str,
        instructions: str,
    ) -> ExtractedHighlight:
        """
        Extract highlighted text from an image.

        Args:
            image_bytes: Raw image bytes
            filename: Original filename (for reference)
            instructions: User instructions describing what to extract

        Returns:
            ExtractedHighlight containing the extracted text
        """
        # Create dspy.Image from bytes
        image = dspy.Image(image_bytes)

        try:
            # Use dspy.context for thread-safe LM configuration
            with dspy.context(lm=self._lm):
                # Use dspy.asyncify for async execution
                async_extract = dspy.asyncify(self._extractor)
                result = await async_extract(image=image, user_instructions=instructions)
                return result
        except Exception:
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
