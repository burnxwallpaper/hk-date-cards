"""Discover Hong Kong events page — parse embedded public event JSON (read-only).

robots.txt allows /tc/events.html (only thank-you / search / map paths disallowed).
Soft-fails if structure changes or JS shell has no container.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .common import clean_text, make_event, polite_get

SOURCE = "香港旅遊發展局 DiscoverHK"
URL = "https://www.discoverhongkong.com/tc/events.html"

# Prefer date-card-friendly categories (museums / art / mall / festivals / exhibitions)
WANTED_CAT_EXACT = {
    "博物館、藝廊或公共空間",
    "藝術",
    "藝術展",
    "商場活動",
    "節慶活動",
}
WANTED_TITLE_KW = (
    "展覽",
    "市集",
    "開放日",
    "美術館",
    "博物館",
    "藝廊",
    "快閃",
    "燈光",
    "燈飾",
    "花燈",
    "導賞",
    "免費",
    "長廊",
    "海濱",
)
# Skip pure ticketed mega-concerts / sports unless also exhibition-like
SKIP_CAT_IF_ONLY = {"演唱會", "賽馬", "運動"}


def _strip_html(s: str) -> str:
    s = re.sub(r"<br\s*/?>", " ", s or "", flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    return clean_text(s)


def _pick_type(title: str, cats: list[str], addr: str, desc: str) -> str | None:
    blob = f"{title} {' '.join(cats)} {addr} {desc}"
    if "商場活動" in cats or any(k in blob for k in ("商場", "mall", "快閃")):
        return "商場漫遊"
    if any(k in blob for k in ("市集", "廟會", "墟")):
        return "市集"
    if any(k in blob for k in ("開放日", "Open Day")):
        return "開放日"
    if "博物館、藝廊或公共空間" in cats or any(k in blob for k in ("美術館", "博物館", "藝廊", "M+", "故宮")):
        if "展覽" in blob or "展" in title:
            return "展覽"
        return "美術館"
    if "藝術展" in cats or "展覽" in title or "展" in title[-6:]:
        return "展覽"
    if any(k in blob for k in ("燈光", "燈飾", "花燈", "煙花", "夜景", "倒數", "跨年", "冬日巡禮", "繽紛冬日")):
        return "夜景散步"
    if any(k in cats for k in ("音樂會", "演唱會", "舞蹈", "舞台製作")) or any(
        k in blob for k in ("演唱會", "音樂會", "演奏會", "公演")
    ):
        return "表演"
    if "藝術" in cats:
        return "展覽"
    if any(k in blob for k in ("海濱", "散步", "公園")):
        return "戶外走走"
    return None


def _wanted(it: dict[str, Any]) -> bool:
    title = it.get("title") or ""
    cats = list(it.get("eventCategories") or [])
    desc = _strip_html(it.get("description") or "")
    blob = f"{title} {' '.join(cats)} {desc}"
    if any(c in WANTED_CAT_EXACT for c in cats):
        return True
    if any(k in blob for k in WANTED_TITLE_KW):
        return True
    # Skip concert-only / sports-only
    if cats and all(c in SKIP_CAT_IF_ONLY or c in ("DHK-direct", "娛樂", "spotlight") for c in cats):
        return False
    return False


def fetch_events(session=None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    meta: dict[str, Any] = {"source": SOURCE, "url": URL, "ok": False, "count": 0, "error": None}
    try:
        resp = polite_get(URL, session=session, timeout=40)
        m = re.search(r'prepareDataContainer\("data_container_4",\s*(\{.*?\})\s*\);', resp.text, re.S)
        if not m:
            meta["skipped"] = True
            meta["error"] = "Soft-skip: embedded data_container_4 JSON not found (page may be JS-only now)"
            return [], meta
        data = json.loads(m.group(1))
        items = data.get("items") or []
        events: list[dict[str, Any]] = []
        for it in items:
            if not _wanted(it):
                continue
            title = clean_text(it.get("title") or "")
            if not title:
                continue
            addr = _strip_html(it.get("addr") or "") or "地點待查"
            desc = _strip_html(it.get("description") or "")
            cats = list(it.get("eventCategories") or [])
            start = (it.get("startDate") or "")[:10] or None
            end = (it.get("endDate") or "")[:10] or None
            if start and end and start != end:
                date_text = f"{start} 至 {end}"
            else:
                date_text = start or ""
            # Prefer DiscoverHK detail page as source_url when available
            source_url = it.get("pageUrl") or URL
            if isinstance(source_url, str) and source_url.startswith("/"):
                source_url = "https://www.discoverhongkong.com" + source_url
            type_hint = _pick_type(title, cats, addr, desc)
            tags_extra: list[str] = []
            if type_hint:
                tags_extra.append(type_hint)
            if any(c in cats for c in ("親子",)) or "親子" in desc:
                tags_extra.append("親子向")
            if "演唱會" in cats or "演唱會" in title:
                tags_extra.append("大型公演")
            budget_blob = f"{title} {desc}"
            # Mall / festival / market-ish without stated price → force_free via type
            ev = make_event(
                title=title,
                location=addr,
                source=SOURCE,
                source_url=source_url,
                date_text=date_text,
                start_date=start,
                end_date=end,
                budget_text=budget_blob,
                extra_text=f"{' '.join(cats)} {desc}",
                tags_extra=tags_extra,
                type_hint=type_hint,
            )
            events.append(ev)

        meta["ok"] = True
        meta["count"] = len(events)
        meta["raw_items"] = len(items)
        return events, meta
    except Exception as e:
        meta["error"] = f"{type(e).__name__}: {e}"
        return [], meta
