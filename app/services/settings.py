"""Settings service for managing application settings."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import AppSetting

# Setting keys
READWISE_API_TOKEN = "readwise_api_token"
READWISE_AUTO_SYNC = "readwise_auto_sync"


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
        """Set a setting value."""
        result = await self.db.execute(select(AppSetting).where(AppSetting.key == key))
        setting = result.scalar_one_or_none()

        if setting:
            setting.value = value
        else:
            setting = AppSetting(key=key, value=value)
            self.db.add(setting)

        await self.db.commit()

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

    async def get_readwise_auto_sync(self) -> bool:
        """Get the Readwise auto-sync setting."""
        return await self.get_bool(READWISE_AUTO_SYNC, default=False)

    async def set_readwise_auto_sync(self, enabled: bool) -> None:
        """Set the Readwise auto-sync setting."""
        await self.set_bool(READWISE_AUTO_SYNC, enabled)


async def get_settings_service(db: AsyncSession) -> SettingsService:
    """Dependency that provides the settings service."""
    return SettingsService(db)
