"""Settings service for managing application settings."""

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.model_registry import normalize_model_id
from app.models.api_usage import APIUsage
from app.models.settings import AppSetting


class APIUsageMetrics(BaseModel):
    """Metrics for API usage and costs."""

    total_extractions: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    average_cost_per_extraction: float = 0.0


# Setting keys
READWISE_API_TOKEN = "readwise_api_token"
READWISE_AUTO_SYNC = "readwise_auto_sync"
CHAT_MODEL = "chat_model"
COACHING_MODEL = "coaching_model"


class SettingsService:
    """Service for managing application settings."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, key: str, default: str | None = None) -> str | None:
        """Get a setting value by key."""
        result = await self.db.execute(select(AppSetting).where(AppSetting.key == key))
        setting = result.scalar_one_or_none()
        return setting.value if setting else default

    async def set(self, key: str, value: str | None) -> None:
        """Set a setting value.

        The write is committed by the session owner (get_db / get_async_session)
        at the end of the request or task, keeping the operation transactional
        with the rest of the request.
        """
        result = await self.db.execute(select(AppSetting).where(AppSetting.key == key))
        setting = result.scalar_one_or_none()

        if setting:
            setting.value = value
        else:
            setting = AppSetting(key=key, value=value)
            self.db.add(setting)

    async def get_bool(self, key: str, default: bool = False) -> bool:
        """Get a boolean setting value."""
        value = await self.get(key)
        if value is None:
            return default
        return value.lower() in ("true", "1", "yes", "on")

    async def set_bool(self, key: str, value: bool) -> None:
        """Set a boolean setting value."""
        await self.set(key, "true" if value else "false")

    async def get_readwise_token(self) -> str | None:
        """Get the Readwise API token."""
        return await self.get(READWISE_API_TOKEN)

    async def set_readwise_token(self, token: str | None) -> None:
        """Set the Readwise API token."""
        await self.set(READWISE_API_TOKEN, token)

    async def get_chat_model(self) -> str:
        """Get the configured chat model as a canonical provider-prefixed id."""
        from app.core.config import get_settings

        default = get_settings().chat_model
        value = await self.get(CHAT_MODEL, default=default) or default
        return normalize_model_id(value)

    async def set_chat_model(self, model: str) -> None:
        """Set the chat model (stored in canonical provider-prefixed form)."""
        await self.set(CHAT_MODEL, normalize_model_id(model))

    async def get_coaching_model(self) -> str:
        """Get the configured coaching model as a canonical provider-prefixed id."""
        from app.core.config import get_settings

        default = get_settings().coaching_model
        value = await self.get(COACHING_MODEL, default=default) or default
        return normalize_model_id(value)

    async def set_coaching_model(self, model: str) -> None:
        """Set the coaching model (stored in canonical provider-prefixed form)."""
        await self.set(COACHING_MODEL, normalize_model_id(model))

    async def get_readwise_auto_sync(self) -> bool:
        """Get the Readwise auto-sync setting."""
        return await self.get_bool(READWISE_AUTO_SYNC, default=False)

    async def set_readwise_auto_sync(self, enabled: bool) -> None:
        """Set the Readwise auto-sync setting."""
        await self.set_bool(READWISE_AUTO_SYNC, enabled)

    async def get_api_usage_metrics(self) -> APIUsageMetrics:
        """Get aggregated API usage metrics.

        Returns:
            APIUsageMetrics with totals and averages for all API usage.
        """
        # Query aggregate stats from api_usage table
        result = await self.db.execute(
            select(
                func.count(APIUsage.id).label("total_extractions"),
                func.coalesce(func.sum(APIUsage.input_tokens), 0).label("total_input_tokens"),
                func.coalesce(func.sum(APIUsage.output_tokens), 0).label("total_output_tokens"),
                func.coalesce(func.sum(APIUsage.total_tokens), 0).label("total_tokens"),
                func.coalesce(func.sum(APIUsage.cost_usd), 0.0).label("total_cost_usd"),
            ).where(APIUsage.operation == "highlight_extraction")
        )
        row = result.one()

        total_extractions = row.total_extractions or 0
        total_cost = row.total_cost_usd or 0.0

        avg_cost = total_cost / total_extractions if total_extractions > 0 else 0.0

        return APIUsageMetrics(
            total_extractions=total_extractions,
            total_input_tokens=row.total_input_tokens or 0,
            total_output_tokens=row.total_output_tokens or 0,
            total_tokens=row.total_tokens or 0,
            total_cost_usd=total_cost,
            average_cost_per_extraction=avg_cost,
        )


async def get_settings_service(db: AsyncSession) -> SettingsService:
    """Dependency that provides the settings service."""
    return SettingsService(db)
