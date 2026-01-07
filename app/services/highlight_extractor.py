"""Highlight extraction service using OpenAI Vision API."""

import base64
from dataclasses import dataclass
from pathlib import Path

from openai import AsyncOpenAI

from app.core.config import get_settings


@dataclass
class ExtractedHighlight:
    """Extracted highlight from an image."""

    text: str
    confidence: str  # "high", "medium", "low"
    page_number: str | None = None


class HighlightExtractorService:
    """Service for extracting highlights from images using OpenAI Vision."""

    def __init__(self) -> None:
        settings = get_settings()
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)

    @staticmethod
    def _encode_image(image_path: str | Path) -> str:
        """Encode image to base64."""
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode("utf-8")

    @staticmethod
    def _encode_image_bytes(image_bytes: bytes) -> str:
        """Encode image bytes to base64."""
        return base64.b64encode(image_bytes).decode("utf-8")

    @staticmethod
    def _get_image_media_type(filename: str) -> str:
        """Get media type from filename."""
        ext = Path(filename).suffix.lower()
        media_types = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }
        return media_types.get(ext, "image/jpeg")

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
            filename: Original filename (for media type detection)
            instructions: User instructions describing what to extract

        Returns:
            ExtractedHighlight containing the extracted text
        """
        base64_image = self._encode_image_bytes(image_bytes)
        media_type = self._get_image_media_type(filename)

        system_prompt = """You are a precise text extraction assistant. Your job is to extract
specific text from book page images based on user instructions.

You can handle TWO types of requests:

1. HIGHLIGHTED TEXT: If the user asks for "highlighted", "underlined", "circled", or
   "marked" text, look for visually marked passages and extract those.

2. INSTRUCTION-BASED: If the user describes text without referring to visual marks,
   find and extract the matching text. Examples:
   - "grab the sentence about love" → find a sentence mentioning love
   - "extract the first paragraph" → get the first paragraph on the page
   - "get the quote starting with 'In the beginning'" → find that specific quote
   - "the sentence containing 'freedom'" → find a sentence with that word

Instructions:
1. Carefully read the user's instructions to understand what text they want
2. If they mention highlights/marks, look for visually marked text
3. If they describe text content, find the matching passage on the page
4. Preserve the exact wording from the book - do not paraphrase or modify
5. If you can see a page number, include it
6. Rate your confidence as "high" (exact match found), "medium" (best guess), or "low"

Respond in this exact JSON format:
{
    "text": "The extracted text exactly as it appears in the book",
    "confidence": "high|medium|low",
    "page_number": "123 or null if not visible"
}

If you cannot find matching text or cannot read the image clearly, respond with:
{
    "text": "",
    "confidence": "low",
    "page_number": null
}"""

        user_message = f"""Please extract text from this book page image.

User instructions: {instructions}

Remember to:
- Extract the text exactly as written in the book
- Follow the user's instructions to identify which text to extract
- Include the page number if visible"""

        response = await self._client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_message},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{media_type};base64,{base64_image}",
                                "detail": "high",
                            },
                        },
                    ],
                },
            ],
            max_tokens=2000,
            response_format={"type": "json_object"},
        )

        # Parse response
        content = response.choices[0].message.content
        if not content:
            return ExtractedHighlight(text="", confidence="low", page_number=None)

        import json

        try:
            data = json.loads(content)
            return ExtractedHighlight(
                text=data.get("text", ""),
                confidence=data.get("confidence", "low"),
                page_number=data.get("page_number"),
            )
        except json.JSONDecodeError:
            # If JSON parsing fails, treat the whole response as text
            return ExtractedHighlight(text=content, confidence="medium", page_number=None)


# Global instance
highlight_extractor_service = HighlightExtractorService()


async def get_highlight_extractor_service() -> HighlightExtractorService:
    """Dependency that provides the highlight extractor service."""
    return highlight_extractor_service
