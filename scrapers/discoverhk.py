"""Discover Hong Kong events page — parse embedded public event JSON (read-only).

robots.txt allows /tc/events.html (only thank-you / search / map paths disallowed).
Soft-fails if structure changes or JS shell has no container.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .common import (
    clean_text,
    infer_type,
    make_event,
    polite_get,
    _is_food_not_walk,
    _is_race_sport,
    _is_performance,
    _has_mall_signal,
    _has_museum_signal,
)

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

# Mega ticketed concerts — not free/$100 dating cards
_MEGA_CONCERT_KW = (
    "巡迴演唱會",
    "世界巡迴",
    "World Tour",
    "Asia Tour",
    "亞洲巡迴",
    "主場館",
    "紅館",
    "體育館",
    "啟德體育園",
    "ARENA",
)


def _strip_html(s: str) -> str:
    s = re.sub(r"<br\s*/?>", " ", s or "", flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    return clean_text(s)


def _is_mega_concert(title: str, cats: list[str], desc: str = "") -> bool:
    blob = f"{title} {' '.join(cats)} {desc}"
    if "演唱會" in cats and not any(k in blob for k in ("展覽", "市集", "開放日", "免費")):
        return True
    if "演唱會" in title or any(k in blob for k in _MEGA_CONCERT_KW):
        if _is_performance(blob, title=title) and not any(k in blob for k in ("免費", "長廳", "大堂")):
            return True
    return False


def _pick_type(title: str, cats: list[str], addr: str, desc: str) -> str | None:
    blob = f"{title} {' '.join(cats)} {addr} {desc}"

    # Food festivals / buffets — not 戶外走走
    if _is_food_not_walk(blob):
        if any(k in blob for k in ("市集", "墟")):
            return "市集"
        return None

    # Spectator sports / sailing races — not couple outdoor walk
    if _is_race_sport(blob) and ("運動" in cats or "帆船" in blob):
        return None

    # Markets / temple fairs BEFORE performance (desc often says 街頭表演)
    if any(k in blob for k in ("市集", "廟會", "墟")) or ("藝術展" in cats and "市集" in (title + desc)):
        return "市集"
    if any(k in blob for k in ("開放日", "Open Day")):
        return "開放日"

    # Clear exhibition/fair title wins even at a mall (e.g. K11 沉浸式展)
    if (
        "藝術展" in cats
        or "博覽會" in cats
        or "展覽" in title
        or "博覽" in title
        or "個展" in title
        or "紀念展" in title
        or (len(title) >= 2 and "展" in title[-8:])
    ):
        return "展覽"

    # Soft mall venues (MegaBox / apm / 海港城) beat museum-category co-tags
    if "商場活動" in cats or _has_mall_signal(f"{title} {addr}"):
        return "商場漫遊"

    # Museum / exhibition BEFORE dance co-tags (e.g. 個展 + 舞蹈 cat)
    if "博物館、藝廊或公共空間" in cats or _has_museum_signal(f"{title} {addr}"):
        if any(k in blob for k in ("展覽", "展", "紀念展", "公開展出", "個展")):
            return "展覽"
        return "美術館"

    # Concerts / shows — strong title/cat signals only (not desc 街頭表演)
    if any(c in cats for c in ("音樂會", "演唱會", "舞台製作")) or _is_performance(
        blob, title=title
    ):
        # Dance-only cat with museum already handled; pure 舞蹈 festival → 表演
        return "表演"
    if "舞蹈" in cats and not any(k in blob for k in ("展覽", "市集", "博物館")):
        return "表演"

    if any(k in blob for k in ("燈光", "燈飾", "花燈", "煙花", "夜景", "倒數", "跨年", "冬日巡禮", "繽紛冬日")):
        return "夜景散步"
    if any(k in blob for k in ("打卡", "裝置藝術", "藝術裝置")):
        return "室內打卡"
    if "藝術" in cats:
        return "展覽"
    # Outdoor walk only for genuine promenade / park strolls
    if any(k in blob for k in ("海濱長廊", "散步", "公園散步")) and not _is_race_sport(blob):
        return "戶外走走"
    # Fall back to shared infer_type (mall venues, collabs, etc.)
    return infer_type(title, addr, f"{' '.join(cats)} {desc}")


def _wanted(it: dict[str, Any]) -> bool:
    title = it.get("title") or ""
    cats = list(it.get("eventCategories") or [])
    desc = _strip_html(it.get("description") or "")
    blob = f"{title} {' '.join(cats)} {desc}"

    # Drop mega ticketed concerts from dating-card feed
    if _is_mega_concert(title, cats, desc):
        return False
    # Drop pure spectator sports / sailing world cups
    if cats and all(c in SKIP_CAT_IF_ONLY or c in ("DHK-direct", "娛樂", "spotlight") for c in cats):
        return False
    if _is_race_sport(blob) and "運動" in cats and not any(k in blob for k in ("展覽", "市集", "免費")):
        return False
    # Drop wine & dine style paid food fests (not free dating walk)
    if _is_food_not_walk(blob) and "美酒佳餚" in (cats + [title]):
        return False

    if any(c in WANTED_CAT_EXACT for c in cats):
        return True
    if any(k in blob for k in WANTED_TITLE_KW):
        return True
    return False


def _budget_blob(title: str, desc: str, cats: list[str], type_hint: str | None) -> str:
    """Build text for budget parsing; hint free for known-free categories."""
    parts = [title, desc, " ".join(cats)]
    # Mall activities / markets / open days → force_free via type; reinforce free signal
    if type_hint in {"商場漫遊", "市集", "開放日", "長廳", "室內打卡"}:
        parts.append("免費入場")
    # Outdoor public permanent art
    if re.search(r"公開展出|常設戶外|免費開放|免費參觀", desc):
        parts.append("公開展出 免費開放")
    # LCSD-style museum permanent language
    if re.search(r"常設展覽", desc) and not re.search(r"(?:HK\$|\$)\s*\d+|票價|門票", desc):
        parts.append("常設展覽免費")
    return " ".join(p for p in parts if p)


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
        skipped_concerts = 0
        for it in items:
            title = clean_text(it.get("title") or "")
            if not title:
                continue
            cats = list(it.get("eventCategories") or [])
            desc = _strip_html(it.get("description") or "")
            if _is_mega_concert(title, cats, desc):
                skipped_concerts += 1
                continue
            if not _wanted(it):
                continue
            addr = _strip_html(it.get("addr") or "") or "地點待查"
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
            # Still no type? try shared infer on title+addr only
            if not type_hint:
                type_hint = infer_type(title, addr, " ".join(cats))
            tags_extra: list[str] = []
            if type_hint:
                tags_extra.append(type_hint)
            if any(c in cats for c in ("親子",)) or "親子" in desc:
                tags_extra.append("親子向")
            # Paid concerts that somehow remain → mark 大型公演, keep budget 未知
            if "演唱會" in cats or "演唱會" in title:
                tags_extra.append("大型公演")
            budget_blob = _budget_blob(title, desc, cats, type_hint)
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
                tags_extra=tags_extra or None,
                type_hint=type_hint,
            )
            events.append(ev)

        meta["ok"] = True
        meta["count"] = len(events)
        meta["raw_items"] = len(items)
        meta["skipped_mega_concerts"] = skipped_concerts
        return events, meta
    except Exception as e:
        meta["error"] = f"{type(e).__name__}: {e}"
        return [], meta
