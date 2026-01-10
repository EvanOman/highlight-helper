"""Pydantic schemas for API request/response validation."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# Book schemas
class BookCreate(BaseModel):
    """Schema for creating a new book."""

    title: str = Field(..., min_length=1, max_length=500)
    author: str = Field(..., min_length=1, max_length=500)
    isbn: str | None = Field(None, max_length=20)
    cover_url: str | None = Field(None, max_length=1000)


class BookUpdate(BaseModel):
    """Schema for updating a book."""

    title: str | None = Field(None, min_length=1, max_length=500)
    author: str | None = Field(None, min_length=1, max_length=500)
    isbn: str | None = Field(None, max_length=20)
    cover_url: str | None = Field(None, max_length=1000)


class BookResponse(BaseModel):
    """Schema for book response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    author: str
    isbn: str | None
    cover_url: str | None
    created_at: datetime
    highlight_count: int = 0


class BookListResponse(BaseModel):
    """Schema for list of books response."""

    books: list[BookResponse]
    total: int


# Highlight schemas
class HighlightCreate(BaseModel):
    """Schema for creating a new highlight."""

    text: str = Field(..., min_length=1)
    note: str | None = None
    page_number: str | None = Field(None, max_length=50)


class HighlightUpdate(BaseModel):
    """Schema for updating a highlight."""

    text: str | None = Field(None, min_length=1)
    note: str | None = None
    page_number: str | None = Field(None, max_length=50)


class HighlightResponse(BaseModel):
    """Schema for highlight response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    book_id: int
    text: str
    note: str | None
    page_number: str | None
    created_at: datetime
    readwise_id: str | None = None
    synced_at: datetime | None = None


class HighlightWithBookResponse(HighlightResponse):
    """Schema for highlight response with book info."""

    book_title: str
    book_author: str


# Book lookup schemas
class BookSearchResult(BaseModel):
    """Schema for book search result from Google Books API."""

    title: str
    author: str
    isbn: str | None
    cover_url: str | None
    description: str | None


class BookSearchResponse(BaseModel):
    """Schema for book search response."""

    results: list[BookSearchResult]


# Highlight extraction schemas
class ExtractHighlightRequest(BaseModel):
    """Schema for highlight extraction request."""

    instructions: str = Field(
        ...,
        min_length=1,
        description="Instructions describing what highlight to extract from the image",
    )


class ExtractHighlightResponse(BaseModel):
    """Schema for highlight extraction response."""

    text: str
    confidence: str
    page_number: str | None


# Readwise schemas
class ReadwiseStatusResponse(BaseModel):
    """Schema for Readwise integration status."""

    configured: bool
    token_valid: bool | None = None


class ReadwiseSyncResponse(BaseModel):
    """Schema for single highlight sync response."""

    success: bool
    readwise_id: str | None = None
    error: str | None = None


class ReadwiseBatchSyncResponse(BaseModel):
    """Schema for batch sync response."""

    total: int
    synced: int
    failed: int
