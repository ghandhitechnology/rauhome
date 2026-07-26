"""
Firecrawl: a scraping API that hands back clean markdown.

Fast and cheap, and it is the only one of the two that can search. It renders
pages server-side, so most sites come back complete — but it is someone else's
idea of what the page says, which is exactly the trade Browserbase does not
make.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List

from rau.browse.base import (
    BrowseError,
    BrowseProvider,
    Page,
    SearchHit,
    clamp_timeout,
    normalise_url,
    post_json,
)
from rau.env import get_secret

API_ROOT = "https://api.firecrawl.dev/v2"
ENV_KEY = "FIRECRAWL_API_KEY"


def _headers() -> Dict[str, str]:
    key = get_secret(ENV_KEY)
    if not key:
        raise BrowseError("no Firecrawl API key is configured", code="no_key")
    return {"Authorization": f"Bearer {key}"}


class FirecrawlBrowser(BrowseProvider):
    id = "firecrawl"
    label = "Firecrawl"
    can_search = True

    def __init__(self, *, post=post_json) -> None:
        # Injected so the contract can be tested without reaching the network.
        self._post = post

    def fetch(self, url: str, *, timeout: float = 45.0) -> Page:
        target = normalise_url(url)
        seconds = clamp_timeout(timeout)
        started = time.monotonic()
        payload: Dict[str, Any] = {
            "url": target,
            # `links` is a separate format — without it Firecrawl omits them.
            "formats": ["markdown", "links"],
            # The navigation and the boilerplate are noise in a context window.
            "onlyMainContent": True,
            # Firecrawl counts in milliseconds, and should give up before we do.
            "timeout": int(max(1.0, seconds - 2) * 1000),
        }
        body = self._post(f"{API_ROOT}/scrape", payload, _headers(), timeout=seconds)
        if not body.get("success", True):
            raise BrowseError(
                str(body.get("error") or "Firecrawl could not read that page"),
                code="provider_error",
            )
        data = body.get("data")
        if not isinstance(data, dict):
            raise BrowseError("Firecrawl returned no page data", code="bad_response")

        metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        text = str(data.get("markdown") or data.get("summary") or "").strip()
        if not text:
            raise BrowseError("that page came back empty", code="empty_page")

        links = [
            str(link)
            for link in (data.get("links") or [])
            if isinstance(link, str) and link.startswith("http")
        ]
        return Page(
            url=str(metadata.get("url") or target),
            title=str(metadata.get("title") or "").strip(),
            text=text,
            links=links,
            provider=self.id,
            elapsed_ms=(time.monotonic() - started) * 1000.0,
        ).trimmed()

    def search(self, query: str, *, limit: int = 5, timeout: float = 45.0) -> List[SearchHit]:
        term = str(query or "").strip()
        if not term:
            raise BrowseError("a search needs something to look for", code="missing_query")
        seconds = clamp_timeout(timeout)
        payload = {"query": term[:400], "limit": max(1, min(int(limit or 5), 20))}
        body = self._post(f"{API_ROOT}/search", payload, _headers(), timeout=seconds)
        if not body.get("success", True):
            raise BrowseError(
                str(body.get("error") or "Firecrawl could not run that search"),
                code="provider_error",
            )
        data = body.get("data")
        rows: List[Any] = []
        if isinstance(data, dict):
            rows = data.get("web") or []
        elif isinstance(data, list):
            # Older shape returned a bare list.
            rows = data
        hits: List[SearchHit] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            url = str(row.get("url") or "").strip()
            if not url:
                continue
            hits.append(
                SearchHit(
                    title=str(row.get("title") or url).strip(),
                    url=url,
                    snippet=str(row.get("description") or "").strip()[:400],
                )
            )
        return hits
