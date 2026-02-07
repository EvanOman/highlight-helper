"""Settings page view."""

from fastapi import Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.settings import get_settings_service

from ._common import router, templates


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Settings page for configuring the application."""
    settings = await get_settings_service(db)

    token = await settings.get_readwise_token()
    auto_sync = await settings.get_readwise_auto_sync()
    api_metrics = await settings.get_api_usage_metrics()

    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "token_configured": bool(token),
            "auto_sync": auto_sync,
            "api_metrics": api_metrics,
        },
    )
