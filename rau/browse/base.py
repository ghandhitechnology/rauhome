"""
What a web-browsing backend has to provide.

Two very different things sit behind this interface. Firecrawl is a scraping
API: hand it a URL, get clean markdown back. Browserbase is a real browser in
someone else's data centre, driven over CDP. They are not interchangeable —
one is faster and cheaper, the other actually runs the page's JavaScript — so
the user picks, and the interface stays small enough that either can honour it.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

#: Nothing fetched from the open web is allowed to grow without bound. This is
#: what reaches the model's context, so it is a latency and a cost ceiling as
#: much as a memory one.
MAX_TEXT_CHARS = 40_000
MAX_LINKS = 60
DEFAULT_TIMEOUT_SEC = 45.0
#: Ceiling on what a caller may ask for, so one call cannot wedge a turn.
MAX_TIMEOUT_SEC = 120.0


class BrowseError(RuntimeError):
    """A browse attempt that failed for a reason worth telling the model."""

    def __init__(self, message: str, *, code: str = "browse_failed") -> None:
        super().__init__(message)
        self.code = code


class Unsupported(BrowseError):
    """The selected backend cannot do this at all."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="unsupported")


@dataclass
class Page:
    url: str
    title: str
    text: str
    links: List[str] = field(default_factory=list)
    provider: str = ""
    #: Wall-clock cost of the fetch, so slow backends are visible not guessed.
    elapsed_ms: float = 0.0

    def trimmed(self) -> "Page":
        text = self.text or ""
        if len(text) > MAX_TEXT_CHARS:
            text = text[:MAX_TEXT_CHARS].rstrip() + "\n\n…[truncated]"
        return Page(
            url=self.url,
            title=self.title,
            text=text,
            links=list(self.links)[:MAX_LINKS],
            provider=self.provider,
            elapsed_ms=self.elapsed_ms,
        )


@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str = ""


class BrowseProvider(ABC):
    """One way of reading the web."""

    id: str = "base"
    label: str = "Base"
    #: Whether `search` is real here, or raises `Unsupported`.
    can_search: bool = False

    @abstractmethod
    def fetch(self, url: str, *, timeout: float = DEFAULT_TIMEOUT_SEC) -> Page:
        """Read one page."""

    def search(
        self, query: str, *, limit: int = 5, timeout: float = DEFAULT_TIMEOUT_SEC
    ) -> List[SearchHit]:
        raise Unsupported(f"{self.label} cannot search the web, only open a page")

    def close(self) -> None:
        """Release anything held open. Safe to call more than once."""
        return None


def post_json(
    url: str,
    payload: Dict[str, Any],
    headers: Dict[str, str],
    *,
    timeout: float,
) -> Dict[str, Any]:
    """
    One JSON POST, with the failure modes named rather than raised raw.

    Everything here ends up in a tool result the model reads, so an error has
    to say what went wrong in terms it can act on — a bad key is a different
    problem from a slow site, and it should not have to guess which it hit.
    """
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:400]
        except Exception:
            pass
        if exc.code in (401, 403):
            raise BrowseError(
                f"the API key was rejected ({exc.code})", code="bad_key"
            ) from exc
        if exc.code == 429:
            raise BrowseError("rate limited by the provider", code="rate_limited") from exc
        raise BrowseError(f"provider returned {exc.code}: {detail}", code="http_error") from exc
    except urllib.error.URLError as exc:
        # urllib wraps any OSError from the connect/read in URLError, so a
        # socket timeout arrives here as the reason rather than as TimeoutError.
        if isinstance(exc.reason, TimeoutError):
            raise BrowseError("the provider timed out", code="timeout") from exc
        raise BrowseError(f"could not reach the provider: {exc.reason}", code="unreachable") from exc
    except TimeoutError as exc:
        raise BrowseError("the provider timed out", code="timeout") from exc

    try:
        parsed = json.loads(raw.decode("utf-8", "replace"))
    except json.JSONDecodeError as exc:
        raise BrowseError("provider returned something that was not JSON", code="bad_response") from exc
    if not isinstance(parsed, dict):
        raise BrowseError("provider returned an unexpected shape", code="bad_response")
    return parsed


def clamp_timeout(value: Optional[float]) -> float:
    try:
        seconds = float(value if value is not None else DEFAULT_TIMEOUT_SEC)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_SEC
    if seconds != seconds or seconds <= 0:  # NaN or nonsense
        return DEFAULT_TIMEOUT_SEC
    return min(seconds, MAX_TIMEOUT_SEC)


def normalise_url(raw: Any) -> str:
    """Accept what a model is likely to produce; reject what cannot be fetched."""
    url = str(raw or "").strip()
    if not url:
        raise BrowseError("a url is required", code="missing_url")
    if url.startswith("//"):
        url = f"https:{url}"

    # Match any scheme, not just the ones written with "//". `javascript:` and
    # `data:` have none, so testing for "://" alone quietly laundered them into
    # "https://javascript:alert(1)" and handed that to the provider.
    scheme_match = re.match(r"^([a-zA-Z][a-zA-Z0-9+.\-]*):", url)
    if scheme_match:
        scheme = scheme_match.group(1).lower()
        if scheme not in ("http", "https"):
            raise BrowseError(
                f"only http and https can be opened, not {scheme}", code="bad_scheme"
            )
    else:
        url = f"https://{url}"
    if len(url) > 2_000:
        raise BrowseError("that url is too long", code="bad_url")
    return url
