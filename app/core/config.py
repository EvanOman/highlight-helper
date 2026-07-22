"""Application configuration."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # OpenAI
    openai_api_key: str = ""

    # Anthropic (for chat with highlights feature)
    anthropic_api_key: str = ""

    # Google Books API
    google_books_api_key: str = ""

    # Groq (fallback for vision model)
    groq_api_key: str = ""

    # Model configuration
    # Vision calls need a vision-capable backing model, so this stays a
    # concrete provider/model id (not a gateway tier alias) even when routed
    # through the gateway.
    vision_model: str = "gemini/gemini-2.5-flash"
    vision_fallback_model: str = "groq/meta-llama/llama-4-scout-17b-16e-instruct"
    # Output-token cap for a single vision extraction. A dense book page's
    # full_text plus the model's chain-of-thought reasoning can exceed 2000
    # tokens and truncate the JSON result, so the cap is generous by default.
    vision_max_tokens: int = 4000
    # Chat/coaching go through app/services/llm.py, which calls the litellm
    # client directly -- gateway tier aliases need the openai/ mirror prefix
    # there for client-side model-string validation.
    chat_model: str = "openai/tier-smart"
    coaching_model: str = "openai/tier-fast"

    # Readwise (optional)
    readwise_api_token: str | None = None
    readwise_auto_sync: bool = False  # Auto-sync highlights on creation

    # Database
    database_url: str = "sqlite+aiosqlite:///./highlight_helper.db"

    # Environment
    environment: str = "development"

    # Upload retention (eval corpus building)
    # Persist every uploaded page photo + a JSON sidecar so each becomes a
    # near-ready eval case. Default ON: this is a single-user internal
    # deployment behind Tailscale and corpus-building is the whole point. The
    # flag exists so a future multi-user/production rollout can disable it.
    store_uploaded_images: bool = True
    uploaded_images_dir: str = "data/uploads"

    # Replace all LLM calls with deterministic fakes (full-stack self-tests only)
    fake_llm: bool = False

    # Root path for subpath deployment (e.g., "/highlights" when behind Tailscale Serve)
    root_path: str = ""

    # OpenTelemetry
    otel_enabled: bool = False
    otel_service_name: str = "highlight-helper"
    otel_exporter: str = "otlp"  # "otlp", "console", "none"
    otel_endpoint: str = "http://localhost:4317"  # OTLP gRPC endpoint (Jaeger, Datadog, etc.)

    @property
    def is_development(self) -> bool:
        """Check if running in development mode."""
        return self.environment == "development"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
