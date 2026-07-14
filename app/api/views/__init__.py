"""Views package - HTML page handlers split into focused modules."""

# Import all view modules so their routes register on the shared router
from . import book_views as _book_views  # noqa: F401
from . import capture_views as _capture_views  # noqa: F401
from . import coaching_views as _coaching_views  # noqa: F401
from . import highlight_views as _highlight_views  # noqa: F401
from . import home as _home  # noqa: F401
from . import metrics_views as _metrics_views  # noqa: F401
from . import settings_views as _settings_views  # noqa: F401
from ._common import router

__all__ = ["router"]
