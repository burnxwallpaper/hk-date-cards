"""新假期 WeekendHK — public weekend activities roundup article (read-only)."""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

from .common import clean_text, make_event, polite_get, soup_html, strip_detail_suffix

SOURCE = "新假期"
# Stable monthly roundup; may 404 when slug rotates — refresh soft-fails and falls back sample.
DEFAULT_URL = (
    "https://www.weekendhk.com/"
    "%e9%a6%99%e6%b8%af%e5%a5%bd%e5%8e%bb%e8%99%95/"
    "%e6%9c%ac%e9%80%b1%e6%9c%ab%e6%b4%bb%e5%8b%95%e6%8e%a8%e4%bb%8b-%e5%a5%bd%e5%8e%bb%e8%99%95-3307066/"
)
CATEGORY_URL = "https://www.weekendhk.com/category/%e9%a6%99%e6%b8%af%e5%a5%bd%e5%8e%bb%e8%99%95/"


def _find_roundup_url(session=None) -> str:
    """Prefer the known roundup; else pick latest category article matching 本週末/好去處."""
    try:
        resp = polite_get(DEFAULT_URL, session=session)
        if resp.status_code == 200 and "日期" in resp.text:
            return DEFAULT_URL
    except Exception:
        pass
    try:
        resp = polite_get(CATEGORY_URL, session=session)
        soup = soup_html(resp.text)
        for a in soup.select("a[href]"):
            href = a.get("href") or ""
            text = clean_text(a.get_text(" ", strip=True))
            if "本週末" in text or "好去處2026" in text or "熱門活動推介" in text:
                return urljoin(CATEGORY_URL, href)
    except Exception:
        pass
    return DEFAULT_URL


def _parse_start_date(date_text: str) -> str | None:
    m = re.search(r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", date_text)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{y:04d}-{mo:02d}-{d:02d}"
    m = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日", date_text)
    if m:
        # assume current article year 2026 if year omitted
        mo, d = int(m.group(1)), int(m.group(2))
        return f"2026-{mo:02d}-{d:02d}"
    return None


def fetch_events(session=None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    meta: dict[str, Any] = {"source": SOURCE, "url": None, "ok": False, "count": 0, "error": None}
    try:
        url = _find_roundup_url(session=session)
        meta["url"] = url
        resp = polite_get(url, session=session)
        soup = soup_html(resp.text)
        events: list[dict[str, Any]] = []

        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            cells = []
            for tr in rows:
                for td in tr.find_all(["td", "th"]):
                    cells.append(clean_text(td.get_text(" ", strip=True)))
            cells = [c for c in cells if c]
            if len(cells) < 2:
                continue
            joined = " ".join(cells)
            if "地點" not in joined and not any(c.startswith("地點") for c in cells):
                continue
            # Skip placeholder/demo tables
            if "Lorem" in joined or "Ipsum" in joined:
                continue

            title = strip_detail_suffix(cells[0])
            date_text = ""
            location = ""
            for i, c in enumerate(cells):
                if c in ("日期", "地點"):
                    continue
                if c.startswith("日期：") or c.startswith("日期:"):
                    date_text = clean_text(c.split("：", 1)[-1].split(":", 1)[-1])
                elif c.startswith("地點：") or c.startswith("地點:"):
                    location = clean_text(c.split("：", 1)[-1].split(":", 1)[-1])
                elif i > 0 and cells[i - 1] == "日期":
                    date_text = c
                elif i > 0 and cells[i - 1] == "地點":
                    location = c

            if not title or not location:
                continue
            if title in ("日期", "地點"):
                continue

            # Budget only from title + table cells (paragraphs often mention free side-perks).
            budget_blob = f"{title} {joined}"

            start_date = _parse_start_date(date_text)
            ev = make_event(
                title=title,
                location=location,
                source=SOURCE,
                source_url=url,
                date_text=date_text,
                start_date=start_date,
                budget_text=budget_blob,
                extra_text=joined,
            )
            events.append(ev)

        meta["ok"] = True
        meta["count"] = len(events)
        return events, meta
    except Exception as e:
        meta["error"] = f"{type(e).__name__}: {e}"
        return [], meta
