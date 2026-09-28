"""LCSD / Hong Kong Cultural Centre — free cultural programmes (read-only HTML)."""
from __future__ import annotations

import re
from typing import Any

from .common import clean_text, make_event, polite_get, soup_html

SOURCE = "康文署／香港文化中心"
URL = "https://www.lcsd.gov.hk/tc/hkcc/programmes/audbuilding/freeculturalprogrammes.html"


def _parse_date_bits(date_raw: str) -> tuple[str, str | None]:
    date_text = clean_text(date_raw)
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", date_text)
    if not m:
        return date_text, None
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return date_text, f"{y:04d}-{mo:02d}-{d:02d}"


def _table_kv(table) -> dict[str, str]:
    """Parse label/value rows; row0 single-cell = title."""
    out: dict[str, str] = {}
    rows = table.find_all("tr")
    if not rows:
        return out
    first_cells = [clean_text(td.get_text(" ", strip=True)) for td in rows[0].find_all(["td", "th"])]
    if len(first_cells) == 1 and first_cells[0]:
        out["title"] = first_cells[0]
    for tr in rows[1:]:
        cells = [clean_text(td.get_text(" ", strip=True)) for td in tr.find_all(["td", "th"])]
        cells = [c for c in cells if c]
        if len(cells) >= 2:
            out[cells[0]] = cells[1]
        elif len(cells) == 1 and cells[0] in ("免費入場",):
            out["budget"] = "免費入場"
    return out


def fetch_events(session=None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    meta: dict[str, Any] = {"source": SOURCE, "url": URL, "ok": False, "count": 0, "error": None}
    try:
        resp = polite_get(URL, session=session)
        soup = soup_html(resp.text)
        events: list[dict[str, Any]] = []
        page_free = "免費入場" in resp.text or "免費文化節目" in resp.text

        for table in soup.find_all("table"):
            kv = _table_kv(table)
            title = kv.get("title") or ""
            if not title or title.startswith(".") or "節目查詢" in title:
                continue
            if "日期" not in "".join(kv.keys()) and "地點" not in "".join(kv.keys()):
                continue
            date_raw = kv.get("日期、時間") or kv.get("日期") or kv.get("日期時間") or ""
            location = kv.get("地點") or "香港文化中心"
            date_text, start_date = _parse_date_bits(date_raw)
            extra = " ".join(f"{k} {v}" for k, v in kv.items())
            tags_extra = ["室內", "長廳"]
            if re.search(r"[（(]六[）)]|星期六|週末|周末", date_text + title):
                tags_extra += ["週末", "半日"]
            type_hint = "長廳"
            if any(k in title for k in ("音樂會", "演奏會", "演唱會", "公演", "表演")):
                type_hint = "表演"
                tags_extra = [t for t in tags_extra if t != "長廳"] + ["表演"]
            ev = make_event(
                title=title,
                location=location,
                source=SOURCE,
                source_url=URL,
                date_text=date_text,
                start_date=start_date,
                budget_text="免費入場" if page_free else kv.get("budget", ""),
                extra_text=extra,
                tags_extra=tags_extra,
                type_hint=type_hint,
            )
            events.append(ev)

        meta["ok"] = True
        meta["count"] = len(events)
        return events, meta
    except Exception as e:
        meta["error"] = f"{type(e).__name__}: {e}"
        return [], meta
