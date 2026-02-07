"""Shared imports and template setup for views."""

from fastapi import APIRouter
from fastapi.templating import Jinja2Templates

from app.core.config import get_settings

router = APIRouter(tags=["views"])
templates = Jinja2Templates(directory="app/templates")

# Add base_path as a global for subpath deployments (e.g., /highlights via Tailscale Serve)
settings = get_settings()
templates.env.globals["base_path"] = settings.root_path
