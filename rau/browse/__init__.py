"""Reading the web: Firecrawl for speed, Browserbase for pages that need a browser."""
from rau.browse.base import (
    BrowseError,
    BrowseProvider,
    Page,
    SearchHit,
    Unsupported,
)
from rau.browse.registry import (
    BROWSE_AUTH,
    available_browse,
    get_browser,
    resolve_browse,
    status,
)

__all__ = [
    "BROWSE_AUTH",
    "BrowseError",
    "BrowseProvider",
    "Page",
    "SearchHit",
    "Unsupported",
    "available_browse",
    "get_browser",
    "resolve_browse",
    "status",
]
