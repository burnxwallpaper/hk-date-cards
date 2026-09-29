"""新假期 WeekendHK — public weekend / market / exhibition roundup articles (read-only)."""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

from .common import (
    clean_text,
    infer_type,
    make_event,
    polite_get,
    soup_html,
    strip_detail_suffix,
    _is_food_not_walk,
    _has_mall_signal,
)

SOURCE = "新假期"
# Stable monthly roundup; may 404 when slug rotates — refresh soft-fails and falls back sample.
DEFAULT_URL = (
    "https://www.weekendhk.com/"
    "%e9%a6%99%e6%b8%af%e5%a5%bd%e5%8e%bb%e8%99%95/"
    "%e6%9c%ac%e9%80%b1%e6%9c%ab%e6%b4%bb%e5%8b%95%e6%8e%a8%e4%bb%8b-%e5%a5%bd%e5%8e%bb%e8%99%95-3307066/"
)
CATEGORY_URL = "https://www.weekendhk.com/category/%e9%a6%99%e6%b8%af%e5%a5%bd%e5%8e%bb%e8%99%95/"

# Prefer articles whose titles suggest markets / exhibitions / malls / open days / roundups
ARTICLE_TITLE_KW = (
    "本週末",
    "熱門活動",
    "好去處",
    "市集",
    "展覽",
    "美術館",
    "商場",
    "開放日",
    "快閃",
    "燈",
    "嘉年華",
    "花燈",
    "夜",
    "中秋",
)
# Skip promo / parking listicles that match 商場 but are not dating events
ARTICLE_TITLE_SKIP = (
    "泊車",
    "停車",
    "優惠碼",
    "信用卡優惠",
    "消費滿",
)
MAX_ARTICLES = 6


def _article_urls(session=None) -> list[str]:
    """Collect up to MAX_ARTICLES relevant public article URLs."""
    found: list[str] = []
    seen: set[str] = set()

    def add(url: str) -> None:
        url = url.split("#")[0].rstrip("/") + "/"
        if url in seen:
            return
        if "weekendhk.com" not in url:
            return
        # skip category/tag/search hubs
        if any(x in url for x in ("/category/", "/tag/", "/?", "/author/", "/page/")):
            return
        seen.add(url)
        found.append(url)

    # Prefer known roundup if alive
    try:
        resp = polite_get(DEFAULT_URL, session=session)
        if resp.status_code == 200 and "日期" in resp.text:
            add(DEFAULT_URL)
    except Exception:
        pass

    try:
        resp = polite_get(CATEGORY_URL, session=session)
        soup = soup_html(resp.text)
        for a in soup.select("a[href]"):
            href = a.get("href") or ""
            text = clean_text(a.get_text(" ", strip=True))
            if not any(k in text for k in ARTICLE_TITLE_KW):
                continue
            if any(k in text for k in ARTICLE_TITLE_SKIP):
                continue
            add(urljoin(CATEGORY_URL, href))
            if len(found) >= MAX_ARTICLES:
                break
    except Exception:
        pass

    if not found:
        found = [DEFAULT_URL]

    def _roundup_score(u: str) -> int:
        # Prefer the evergreen weekend roundup article over one-off listicles
        if "3307066" in u or "%e6%9c%ac%e9%80%b1%e6%9c%ab%e6%b4%bb%e5%8b%95" in u or "本週末" in u:
            return 0
        if "好去處" in u or "%e5%a5%bd%e5%8e%bb%e8%99%95" in u:
            return 1
        return 2

    found.sort(key=_roundup_score)
    return found[:MAX_ARTICLES]


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


_MEGA_CONCERT_KW = (
    "巡迴演唱會",
    "世界巡迴",
    "World Tour",
    "主場館",
    "紅館",
    "體育館",
    "啟德體育園",
    "ARENA",
    "Arena",
)


def _skip_event(title: str, joined: str) -> bool:
    """Drop food buffets & mega ticketed concerts from dating-card feed."""
    blob = f"{title} {joined}"
    if _is_food_not_walk(blob) and any(k in blob for k in ("放題", "自助餐", "燒烤放題", "海鮮燒烤")):
        return True
    if "演唱會" in title and any(k in blob for k in _MEGA_CONCERT_KW):
        return True
    if any(k in title for k in ("巡迴演唱會", "世界巡迴演唱會")):
        return True
    return False


def _type_hint_from_title(title: str, joined: str) -> str | None:
    blob = f"{title} {joined}"
    # Food buffets — no couple-date type (caller may skip entirely)
    if _is_food_not_walk(blob) and any(k in blob for k in ("放題", "自助餐", "燒烤")):
        return None
    # Performance BEFORE museum (avoid 博物館道 → 美術館)
    if any(k in blob for k in ("演唱會", "音樂會", "演奏會", "公演", "音樂劇", "舞台劇")):
        return "表演"
    if any(k in blob for k in ("舞火龍", "煙花", "亮燈", "綵燈", "倒數")):
        return "夜景散步"
    if any(k in blob for k in ("體檢", "VetCare")):
        return "開放日"
    if any(k in blob for k in ("市集", "墟", "嘉年華")):
        return "市集"
    if any(k in blob for k in ("開放日",)):
        return "開放日"
    if _has_mall_signal(blob) or any(k in blob for k in ("快閃", "pop-up", "Pop-up")):
        return "商場漫遊"
    if any(k in blob for k in ("美術館", "博物館", "藝術館")) and "音樂會" not in blob:
        # Ignore 博物館道 street false positive via shared infer
        return infer_type(title, "", joined) or "美術館"
    if any(k in blob for k in ("展覽", "展覧", "紀念展")):
        return "展覽"
    if any(k in blob for k in ("燈", "夜景", "煙花", "亮燈")):
        return "夜景散步"
    if any(k in blob for k in ("大堂", "長廳")):
        return "長廳"
    if any(k in blob for k in ("打卡", "裝置", "聯乘", "×")):
        if _has_mall_signal(blob):
            return "商場漫遊"
        return "室內打卡"
    return infer_type(title, "", joined)


def _parse_article(url: str, session=None) -> list[dict[str, Any]]:
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
        if title in ("日期", "地點", "適用日子", "時間", "收費", "詳情"):
            continue
        if len(title) < 4:
            continue
        if _skip_event(title, joined):
            continue

        budget_blob = f"{title} {joined}"
        start_date = _parse_start_date(date_text)
        type_hint = _type_hint_from_title(title, joined)
        # Soft mall venues (海港城 etc.) — ensure type + free browse budget
        if not type_hint:
            type_hint = infer_type(title, location, joined)
        if type_hint in {"商場漫遊", "室內打卡", "市集", "開放日", "長廳"} and "免費" not in budget_blob:
            budget_blob = budget_blob + " 免費入場"
        tags_extra = [type_hint] if type_hint else None
        if type_hint == "表演" and any(k in title for k in ("演唱會", "巡迴")):
            tags_extra = [type_hint, "大型公演"]
        ev = make_event(
            title=title,
            location=location,
            source=SOURCE,
            source_url=url,
            date_text=date_text,
            start_date=start_date,
            budget_text=budget_blob,
            extra_text=joined,
            type_hint=type_hint,
            tags_extra=tags_extra,
        )
        events.append(ev)

    # Fallback: some listicles (中秋燈飾等) use paragraphs instead of tables
    if not events:
        events.extend(_parse_article_paragraphs(soup, url))
    return events


def _parse_article_paragraphs(soup, url: str) -> list[dict[str, Any]]:
    """Best-effort: heading + nearby 日期/地點 lines when no event tables exist."""
    events: list[dict[str, Any]] = []
    root = soup.select_one("article") or soup.select_one(".entry-content") or soup
    blocks = root.find_all(["h2", "h3", "h4", "strong"])
    seen_titles: set[str] = set()
    for h in blocks:
        title = strip_detail_suffix(clean_text(h.get_text(" ", strip=True)))
        if not title or len(title) < 4 or len(title) > 80:
            continue
        if title in ("日期", "地點", "詳情", "時間", "收費"):
            continue
        if title in seen_titles:
            continue
        # Collect following sibling text (a few nodes)
        chunks: list[str] = []
        sib = h.find_parent()
        cursor = h
        for _ in range(8):
            cursor = cursor.find_next_sibling() if hasattr(cursor, "find_next_sibling") else None
            if cursor is None and sib is not None:
                # walk parent's next bits
                break
            if cursor is None:
                break
            if getattr(cursor, "name", None) in ("h2", "h3", "h4"):
                break
            chunks.append(clean_text(cursor.get_text(" ", strip=True)))
        # Also check parent container text
        parent_txt = clean_text(h.parent.get_text(" ", strip=True)) if h.parent else ""
        joined = " ".join(chunks) or parent_txt
        if "地點" not in joined and "日期" not in joined:
            continue
        date_text = ""
        location = ""
        m = re.search(r"日期\s*[:：]?\s*([^地點]{4,80})", joined)
        if m:
            date_text = clean_text(m.group(1))
        m = re.search(r"地點\s*[:：]?\s*([^日時間收費詳情]{2,80})", joined)
        if m:
            location = clean_text(m.group(1))
        if not location:
            continue
        if _skip_event(title, joined):
            continue
        seen_titles.add(title)
        budget_blob = f"{title} {joined}"
        start_date = _parse_start_date(date_text)
        type_hint = _type_hint_from_title(title, joined) or infer_type(title, location, joined)
        if type_hint in {"商場漫遊", "室內打卡", "市集", "開放日", "長廳", "夜景散步"} and "免費" not in budget_blob:
            budget_blob = budget_blob + " 免費入場"
        tags_extra = [type_hint] if type_hint else None
        ev = make_event(
            title=title,
            location=location,
            source=SOURCE,
            source_url=url,
            date_text=date_text,
            start_date=start_date,
            budget_text=budget_blob,
            extra_text=joined,
            type_hint=type_hint,
            tags_extra=tags_extra,
        )
        events.append(ev)
        if len(events) >= 12:
            break
    return events


def fetch_events(session=None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    meta: dict[str, Any] = {"source": SOURCE, "url": None, "ok": False, "count": 0, "error": None}
    try:
        urls = _article_urls(session=session)
        meta["url"] = urls[0] if urls else None
        meta["urls"] = urls
        events: list[dict[str, Any]] = []
        errors: list[str] = []
        for url in urls:
            try:
                events.extend(_parse_article(url, session=session))
            except Exception as e:
                errors.append(f"{url}: {type(e).__name__}: {e}")
        meta["ok"] = True
        meta["count"] = len(events)
        if errors:
            meta["note"] = " | ".join(errors[:5])
        return events, meta
    except Exception as e:
        meta["error"] = f"{type(e).__name__}: {e}"
        return [], meta
