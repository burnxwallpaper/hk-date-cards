"""Timable — intentionally skipped (robots.txt Disallow: / for User-agent: *)."""
from __future__ import annotations

from typing import Any

SOURCE = "Timable"
REASON = (
    "Skipped: https://timable.com/robots.txt sets `User-agent: *` → `Disallow: /`. "
    "Personal scraper must not crawl against that. No events fetched."
)


def fetch_events(session=None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    return [], {
        "source": SOURCE,
        "url": "https://timable.com/hk/zh/",
        "ok": False,
        "skipped": True,
        "count": 0,
        "error": REASON,
    }
