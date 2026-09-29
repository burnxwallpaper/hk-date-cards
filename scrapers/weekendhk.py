"""新假期 WeekendHK — public weekend / market / exhibition roundup articles (read-only)."""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, unquote

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
# Evergreen monthly roundup slug; may go stale — discovery prefers fresher articles.
DEFAULT_URL = (
    "https://www.weekendhk.com/"
    "%e9%a6%99%e6%b8%af%e5%a5%bd%e5%8e%bb%e8%99%95/"
    "%e6%9c%ac%e9%80%b1%e6%9c%ab%e6%b4%bb%e5%8b%95%e6%8e%a8%e4%bb%8b-%e5%a5%bd%e5%8e%bb%e8%99%95-3307066/"
)
CATEGORY_URL = "https://www.weekendhk.com/category/%e9%a6%99%e6%b8%af%e5%a5%bd%e5%8e%bb%e8%99%95/"
# Extra listing hubs (robots-allow) that surface seasonal roundups
EXTRA_LIST_URLS = (
    CATEGORY_URL,
    CATEGORY_URL.rstrip("/") + "/page/2/",
    "https://www.weekendhk.com/",
)

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
    "綵燈",
    "夜",
    "中秋",
    "萬聖節",
    "萬聖",
    "光影",
    "打卡",
    "週末",
)
# Skip promo / parking listicles that match 商場 but are not dating events
ARTICLE_TITLE_SKIP = (
    "泊車",
    "停車",
    "優惠碼",
    "信用卡優惠",
    "消費滿",
    "深圳好去處",
    "台灣好去處",
    "澳門",
)
# Known fresh seasonal roundups (mid-autumn / mall installations) when category lags
SEED_URLS = (
    DEFAULT_URL,
    # 中秋好去處2026 — structured 日期/地點 lists through mid-Oct
    "https://www.weekendhk.com/%e9%a6%99%e6%b8%af%e5%a5%bd%e5%8e%bb%e8%99%95/"
    "%e4%b8%ad%e7%a7%8b-%e7%b6%ad%e5%9c%92-%e5%a5%bd%e5%8e%bb%e8%99%95-%e5%a4%a7%e5%9d%91-3511860/",
    # MegaBox 巨型哥基 — through early Oct
    "https://www.weekendhk.com/%e9%a6%99%e6%b8%af%e5%a5%bd%e5%8e%bb%e8%99%95/"
    "%e4%b9%9d%e9%be%8d%e7%81%a3%e9%80%be-mega-sky-megabox-3486891/",
    # 藍屋中秋燈籠 — through mid-Oct
    "https://www.weekendhk.com/%e9%a6%99%e6%b8%af%e5%a5%bd%e5%8e%bb%e8%99%95/"
    "%e7%81%a3%e4%bb%94-%e8%97%8d%e5%b1%8b-%e4%b8%ad%e7%a7%8b%e7%af%80-%e7%87%88%e7%b1%a0-3505647/",
    # 利東街中秋燈籠 — through mid-Oct
    "https://www.weekendhk.com/%e9%a6%99%e6%b8%af%e5%a5%bd%e5%8e%bb%e8%99%95/"
    "%e5%88%a9%e6%9d%b1%e8%a1%97-%e4%b8%ad%e7%a7%8b-%e7%87%88%e7%b1%a0-%e5%a5%bd%e5%8e%bb%e8%99%95-3510890/",
    # 滙映山頂光影 — open-ended from June
    "https://www.weekendhk.com/%e9%a6%99%e6%b8%af%e5%a5%bd%e5%8e%bb%e8%99%95/"
    "%e5%bd%99%e8%b1%90%e4%bf%9d%e9%9a%aa-%e5%b1%b1%e9%a0%82%e7%ba%9c%e8%bb%8a-%e5%bd%99%e6%98%a0%e5%b1%b1%e9%a0%82-3454806/",
)
MAX_ARTICLES = 10

_POST_ID_RE = re.compile(r"-(\d{6,})/?$")


def _post_id(url: str) -> int:
    m = _POST_ID_RE.search(unquote(url))
    return int(m.group(1)) if m else 0


def _article_urls(session=None) -> list[str]:
    """Collect up to MAX_ARTICLES relevant public article URLs (fresher first)."""
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
        # skip obvious non-article hub paths
        path = unquote(url)
        if path.rstrip("/").endswith("好去處") and path.count("/") <= 4 and "-" not in path.split("/")[-2]:
            # e.g. /大灣區好去處/ hub without a post slug
            if not _post_id(url):
                return
        # Collapse encoding variants of the same post id
        pid = _post_id(url)
        if pid and any(_post_id(u) == pid for u in found):
            return
        seen.add(url)
        found.append(url)

    for seed in SEED_URLS:
        add(seed)

    # Prefer known roundup if alive (also already in seeds)
    try:
        resp = polite_get(DEFAULT_URL, session=session)
        if resp.status_code == 200 and ("日期" in resp.text or "地點" in resp.text):
            add(DEFAULT_URL)
    except Exception:
        pass

    for list_url in EXTRA_LIST_URLS:
        try:
            resp = polite_get(list_url, session=session)
            soup = soup_html(resp.text)
            for a in soup.select("a[href]"):
                href = a.get("href") or ""
                text = clean_text(a.get_text(" ", strip=True))
                if not any(k in text for k in ARTICLE_TITLE_KW):
                    continue
                if any(k in text for k in ARTICLE_TITLE_SKIP):
                    continue
                add(urljoin(list_url, href))
        except Exception:
            pass

    if not found:
        found = [DEFAULT_URL]

    def _score(u: str) -> tuple:
        # Fresher post IDs first; then prefer weekend roundup / 好去處 seasonal listicles
        pid = _post_id(u)
        # Negate pid so higher IDs sort first
        roundup = 0
        if "3307066" in u or "本週末" in unquote(u) or "%e6%9c%ac%e9%80%b1%e6%9c%ab" in u:
            roundup = -1  # slight boost for evergreen roundup
        if "中秋" in unquote(u) or "mega" in u.lower() or "藍屋" in unquote(u) or "利東街" in unquote(u):
            roundup = -2  # seasonal listicles often have current date ranges
        return (roundup, -pid)

    found.sort(key=_score)
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
    if any(k in blob for k in ("舞火龍", "煙花", "亮燈", "綵燈", "倒數", "光影", "花燈", "燈籠")):
        return "夜景散步"
    if any(k in blob for k in ("體檢", "VetCare")):
        return "開放日"
    if any(k in blob for k in ("市集", "墟", "嘉年華")):
        return "市集"
    if any(k in blob for k in ("開放日",)):
        return "開放日"
    if _has_mall_signal(blob) or any(k in blob for k in ("快閃", "pop-up", "Pop-up", "巨型", "打卡")):
        if any(k in blob for k in ("市集", "墟")):
            return "市集"
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


def _extract_date_location(joined: str) -> tuple[str, str]:
    """Pull date_text + location from a fact blob (ul/li or paragraph)."""
    date_text = ""
    location = ""
    # Normalise double-colon typos (日期::)
    blob = joined.replace("：", ":").replace("::", ":")

    m = re.search(
        r"(?:活動)?日期(?:及時間)?\s*[:：]?\s*(.+?)(?=\s*(?:地點|集合地點|時間|亮燈時間|費用|開放時間|參與方式|交通|活動查詢|$))",
        blob,
    )
    if not m:
        m = re.search(
            r"展出日期\s*[:：]?\s*(.+?)(?=\s*(?:地點|時間|費用|$))",
            blob,
        )
    if m:
        date_text = clean_text(m.group(1))

    m = re.search(
        r"(?:集合)?地點\s*[:：]?\s*(.+?)(?=\s*(?:日期|活動日期|時間|亮燈時間|費用|開放時間|參與方式|交通|活動查詢|展出日期|$))",
        blob,
    )
    if m:
        location = clean_text(m.group(1))
        # Trim trailing noise after first sentence-ish chunk
        location = re.split(r"\s{2,}|\s+(?=時間|費用|開放)", location)[0].strip(" ，,;；")

    return date_text, location


def _title_from_blob(joined: str) -> str:
    """Prefer 「quoted」 event name embedded before 日期 in fact blobs."""
    blob = joined.replace("：", ":")
    # e.g. 滙豐保險「滙映山頂」光影匯演演出詳情 日期:...
    m = re.search(r"「([^」]{2,40})」", blob)
    if m and "日期" in blob[blob.find(m.group(0)): blob.find(m.group(0)) + 80]:
        return clean_text(m.group(1))
    m = re.search(r"(.{2,40}?)(?:演出)?詳情\s*(?:日期|展出日期)", blob)
    if m:
        t = strip_detail_suffix(clean_text(m.group(1)))
        t = re.sub(r"^\d+\.\s*", "", t)
        if 4 <= len(t) <= 60 and "圖片來源" not in t:
            return t
    return ""


def _title_near(el) -> str:
    """Nearest preceding heading / strong as event title."""
    for prev in el.find_all_previous(["h2", "h3", "h4"]):
        t = strip_detail_suffix(clean_text(prev.get_text(" ", strip=True)))
        if not t or len(t) < 3 or len(t) > 100:
            continue
        if t in ("日期", "地點", "詳情", "時間", "收費", "活動詳情"):
            continue
        if "攻略" in t and "打卡" in t:
            continue  # marketing subheads, not event names
        # Strip leading "1." numbering
        t = re.sub(r"^\d+\.\s*", "", t)
        return t
    for prev in el.find_all_previous(["strong"]):
        t = strip_detail_suffix(clean_text(prev.get_text(" ", strip=True)))
        if not t or len(t) < 3 or len(t) > 80:
            continue
        if t in ("日期", "地點", "詳情", "時間", "收費", "活動詳情"):
            continue
        t = re.sub(r"^\d+\.\s*", "", t)
        return t
    return ""


def _build_event(title: str, location: str, date_text: str, joined: str, url: str) -> dict[str, Any] | None:
    title = strip_detail_suffix(clean_text(title))
    location = clean_text(location)
    date_text = clean_text(date_text)
    if not title or not location:
        return None
    if title in ("日期", "地點", "適用日子", "時間", "收費", "詳情", "活動詳情"):
        return None
    if len(title) < 4:
        return None
    if _skip_event(title, joined):
        return None
    budget_blob = f"{title} {joined}"
    start_date = _parse_start_date(date_text)
    type_hint = _type_hint_from_title(title, joined)
    if not type_hint:
        type_hint = infer_type(title, location, joined)
    if type_hint in {"商場漫遊", "室內打卡", "市集", "開放日", "長廳", "夜景散步"} and "免費" not in budget_blob:
        budget_blob = budget_blob + " 免費入場"
    tags_extra = [type_hint] if type_hint else None
    if type_hint == "表演" and any(k in title for k in ("演唱會", "巡迴")):
        tags_extra = [type_hint, "大型公演"]
    return make_event(
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


def _parse_tables(soup, url: str) -> list[dict[str, Any]]:
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

        ev = _build_event(title, location, date_text, joined, url)
        if ev:
            events.append(ev)
    return events


def _parse_fact_lists(soup, url: str) -> list[dict[str, Any]]:
    """Parse ul/li (and compact p) blocks that carry 日期 + 地點 fact lines."""
    events: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    root = soup.select_one("article") or soup.select_one(".entry-content") or soup

    candidates = []
    for ul in root.find_all("ul"):
        joined = clean_text(ul.get_text(" ", strip=True))
        if ("日期" in joined or "展出日期" in joined) and ("地點" in joined or "集合地點" in joined):
            candidates.append(ul)
    # MegaBox-style paragraphs with 展出日期/地點 inline
    for p in root.find_all(["p", "div"]):
        # Avoid huge containers
        if p.name == "div" and len(p.find_all(["p", "div"])) > 6:
            continue
        joined = clean_text(p.get_text(" ", strip=True))
        if len(joined) < 12 or len(joined) > 600:
            continue
        if ("展出日期" in joined or re.search(r"(?:活動)?日期\s*[:：]", joined)) and re.search(
            r"(?:集合)?地點\s*[:：]", joined
        ):
            candidates.append(p)

    for el in candidates:
        joined = clean_text(el.get_text(" ", strip=True))
        date_text, location = _extract_date_location(joined)
        if not location:
            continue
        title = _title_from_blob(joined) or _title_near(el)
        # MegaBox: short attraction name in previous p/strong under 活動詳情
        if (not title or title in seen_titles or "啱晒" in title or "攻略" in title):
            prev = el.find_previous(["h2", "h3", "h4", "strong", "p"])
            if prev is not None:
                alt = strip_detail_suffix(clean_text(prev.get_text(" ", strip=True)))
                alt = re.sub(r"^\d+\.\s*", "", alt)
                if alt and 4 <= len(alt) <= 80 and "日期" not in alt and "地點" not in alt:
                    if "活動詳情" not in alt and "啱晒" not in alt and "攻略" not in alt:
                        title = alt
        if not title or title in seen_titles:
            continue
        # Prefer shorter display title when heading starts with numbering already stripped
        ev = _build_event(title, location, date_text, joined, url)
        if not ev:
            continue
        seen_titles.add(title)
        events.append(ev)
        if len(events) >= 20:
            break
    return events


def _parse_article_paragraphs(soup, url: str) -> list[dict[str, Any]]:
    """Best-effort: heading + nearby 日期/地點 lines when no event tables exist."""
    events: list[dict[str, Any]] = []
    root = soup.select_one("article") or soup.select_one(".entry-content") or soup
    blocks = root.find_all(["h2", "h3", "h4", "strong"])
    seen_titles: set[str] = set()
    for h in blocks:
        title = strip_detail_suffix(clean_text(h.get_text(" ", strip=True)))
        title = re.sub(r"^\d+\.\s*", "", title)
        if not title or len(title) < 4 or len(title) > 80:
            continue
        if title in ("日期", "地點", "詳情", "時間", "收費", "活動詳情"):
            continue
        if title in seen_titles:
            continue
        # Collect following text including nested ul inside later siblings / next nodes
        chunks: list[str] = []
        for node in h.find_all_next():
            name = getattr(node, "name", None)
            if name in ("h2", "h3", "h4") and node is not h:
                break
            if name in ("ul", "p"):
                t = clean_text(node.get_text(" ", strip=True))
                if t:
                    chunks.append(t)
                if len(chunks) >= 6:
                    break
            if name in ("div",) and node.get("class") and any(
                str(c).startswith("_page_") for c in (node.get("class") or [])
            ):
                t = clean_text(node.get_text(" ", strip=True))
                if t:
                    chunks.append(t)
                if len(chunks) >= 6:
                    break
        parent_txt = clean_text(h.parent.get_text(" ", strip=True)) if h.parent else ""
        joined = " ".join(chunks) or parent_txt
        if "地點" not in joined and "日期" not in joined:
            continue
        date_text, location = _extract_date_location(joined)
        if not location:
            m = re.search(r"地點\s*[:：]?\s*([^日時間收費詳情]{2,80})", joined)
            if m:
                location = clean_text(m.group(1))
        if not date_text:
            m = re.search(r"日期\s*[:：]?\s*([^地點]{4,80})", joined)
            if m:
                date_text = clean_text(m.group(1))
        if not location:
            continue
        if _skip_event(title, joined):
            continue
        ev = _build_event(title, location, date_text, joined, url)
        if not ev:
            continue
        seen_titles.add(title)
        events.append(ev)
        if len(events) >= 12:
            break
    return events


_VENUE_FP = (
    "利東街",
    "藍屋",
    "維多利亞公園",
    "維園",
    "黃大仙",
    "megabox",
    "mega sky",
    "山頂道花園",
    "凌霄閣",
    "海港城",
    "饒宗頤",
    "大澳",
)


def _venue_fp(title: str, loc: str) -> str:
    blob = f"{title} {loc}".lower()
    for v in _VENUE_FP:
        if v.lower() in blob:
            return v.lower()
    return re.sub(r"\s+", "", loc)[:24].lower()


def _dedupe_by_title(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    seen_venue: set[str] = set()
    out: list[dict[str, Any]] = []
    for ev in events:
        title = clean_text(ev.get("title") or "")
        loc = clean_text(ev.get("location") or "")
        key = title.lower()
        if not key or key in seen:
            continue
        vp = _venue_fp(title, loc)
        # Collapse near-duplicates at same venue (prefer first / cleaner card)
        if vp and vp in seen_venue:
            continue
        seen.add(key)
        if vp:
            seen_venue.add(vp)
        out.append(ev)
    return out


def _parse_teaser_prose(soup, url: str) -> list[dict[str, Any]]:
    """Paywalled teasers often still expose 日期 range + venue in the free intro."""
    h1 = soup.select_one("h1") or soup.select_one(".entry-title")
    if not h1:
        return []
    title = strip_detail_suffix(clean_text(h1.get_text(" ", strip=True)))
    title = re.sub(r"^\d+\.\s*", "", title)
    if not title or len(title) < 4:
        return []
    # Trim SEO pipe / exclaim suffixes for card titles
    if "|" in title:
        title = title.split("|", 1)[0].strip()
    if "!" in title:
        title = title.split("!", 1)[0].strip()
    if len(title) > 36:
        title = title[:36].rstrip()

    root = soup.select_one("article") or soup.select_one(".entry-content") or soup
    blob = clean_text(root.get_text(" ", strip=True))[:1200]
    if "日期" not in blob and "至" not in blob and "即日" not in blob:
        return []

    # Date range cues in free copy
    date_text = ""
    m = re.search(
        r"(?:由\s*)?(?:即日起?|即日)\s*至\s*((?:20\d{2}\s*年\s*)?\d{1,2}\s*月\s*\d{1,2}\s*日)",
        blob,
    )
    if m:
        date_text = "即日至" + clean_text(m.group(1))
    if not date_text:
        m = re.search(
            r"(?:由\s*)?((?:20\d{2}\s*年\s*)?\d{1,2}\s*月\s*\d{1,2}\s*日)\s*至\s*"
            r"((?:20\d{2}\s*年\s*)?\d{1,2}\s*月\s*\d{1,2}\s*日)",
            blob,
        )
        if m:
            date_text = clean_text(m.group(1) + "至" + m.group(2))
    if not date_text:
        return []

    location = ""
    # Prefer explicit 地點, else known venue phrases from title/body
    m = re.search(r"地點\s*[:：]?\s*([^。；;]{2,40})", blob)
    if m:
        location = clean_text(m.group(1))
    if not location:
        for cue in (
            "灣仔利東街",
            "利東街",
            "藍屋建築群",
            "灣仔藍屋",
            "藍屋",
            "MegaBox",
            "海港城",
            "山頂道花園",
            "維多利亞公園",
            "維園",
            "黃大仙祠",
            "饒宗頤文化館",
        ):
            if cue in blob or cue in title:
                location = cue
                break
    if not location:
        return []

    joined = f"{title} 日期:{date_text} 地點:{location} {blob[:200]}"
    ev = _build_event(title, location, date_text, joined, url)
    return [ev] if ev else []


def _parse_article(url: str, session=None) -> list[dict[str, Any]]:
    resp = polite_get(url, session=session)
    soup = soup_html(resp.text)
    events: list[dict[str, Any]] = []
    events.extend(_parse_tables(soup, url))
    # Always also try fact-lists — seasonal listicles use ul under ._page_ divs
    events.extend(_parse_fact_lists(soup, url))
    if not events:
        events.extend(_parse_article_paragraphs(soup, url))
    if not events:
        events.extend(_parse_teaser_prose(soup, url))
    return _dedupe_by_title(events)


def fetch_events(session=None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    meta: dict[str, Any] = {"source": SOURCE, "url": None, "ok": False, "count": 0, "error": None}
    try:
        urls = _article_urls(session=session)
        meta["url"] = urls[0] if urls else None
        meta["urls"] = urls
        events: list[dict[str, Any]] = []
        errors: list[str] = []
        per_url: list[dict[str, Any]] = []
        for url in urls:
            try:
                batch = _parse_article(url, session=session)
                events.extend(batch)
                per_url.append({"url": url, "count": len(batch)})
            except Exception as e:
                errors.append(f"{url}: {type(e).__name__}: {e}")
                per_url.append({"url": url, "count": 0, "error": f"{type(e).__name__}: {e}"})
        events = _dedupe_by_title(events)
        meta["ok"] = True
        meta["count"] = len(events)
        meta["per_url"] = per_url
        if errors:
            meta["note"] = " | ".join(errors[:5])
        return events, meta
    except Exception as e:
        meta["error"] = f"{type(e).__name__}: {e}"
        return [], meta
