# Implementation Plan: Chat with Highlights Feature (Issue #37)

## Issue Summary

**GitHub Issue #37**: Add a chat with highlights feature

Users should be able to chat with their highlights and notes. The chat can be scoped to either:
1. A specific book
2. All notes across all books

The feature should be implemented using the Claude Agent SDK.

## Architecture Overview

### High-Level Design

The chat feature will allow users to have natural language conversations with Claude about their highlights and notes. Claude will have access to the user's highlight data through custom MCP tools that query the SQLite database.

```
User -> Chat UI -> FastAPI Endpoint -> Claude Agent SDK -> Custom MCP Tools -> SQLite DB
                                            |
                                            v
                                    Claude's Response
```

### Key Components

1. **Chat Service** (`app/services/chat.py`)
   - Manages conversations using Claude Agent SDK
   - Configures custom MCP tools for database access
   - Handles session management for multi-turn conversations

2. **Custom MCP Tools** (`app/services/chat_tools.py`)
   - `get_all_highlights`: Retrieve all highlights, optionally filtered by book
   - `get_highlights_by_book`: Get highlights for a specific book
   - `search_highlights`: Search highlights by text content
   - `get_book_info`: Get book metadata (title, author, highlight count)
   - `list_books`: List all books with highlight counts

3. **API Endpoints** (`app/api/chat.py`)
   - `POST /api/chat/message`: Send a message and get a response
   - `GET /api/chat/history/{session_id}`: Get conversation history
   - `DELETE /api/chat/session/{session_id}`: Clear a conversation session
   - `POST /api/chat/book/{book_id}/message`: Chat scoped to a specific book

4. **UI Templates**
   - `app/templates/chat.html`: Global chat page (all highlights)
   - `app/templates/book_chat.html`: Book-specific chat page
   - Embedded chat component in `book_detail.html`

5. **Database Model** (optional)
   - `ChatSession`: Store conversation history for persistence

## Implementation Details

### 1. Dependencies

Add to `pyproject.toml`:
```toml
dependencies = [
    # ... existing deps ...
    "claude-agent-sdk>=0.1.0",
    "aiohttp>=3.9.0",  # For async HTTP in custom tools
]
```

### 2. Custom MCP Tools (`app/services/chat_tools.py`)

```python
from claude_agent_sdk import tool, create_sdk_mcp_server
from typing import Any
import json

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.book import Book
from app.models.highlight import Highlight


@tool(
    "list_books",
    "List all books in the user's library with highlight counts",
    {}
)
async def list_books(args: dict[str, Any], db: AsyncSession) -> dict[str, Any]:
    """List all books with their highlight counts."""
    query = (
        select(Book, func.count(Highlight.id).label("highlight_count"))
        .outerjoin(Highlight)
        .group_by(Book.id)
        .order_by(Book.title)
    )
    result = await db.execute(query)
    rows = result.all()

    books = [
        {
            "id": book.id,
            "title": book.title,
            "author": book.author,
            "highlight_count": count
        }
        for book, count in rows
    ]

    return {
        "content": [{
            "type": "text",
            "text": json.dumps(books, indent=2)
        }]
    }


@tool(
    "get_highlights",
    "Get highlights from the user's library",
    {
        "book_id": int,  # Optional - filter by book
        "search_query": str,  # Optional - search text
        "limit": int  # Optional - max results
    }
)
async def get_highlights(args: dict[str, Any], db: AsyncSession) -> dict[str, Any]:
    """Get highlights, optionally filtered by book or search query."""
    query = select(Highlight, Book).join(Book)

    if book_id := args.get("book_id"):
        query = query.where(Highlight.book_id == book_id)

    if search := args.get("search_query"):
        query = query.where(Highlight.text.ilike(f"%{search}%"))

    limit = args.get("limit", 50)
    query = query.limit(limit).order_by(Highlight.created_at.desc())

    result = await db.execute(query)
    rows = result.all()

    highlights = [
        {
            "id": h.id,
            "text": h.text,
            "note": h.note,
            "page_number": h.page_number,
            "book_title": b.title,
            "book_author": b.author,
            "created_at": h.created_at.isoformat()
        }
        for h, b in rows
    ]

    return {
        "content": [{
            "type": "text",
            "text": json.dumps(highlights, indent=2)
        }]
    }


@tool(
    "get_book_details",
    "Get detailed information about a specific book",
    {"book_id": int}
)
async def get_book_details(args: dict[str, Any], db: AsyncSession) -> dict[str, Any]:
    """Get details about a specific book including all its highlights."""
    query = select(Book).where(Book.id == args["book_id"])
    result = await db.execute(query)
    book = result.scalar_one_or_none()

    if not book:
        return {
            "content": [{
                "type": "text",
                "text": "Book not found"
            }]
        }

    highlights_query = (
        select(Highlight)
        .where(Highlight.book_id == book.id)
        .order_by(Highlight.created_at.desc())
    )
    highlights_result = await db.execute(highlights_query)
    highlights = highlights_result.scalars().all()

    book_data = {
        "id": book.id,
        "title": book.title,
        "author": book.author,
        "isbn": book.isbn,
        "highlight_count": len(highlights),
        "highlights": [
            {
                "id": h.id,
                "text": h.text,
                "note": h.note,
                "page_number": h.page_number,
                "created_at": h.created_at.isoformat()
            }
            for h in highlights
        ]
    }

    return {
        "content": [{
            "type": "text",
            "text": json.dumps(book_data, indent=2)
        }]
    }


def create_highlights_mcp_server(db: AsyncSession):
    """Create an MCP server with database-connected tools."""
    # Note: Tools need db session injected - this requires wrapping
    # the tool functions to include the db parameter
    return create_sdk_mcp_server(
        name="highlights-db",
        version="1.0.0",
        tools=[
            # Wrapped versions that include db session
            _wrap_tool_with_db(list_books, db),
            _wrap_tool_with_db(get_highlights, db),
            _wrap_tool_with_db(get_book_details, db),
        ]
    )
```

### 3. Chat Service (`app/services/chat.py`)

```python
from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage, AssistantMessage
from typing import AsyncGenerator
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.chat_tools import create_highlights_mcp_server

logger = logging.getLogger(__name__)


class ChatService:
    """Service for managing chat conversations with highlights."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._sessions: dict[str, str] = {}  # session_id -> Claude session_id

    async def send_message(
        self,
        message: str,
        book_id: int | None = None,
        session_id: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """
        Send a message and stream the response.

        Args:
            message: User's message
            book_id: Optional book ID to scope the conversation
            session_id: Optional session ID to resume a conversation

        Yields:
            Chunks of the response text
        """
        # Create MCP server with database tools
        mcp_server = create_highlights_mcp_server(self.db)

        # Build system prompt based on scope
        if book_id:
            system_prompt = f"""You are a helpful assistant that helps users explore and discuss
            their book highlights. You are currently focused on book ID {book_id}.

            Use the available tools to look up highlight information when needed.
            Be conversational and insightful. Help users find connections between ideas,
            recall specific passages, and explore themes in their highlights."""
        else:
            system_prompt = """You are a helpful assistant that helps users explore and discuss
            their book highlights across all their books.

            Use the available tools to look up highlight information when needed.
            Be conversational and insightful. Help users find connections between ideas,
            recall specific passages, compare themes across books, and explore their reading journey."""

        options = ClaudeAgentOptions(
            mcp_servers={"highlights-db": mcp_server},
            allowed_tools=[
                "mcp__highlights-db__list_books",
                "mcp__highlights-db__get_highlights",
                "mcp__highlights-db__get_book_details",
            ],
            system_prompt=system_prompt,
            permission_mode="bypassPermissions",  # Tools are read-only
        )

        # Resume session if provided
        if session_id and session_id in self._sessions:
            options.resume = self._sessions[session_id]

        async for msg in query(prompt=message, options=options):
            # Capture session ID from init message
            if hasattr(msg, 'subtype') and msg.subtype == 'init':
                if session_id:
                    self._sessions[session_id] = msg.session_id

            # Stream text content from assistant messages
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if hasattr(block, 'text'):
                        yield block.text

            # Handle final result
            elif isinstance(msg, ResultMessage) and msg.subtype == 'success':
                if hasattr(msg, 'result') and msg.result:
                    yield msg.result


async def get_chat_service(db: AsyncSession) -> ChatService:
    """Dependency that provides the chat service."""
    return ChatService(db)
```

### 4. API Endpoints (`app/api/chat.py`)

```python
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.chat import ChatService, get_chat_service

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatMessageRequest(BaseModel):
    message: str
    session_id: str | None = None


class ChatMessageResponse(BaseModel):
    response: str
    session_id: str


@router.post("/message")
async def send_chat_message(
    request: ChatMessageRequest,
    chat_service: ChatService = Depends(get_chat_service),
):
    """Send a message and get a streaming response."""
    async def generate():
        async for chunk in chat_service.send_message(
            message=request.message,
            session_id=request.session_id,
        ):
            yield chunk

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
    )


@router.post("/book/{book_id}/message")
async def send_book_chat_message(
    book_id: int,
    request: ChatMessageRequest,
    chat_service: ChatService = Depends(get_chat_service),
    db: AsyncSession = Depends(get_db),
):
    """Send a message scoped to a specific book."""
    # Verify book exists
    from sqlalchemy import select
    from app.models.book import Book

    result = await db.execute(select(Book).where(Book.id == book_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Book not found")

    async def generate():
        async for chunk in chat_service.send_message(
            message=request.message,
            book_id=book_id,
            session_id=request.session_id,
        ):
            yield chunk

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
    )
```

### 5. View Endpoints (`app/api/views.py` additions)

```python
@router.get("/chat/", response_class=HTMLResponse)
async def chat_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Global chat page for all highlights."""
    # Get summary stats for context
    from sqlalchemy import func

    book_count = await db.scalar(select(func.count(Book.id)))
    highlight_count = await db.scalar(select(func.count(Highlight.id)))

    return templates.TemplateResponse(
        request,
        "chat.html",
        {
            "book_count": book_count,
            "highlight_count": highlight_count,
        },
    )


@router.get("/books/{book_id}/chat/", response_class=HTMLResponse)
async def book_chat_page(
    request: Request,
    book_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Book-specific chat page."""
    query = select(Book).where(Book.id == book_id)
    result = await db.execute(query)
    book = result.scalar_one_or_none()

    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    highlight_count = await db.scalar(
        select(func.count(Highlight.id)).where(Highlight.book_id == book_id)
    )

    return templates.TemplateResponse(
        request,
        "book_chat.html",
        {
            "book": book,
            "highlight_count": highlight_count,
        },
    )
```

### 6. UI Templates

#### `app/templates/chat.html`

```html
{% extends "layouts/base.html" %}

{% block title %}Chat with Your Highlights - Highlight Helper{% endblock %}

{% block content %}
<div class="flex flex-col h-[calc(100vh-12rem)]">
    <div class="mb-4">
        <h1 class="text-2xl font-bold text-gray-900 dark:text-white">Chat with Your Highlights</h1>
        <p class="text-gray-600 dark:text-gray-400">
            {{ book_count }} books, {{ highlight_count }} highlights
        </p>
    </div>

    <!-- Chat messages container -->
    <div id="chat-messages" class="flex-1 overflow-y-auto space-y-4 mb-4 p-4 bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700">
        <div class="text-center text-gray-500 dark:text-gray-400 py-8">
            <p>Ask me about your highlights!</p>
            <p class="text-sm mt-2">Try: "What themes appear across my books?" or "Find highlights about leadership"</p>
        </div>
    </div>

    <!-- Input form -->
    <form id="chat-form" class="flex gap-2">
        <input type="text"
               id="chat-input"
               name="message"
               placeholder="Ask about your highlights..."
               class="flex-1 px-4 py-3 rounded-xl border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-primary-500 focus:border-transparent"
               autocomplete="off">
        <button type="submit"
                class="px-6 py-3 bg-primary-600 text-white rounded-xl font-medium hover:bg-primary-700 transition disabled:opacity-50 disabled:cursor-not-allowed">
            Send
        </button>
    </form>
</div>

<script>
const chatMessages = document.getElementById('chat-messages');
const chatForm = document.getElementById('chat-form');
const chatInput = document.getElementById('chat-input');
let sessionId = null;

function addMessage(role, content) {
    const messageDiv = document.createElement('div');
    messageDiv.className = role === 'user'
        ? 'flex justify-end'
        : 'flex justify-start';

    const bubble = document.createElement('div');
    bubble.className = role === 'user'
        ? 'max-w-[80%] px-4 py-2 rounded-2xl bg-primary-600 text-white'
        : 'max-w-[80%] px-4 py-2 rounded-2xl bg-gray-100 dark:bg-gray-700 text-gray-900 dark:text-white';
    bubble.textContent = content;

    messageDiv.appendChild(bubble);
    chatMessages.appendChild(messageDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;

    return bubble;
}

chatForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const message = chatInput.value.trim();
    if (!message) return;

    // Clear placeholder on first message
    if (chatMessages.querySelector('.text-center')) {
        chatMessages.innerHTML = '';
    }

    // Add user message
    addMessage('user', message);
    chatInput.value = '';

    // Add assistant placeholder
    const assistantBubble = addMessage('assistant', '...');

    try {
        const response = await fetch('{{ base_path }}/api/chat/message', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message, session_id: sessionId }),
        });

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let fullResponse = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            const chunk = decoder.decode(value);
            fullResponse += chunk;
            assistantBubble.textContent = fullResponse;
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }
    } catch (error) {
        assistantBubble.textContent = 'Error: Could not get response. Please try again.';
        assistantBubble.className += ' text-red-500';
    }
});
</script>
{% endblock %}
```

### 7. Configuration Updates (`app/core/config.py`)

```python
class Settings(BaseSettings):
    # ... existing settings ...

    # Anthropic API for Claude Agent SDK
    anthropic_api_key: str = ""
```

### 8. Main App Updates (`app/main.py`)

```python
from app.api.chat import router as chat_router

# ... existing code ...

# Include chat router
app.include_router(chat_router)
```

## File Changes Summary

### New Files

| File | Purpose |
|------|---------|
| `app/services/chat.py` | Chat service using Claude Agent SDK |
| `app/services/chat_tools.py` | Custom MCP tools for database access |
| `app/api/chat.py` | API endpoints for chat functionality |
| `app/templates/chat.html` | Global chat UI page |
| `app/templates/book_chat.html` | Book-scoped chat UI page |
| `tests/unit/test_chat_service.py` | Unit tests for chat service |
| `tests/integration/test_chat_api.py` | Integration tests for chat API |

### Modified Files

| File | Changes |
|------|---------|
| `pyproject.toml` | Add `claude-agent-sdk` dependency |
| `app/main.py` | Register chat router |
| `app/api/views.py` | Add chat page view endpoints |
| `app/core/config.py` | Add `anthropic_api_key` setting |
| `app/templates/layouts/base.html` | Add "Chat" link to navigation |
| `app/templates/book_detail.html` | Add "Chat about this book" button |
| `tests/conftest.py` | Add mock chat service fixture |

## Testing Strategy

### Unit Tests (`tests/unit/test_chat_service.py`)

1. Test custom MCP tools return correct data format
2. Test tool filtering by book_id
3. Test tool search functionality
4. Mock Claude Agent SDK to test message handling

### Integration Tests (`tests/integration/test_chat_api.py`)

1. Test chat endpoint authentication
2. Test book-scoped chat validates book exists
3. Test streaming response format
4. Mock Claude Agent SDK responses

### E2E Tests (`tests/e2e/test_chat.py`)

1. Test chat page loads correctly
2. Test message input and display
3. Test book-specific chat navigation
4. Test dark mode styling

## Security Considerations

1. **Read-only tools**: All MCP tools are read-only database queries
2. **Book ownership**: Future enhancement could add user authentication
3. **Rate limiting**: Consider adding rate limits to chat endpoints
4. **Input sanitization**: Escape user input in UI rendering
5. **API key management**: Anthropic API key stored in environment variables

## Performance Considerations

1. **Streaming responses**: Use SSE for real-time response streaming
2. **Database queries**: Use efficient indexes for highlight search
3. **Context window**: Limit highlight retrieval to avoid context overflow
4. **Session caching**: Store Claude session IDs for conversation continuity

## Future Enhancements

1. **Conversation persistence**: Store chat history in database
2. **Export conversations**: Download chat history as markdown
3. **Smart suggestions**: Suggest follow-up questions based on highlights
4. **Cross-book insights**: Automatically identify themes across books
5. **Voice input**: Add speech-to-text for hands-free chatting
6. **Highlight citations**: Link back to specific highlights in responses

## Implementation Order

1. **Phase 1: Core Backend**
   - [ ] Add claude-agent-sdk dependency
   - [ ] Create chat_tools.py with MCP tools
   - [ ] Create chat.py service
   - [ ] Add API endpoints

2. **Phase 2: Basic UI**
   - [ ] Create chat.html template
   - [ ] Add navigation link
   - [ ] Implement streaming display
   - [ ] Add book-specific chat page

3. **Phase 3: Testing**
   - [ ] Write unit tests with mocked SDK
   - [ ] Write integration tests
   - [ ] Manual validation

4. **Phase 4: Polish**
   - [ ] Error handling improvements
   - [ ] Loading states
   - [ ] Mobile responsiveness
   - [ ] Dark mode styling

## Estimated Effort

- **Backend implementation**: 4-6 hours
- **UI implementation**: 3-4 hours
- **Testing**: 2-3 hours
- **Documentation**: 1 hour
- **Total**: ~10-14 hours

## References

- [Claude Agent SDK Documentation](https://platform.claude.com/docs/en/agent-sdk/overview)
- [Claude Agent SDK Python GitHub](https://github.com/anthropics/claude-agent-sdk-python)
- [MCP Custom Tools Guide](https://platform.claude.com/docs/en/agent-sdk/custom-tools)
- [FastAPI Streaming Responses](https://fastapi.tiangolo.com/advanced/custom-response/#streamingresponse)
