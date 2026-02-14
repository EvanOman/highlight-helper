# Highlight Helper

A mobile-friendly web app for collecting and organizing book highlights using AI-powered text extraction.

[![CI](https://github.com/EvanOman/highlight-helper/actions/workflows/ci.yml/badge.svg)](https://github.com/EvanOman/highlight-helper/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/EvanOman/highlight-helper/branch/main/graph/badge.svg)](https://codecov.io/gh/EvanOman/highlight-helper)

## Overview

Highlight Helper captures and organizes passages from physical books. Take a photo of a highlighted page, and the app uses OpenAI's Vision API to extract the text, returning both the full page content and the highlighted portion. An interactive editor lets you review and adjust the selection before saving.

## Limitations & Security Model

- This project is designed for **single-user** operation.
- The intended deployment/access pattern is over a **private Tailscale network** to your own machine.
- It currently does **not** implement production-grade multi-user security controls (for example: authentication/authorization hardening, CSRF protection, per-user isolation, and abuse/rate controls).
- Treat this app as personal/dev-machine software unless additional hardening is added.

### Key Features

- **AI-Powered Text Extraction** — Upload a photo of a book page, and the Vision API extracts all readable text along with the highlighted portion
- **Interactive Highlight Editor** — Review the full extracted text with the highlight marked, then drag handles to adjust the selection as needed
- **Book Library Management** — Search and add books via Google Books API with cover art and metadata
- **Mobile-First Design** — Responsive, touch-friendly interface designed for phones and tablets
- **Highlight Organization** — View all highlights in one place, organized by book
- **Chat with Your Highlights** — Ask questions across your entire library; the AI searches and quotes your actual highlights
- **Readwise Sync** — Sync highlights to Readwise for integration with your reading workflow
- **Local Database** — Data stored in SQLite; highlights stay on your server

## Screenshots

### Book Library

![Book library showing covers, authors, and highlight counts](static/screenshots/library.png)

### Book Detail

![Book detail page with reading progress timeline and highlighted passages](static/screenshots/book-detail.png)

### Chat with Your Highlights

![Chat conversation analyzing themes across a 61-book library](static/screenshots/chat.png)

## AI Reading Coach

Highlight Helper proactively generates coaching cards based on your reading highlights — prompting you to revisit old passages, find cross-book connections, and reflect on what you've read. Click "Reflect in Chat" to start a Socratic coaching session where the AI draws on your actual highlights to ask thoughtful questions.

![Coaching session exploring probabilistic thinking and navigating uncertainty](static/screenshots/coaching-session.png)

## Technology Stack

- **Backend**: [FastAPI](https://fastapi.tiangolo.com/) with async SQLAlchemy
- **Database**: [SQLite](https://sqlite.org/) via [SQLAlchemy](https://www.sqlalchemy.org/) (async)
- **Frontend**: Server-rendered HTML with [Jinja2](https://jinja.palletsprojects.com/) + [Tailwind CSS](https://tailwindcss.com/)
- **AI**: [OpenAI Vision API](https://platform.openai.com/docs/guides/vision) via [DSPy](https://dspy.ai/)
- **Book Data**: [Google Books API](https://developers.google.com/books)
- **Readwise**: [readwise-plus](https://pypi.org/project/readwise-plus/) SDK

## Getting Started

### Prerequisites

- Python 3.12+
- An OpenAI API key (for highlight extraction)

### Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/EvanOman/highlight-helper.git
   cd highlight-helper
   ```

2. Create a virtual environment and install dependencies:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -e ".[dev]"
   ```

3. Set up environment variables:
   ```bash
   cp .env.example .env
   # Edit .env and add your OPENAI_API_KEY
   ```

4. Run the application:
   ```bash
   python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```

5. Open http://localhost:8000 in your browser

## Development

### Running Tests

```bash
# Run all unit and integration tests
pytest tests/unit tests/integration -v

# Run with coverage
pytest tests/unit tests/integration --cov=app --cov-report=html

# Run E2E tests (requires Playwright)
playwright install chromium
pytest tests/e2e -v
```

### Code Quality

```bash
# Lint with Ruff
ruff check .

# Format with Ruff
ruff format .
```

## Project Structure

```
highlight_helper/
├── app/
│   ├── api/              # API routes and HTML views
│   │   ├── views/        # Server-rendered HTML views (package)
│   │   ├── books.py      # Book REST API
│   │   ├── highlights.py # Highlight REST API
│   │   ├── readwise.py   # Readwise sync API
│   │   ├── chat.py       # AI chat endpoints and views
│   │   └── schemas.py    # Pydantic request/response models
│   ├── core/             # Configuration and database setup
│   ├── models/           # SQLAlchemy database models
│   ├── repositories/     # Database access layer
│   ├── services/         # External service integrations
│   │   ├── book_lookup.py         # Google Books API
│   │   ├── highlight_extractor.py # OpenAI Vision API via DSPy
│   │   ├── readwise.py            # Readwise sync
│   │   └── chat.py                # AI chat service
│   └── templates/        # Jinja2 HTML templates
├── tests/
│   ├── unit/             # Unit tests
│   ├── integration/      # Integration tests
│   └── e2e/              # End-to-end Playwright tests
└── static/
    └── js/
        └── highlight-editor.js  # Interactive highlight editor
```

## API Documentation

When the app is running, visit:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## Contributing

Contributions welcome. Feel free to open a Pull Request.

## License

This project is available under the [MIT License](LICENSE).
