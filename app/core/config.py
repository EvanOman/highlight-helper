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

    # Groq (fallback for vision model)
    groq_api_key: str = ""

    # Model configuration
    vision_model: str = "openai/gpt-5.4"
    vision_fallback_model: str = "groq/meta-llama/llama-4-scout-17b-16e-instruct"
    chat_model: str = "claude-opus-4-6"

    # Readwise (optional)
    readwise_api_token: str | None = None
    readwise_auto_sync: bool = False  # Auto-sync highlights on creation

    # Database
    database_url: str = "sqlite+aiosqlite:///./highlight_helper.db"

    # Environment
    environment: str = "development"

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
