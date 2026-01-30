# Implementation Plan: Notes Feature (Issue #35)

## Issue Summary

Add standalone notes feature that allows users to:
1. Add notes outside of highlight context (notes require only page number, not highlight text)
2. Display notes alongside highlights with visual differentiation
3. Export both highlights and notes to Markdown/Obsidian format

## Current Architecture Analysis

### Data Model
- `Highlight` model (`app/models/highlight.py`):
  - `id`, `book_id`, `text` (required), `note`, `page_number`
  - Readwise sync fields: `readwise_id`, `synced_at`, `sync_status`
  - Relationship to `Book`

- `Book` model (`app/models/book.py`):
  - `id`, `title`, `author`, `isbn`, `cover_url`, `created_at`
  - One-to-many relationship with `Highlight`

### Key Observations
1. Current `Highlight.text` is required (`nullable=False`)
2. Notes are stored as optional `note` field on highlights
3. No standalone note support exists
4. No export functionality exists (mentioned in README roadmap)
5. Readwise integration uses `readwise_sdk` with `SimpleHighlight` objects

## Design Decisions

### Option A: Extend Highlight Model (Recommended)
Add a `type` field to distinguish highlights from notes:
- Less database schema complexity
- Reuses existing UI patterns
- Single table for all book annotations
- Easier to maintain sort order by page

### Option B: Separate Note Model
Create a new `Note` model parallel to `Highlight`:
- More explicit separation
- More complex queries for combined views
- Duplicates much of the highlight infrastructure

**Decision: Option A** - Add a `type` field to the existing `Highlight` model

## Implementation Plan

### Phase 1: Database Schema Changes

#### 1.1 Update Highlight Model (`app/models/highlight.py`)

Add an enum and type field:

```python
class AnnotationType(str, Enum):
    """Type of annotation."""
    HIGHLIGHT = "highlight"
    NOTE = "note"
```

Update `Highlight` class:
- Add `type: Mapped[AnnotationType]` field with default `HIGHLIGHT`
- Make `text` field nullable (for notes, text is optional)
- Ensure backward compatibility with existing data

#### 1.2 Database Migration

Create migration to:
1. Add `type` column with default `'highlight'`
2. Update existing rows to have type='highlight'
3. Make `text` column nullable

**Files to modify:**
- `app/models/highlight.py`
- `app/models/__init__.py` (export new enum)
- Create Alembic migration (or use init_db for simple SQLite)

### Phase 2: API Schema Changes

#### 2.1 Update Pydantic Schemas (`app/api/schemas.py`)

```python
class NoteCreate(BaseModel):
    """Schema for creating a standalone note."""
    page_number: str = Field(..., min_length=1, max_length=50)
    text: str | None = None  # Optional content for the note
    note: str  # The actual note content (required for notes)

class HighlightResponse(BaseModel):
    # Add type field
    type: str  # "highlight" or "note"
    # ... existing fields
```

**Files to modify:**
- `app/api/schemas.py`

### Phase 3: API Route Updates

#### 3.1 Update Highlight Routes (`app/api/highlights.py`)

Add endpoint for creating notes:
```python
@router.post("/book/{book_id}/note", response_model=HighlightResponse)
async def create_note(book_id: int, note_data: NoteCreate, ...)
```

Update list endpoints to include type field in response.

#### 3.2 Update Views (`app/api/views.py`)

- Add `add_note_page` view for standalone note creation
- Update `book_detail` to show notes differentiated from highlights
- Update `all_highlights` to show both with visual distinction

**Files to modify:**
- `app/api/highlights.py`
- `app/api/views.py`

### Phase 4: UI Templates

#### 4.1 New Template: `add_note.html`

Create a simplified form for notes:
- Page number (required)
- Note content (required textarea)
- Optional highlight text (if they want to quote something)

#### 4.2 Update `book_detail.html`

- Add "Add Note" button alongside "Add Highlight"
- Visual differentiation for notes vs highlights:
  - Highlights: yellow border, quote styling
  - Notes: blue/gray border, different icon (e.g., pencil or sticky note)
- Sort by page number option
- Filter by type option (nice-to-have)

#### 4.3 Update `all_highlights.html`

- Show type indicator for each item
- Visual differentiation consistent with book detail

**Files to modify/create:**
- Create: `app/templates/add_note.html`
- Modify: `app/templates/book_detail.html`
- Modify: `app/templates/all_highlights.html`

### Phase 5: Export Feature

#### 5.1 Create Export Service (`app/services/export.py`)

```python
class ExportService:
    """Service for exporting highlights and notes."""

    async def export_book_to_markdown(
        self,
        book: Book,
        annotations: list[Highlight]
    ) -> str:
        """Export a book's annotations to Markdown format."""

    async def export_all_to_markdown(
        self,
        books: list[Book]
    ) -> str:
        """Export all books to a single Markdown file."""

    async def export_to_obsidian(
        self,
        book: Book,
        annotations: list[Highlight]
    ) -> str:
        """Export in Obsidian-compatible format with frontmatter."""
```

#### 5.2 Markdown Format

```markdown
# Book Title
**Author:** Author Name
**ISBN:** 1234567890

## Highlights & Notes

### Page 42

> "This is the highlighted text from the book."

*Note: My thoughts about this highlight*

---

### Page 55 (Note)

My standalone note about this section of the book.

---
```

#### 5.3 Obsidian Format

```markdown
---
title: "Book Title"
author: "Author Name"
isbn: "1234567890"
type: book-notes
date_exported: 2026-01-30
tags:
  - book-notes
  - highlights
---

# Book Title
by Author Name

## Annotations

### Page 42

> "This is the highlighted text from the book."

**Note:** My thoughts about this highlight

---

### Page 55 (Note)

My standalone note about this section of the book.
```

#### 5.4 Export API Routes (`app/api/export.py`)

```python
@router.get("/book/{book_id}/export/markdown")
async def export_book_markdown(book_id: int, db: AsyncSession = Depends(get_db))

@router.get("/book/{book_id}/export/obsidian")
async def export_book_obsidian(book_id: int, db: AsyncSession = Depends(get_db))

@router.get("/export/all/markdown")
async def export_all_markdown(db: AsyncSession = Depends(get_db))
```

**Files to create:**
- `app/services/export.py`
- `app/api/export.py`

**Files to modify:**
- `app/main.py` (include export router)

### Phase 6: UI Export Integration

#### 6.1 Update `book_detail.html`

Add export dropdown/buttons:
```html
<div class="flex gap-2">
    <a href="/books/{book_id}/export/markdown" class="btn">Export Markdown</a>
    <a href="/books/{book_id}/export/obsidian" class="btn">Export Obsidian</a>
</div>
```

#### 6.2 Update Settings Page (Optional)

- Add export preferences (default format, include/exclude notes, etc.)

**Files to modify:**
- `app/templates/book_detail.html`
- (Optional) `app/templates/settings.html`

### Phase 7: Testing

#### 7.1 Unit Tests (`tests/unit/`)

- Test `AnnotationType` enum
- Test export service Markdown generation
- Test export service Obsidian format

#### 7.2 Integration Tests (`tests/integration/`)

- Test note creation API
- Test export endpoints
- Test combined highlight/note listing

#### 7.3 E2E Tests (`tests/e2e/`)

- Test adding a note flow
- Test export download flow

**Files to create/modify:**
- `tests/unit/test_export.py`
- `tests/integration/test_api_notes.py`
- `tests/integration/test_api_export.py`
- `tests/e2e/test_user_flows.py`

## File Summary

### Files to Create
1. `app/services/export.py` - Export service
2. `app/api/export.py` - Export API routes
3. `app/templates/add_note.html` - Note creation page
4. `tests/unit/test_export.py` - Export unit tests
5. `tests/integration/test_api_notes.py` - Note API tests
6. `tests/integration/test_api_export.py` - Export API tests

### Files to Modify
1. `app/models/highlight.py` - Add AnnotationType, make text nullable
2. `app/models/__init__.py` - Export new types
3. `app/api/schemas.py` - Add NoteCreate, update responses
4. `app/api/highlights.py` - Add note creation endpoint
5. `app/api/views.py` - Add note views, update listing
6. `app/main.py` - Include export router
7. `app/templates/book_detail.html` - Note display, export buttons
8. `app/templates/all_highlights.html` - Type indicator
9. `app/templates/add_highlight.html` - Minor text updates
10. `tests/conftest.py` - Add note fixtures

## Implementation Order

1. **Phase 1**: Database schema (foundation)
2. **Phase 2**: API schemas (depends on Phase 1)
3. **Phase 3**: API routes for notes (depends on Phase 2)
4. **Phase 4**: UI for notes (depends on Phase 3)
5. **Phase 5**: Export service (can parallel Phase 4)
6. **Phase 6**: Export UI (depends on Phase 5)
7. **Phase 7**: Testing (throughout, but finalize at end)

## Considerations

### Readwise Integration
- Notes could optionally sync to Readwise as highlights with a special prefix
- Or skip Readwise sync for pure notes
- Current implementation: Readwise only gets items with highlight text

### Backward Compatibility
- Existing highlights continue to work
- Default type is "highlight"
- Text becomes nullable but validation ensures highlights have text

### Mobile UX
- Keep the add note form simple
- Page number is the key required field
- Large touch targets for buttons

### Sort Order
- Default: by created_at (current behavior)
- Option: by page_number (useful for reading through)
- Notes and highlights interleaved by chosen sort

## Estimated Effort

- Phase 1-2: 1-2 hours (schema/API changes)
- Phase 3-4: 2-3 hours (routes and basic UI)
- Phase 5-6: 2-3 hours (export feature)
- Phase 7: 1-2 hours (testing)

**Total: 6-10 hours**
