"""Shared helpers: fetch, normalize, tags, dedupe."""
from __future__ import annotations

import hashlib
import re
import time
import unicodedata
from datetime import datetime, timezone, timedelta
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

HKT = timezone(timedelta(hours=8))
USER_AGENT = "HKDateCardsPersonalBot/1.0 (+personal offline MVP; polite rate-limit; no commercial use)"
MIN_INTERVAL_SEC = 1.5

OCCASION = {"室內", "戶外", "半日", "夜晚", "週末"}
MOOD = {"安靜", "熱鬧", "行路多", "坐低傾"}
BUDGET_TAGS = {"免費", "$100內", "$100–300", "$300–600", "$600+"}
OPTIONAL = {"要早訂", "親子向", "大型公演"}
ALL_ALLOWED = OCCASION | MOOD | BUDGET_TAGS | OPTIONAL

_last_fetch_at = 0.0


def polite_get(url: str, session: requests.Session | None = None, timeout: int = 25) -> requests.Response:
    """GET with rate limit and identifiable UA. Raises on HTTP errors."""
    global _last_fetch_at
    sess = session or requests.Session()
    wait = MIN_INTERVAL_SEC - (time.monotonic() - _last_fetch_at)
    if wait > 0:
        time.sleep(wait)
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "zh-HK,zh-TW;q=0.9,en;q=0.5"}
    resp = sess.get(url, headers=headers, timeout=timeout)
    _last_fetch_at = time.monotonic()
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or resp.encoding
    return resp


def soup_html(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def clean_text(s: str | None) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("\xa0", " ").replace("\u200b", "")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def strip_detail_suffix(title: str) -> str:
    t = clean_text(title)
    t = re.sub(r"(詳情|活動詳情)\s*$", "", t).strip()
    return t


def short_title(title: str) -> str:
    """Card headline: drop series/brand prefix; full title kept separately."""
    t = clean_text(title)
    for sep in (" — ", " – ", "——", "－"):
        if sep in t:
            left, right = t.rsplit(sep, 1)
            right = right.strip()
            if len(right) >= 4 and ("@" in left or re.search(r"20\d{2}", left) or len(left) >= 10):
                return right
    m = re.search(r"「([^」]{4,})」", t)
    if m and len(m.group(1)) + 6 < len(t):
        return m.group(1)
    return t


def clean_location(loc: str) -> str:
    """Drop redundant bits e.g. 大坑 浣紗街 香港浣紗街 → 大坑 浣紗街."""
    s = clean_text(loc)
    # Remove 「香港X」 when X already appears elsewhere (ignore spaces)
    compact = re.sub(r"\s+", "", s)
    changed = True
    while changed:
        changed = False
        for m in list(re.finditer(r"香港([\u4e00-\u9fff]{2,})", s)):
            rest = m.group(1)
            without = s[: m.start()] + s[m.end() :]
            if rest in re.sub(r"\s+", "", without):
                s = re.sub(r"\s+", " ", without).strip()
                changed = True
                break
    return s


def normalize_title_key(title: str) -> str:
    t = clean_text(title).lower()
    t = re.sub(r"[「」『』\"'“”‘’\[\]（）()【】《》〈〉·•\.\,\!\?\-—–～~／/\|@＠]", "", t)
    t = re.sub(r"\s+", "", t)
    return t


def normalize_venue_key(venue: str) -> str:
    v = clean_text(venue).lower()
    v = re.sub(r"\s+", "", v)
    return v


def parse_budget_from_text(text: str) -> tuple[str, str | None]:
    """
    Return (budget_display, budget_tag_or_None).
    Never invent prices — only explicit free / $ amounts.
    """
    t = clean_text(text)
    if not t:
        return "未知", None
    # Strong free signals only — ignore "免費特飲/免費燈籠" promo asides in long blurbs.
    if re.search(
        r"免費入場|免費參加|免費參觀|免費開放|免費體檢|免費文化|"
        r"Free Admission|free admission|費用：?\s*免費|收費：?\s*免費|"
        r"^免費$|(?:^|[【\s])免費(?:活動|節目|音樂會|演奏會|市集|展覽)",
        t,
        re.I,
    ):
        return "免費", "免費"
    # Title-level: short strings that literally start with 免費…
    if len(t) <= 80 and re.match(r"^免費", t) and not re.search(r"\$\s*\d+|HK\$\s*\d+", t):
        return "免費", "免費"

    amounts = [int(x) for x in re.findall(r"(?:HK\$|港幣|\$)\s*(\d{1,5})", t)]
    amounts += [int(x) for x in re.findall(r"(\d{2,5})\s*元", t)]
    if not amounts:
        return "未知", None
    lo, hi = min(amounts), max(amounts)
    display = f"${lo}" if lo == hi else f"${lo}–{hi}"
    # Map by lowest listed price (entry floor)
    if lo <= 100:
        tag = "$100內"
    elif lo <= 300:
        tag = "$100–300"
    elif lo <= 600:
        tag = "$300–600"
    else:
        tag = "$600+"
    return display, tag


def infer_tags(
    *,
    title: str,
    location: str,
    date_text: str = "",
    budget_tag: str | None = None,
    extra_text: str = "",
) -> list[str]:
    """Heuristic tags from locked taxonomy. Budget tag only if known."""
    blob = f"{title} {location} {date_text} {extra_text}"
    tags: list[str] = []

    outdoor_kw = ("戶外", "露天", "廣場", "海濱", "公園", "大坑", "浣紗", "街", "市集", "嘉年華", "跑", "行山")
    indoor_kw = ("音樂廳", "大劇院", "劇場", "展覽廳", "圖書館", "館", "商場", "中庭", "大堂", "會展", "室內")
    if any(k in blob for k in outdoor_kw) and not any(k in location for k in ("音樂廳", "大劇院", "劇場", "展覽廳")):
        tags.append("戶外")
    elif any(k in blob for k in indoor_kw):
        tags.append("室內")

    night_kw = ("夜", "晚上", "夜晚", "PM", "pm", "19:", "20:", "21:", "22:", "7:", "8:", "9:", "10:00 PM", "黃昏")
    half_kw = ("半日", "下午", "3pm", "3 pm", "14:", "15:", "16:", "上午", "早上", "AM")
    if re.search(r"(夜|晚上|夜晚|黃昏|7:30|8:00|19:|20:|21:)", blob) or re.search(
        r"\b([7-9]|1[0-1]):\d{2}\s*PM\b", blob, re.I
    ):
        tags.append("夜晚")
    elif any(k in blob for k in ("半日",)) or re.search(r"(3pm|下午|上午|14:|15:)", blob, re.I):
        tags.append("半日")

    if re.search(r"(週末|周末|星期六|星期日|週六|週日|（六）|（日）|\(六\)|\(日\)|Sat|Sun|Weekend|weekend)", blob):
        tags.append("週末")
    elif re.search(r"逢星期六至日|每逢週末", blob):
        tags.append("週末")

    loud = ("市集", "嘉年華", "演唱會", "音樂會", "派對", "快閃", "舞火龍", "熱鬧", "Battle", "公演")
    quiet = ("展覽", "導賞", "講座", "閱讀", "博物館", "安靜", "静", "靜")
    walk = ("市集", "街", "行路", "海濱", "導賞", "巡", "行山", "開放日")
    sit = ("音樂會", "演奏會", "演唱會", "劇場", "電影", "傾")
    if any(k in blob for k in loud):
        tags.append("熱鬧")
    elif any(k in blob for k in quiet):
        tags.append("安靜")
    if any(k in blob for k in walk):
        tags.append("行路多")
    elif any(k in blob for k in sit):
        tags.append("坐低傾")

    if any(k in blob for k in ("親子", "兒童", "小孩", "家庭", "寵物體檢")):
        tags.append("親子向")
    if any(k in blob for k in ("演唱會", "大型公演", "巡迴演唱會", "世界巡迴", "主場館", "紅館", "體育館")):
        tags.append("大型公演")
    if any(k in blob for k in ("要早訂", "早鳥", "門票將", "即將售罄", "售罄", "公開發售")):
        tags.append("要早訂")
    if budget_tag and budget_tag in BUDGET_TAGS:
        tags.append(budget_tag)

    # Dedupe preserve order; keep only allowed
    seen = set()
    out = []
    for t in tags:
        if t in ALL_ALLOWED and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def display_tags(tags: list[str], limit: int = 2) -> list[str]:
    """Card UI: max 1–2 tags. Prefer mood for couple-facing cards, then occasion."""
    preferred_order = [
        "熱鬧", "安靜", "行路多", "坐低傾",
        "週末", "夜晚", "半日", "戶外", "室內",
        "大型公演", "要早訂", "親子向",
        # budget tags last — UI also shows 預算 field
        "免費", "$100內", "$100–300", "$300–600", "$600+",
    ]

    ranked = sorted(
        [t for t in tags if t in ALL_ALLOWED],
        key=lambda t: preferred_order.index(t) if t in preferred_order else 99,
    )
    return ranked[:limit]


def make_event(
    *,
    title: str,
    location: str,
    source: str,
    source_url: str,
    date_text: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    budget_text: str = "",
    extra_text: str = "",
    tags_extra: list[str] | None = None,
) -> dict[str, Any]:
    title_full = strip_detail_suffix(title)
    title = short_title(title_full)
    location = clean_location(location) or "地點待查"
    budget_display, budget_tag = parse_budget_from_text(budget_text or f"{title} {extra_text}")
    # Title starting with 免費… is authoritative even if blurb is long
    if budget_display == "未知" and re.match(r"^免費", clean_text(title)):
        budget_display, budget_tag = "免費", "免費"
    tags = infer_tags(
        title=title_full,
        location=location,
        date_text=date_text,
        budget_tag=budget_tag,
        extra_text=extra_text,
    )
    if tags_extra:
        for t in tags_extra:
            if t in ALL_ALLOWED and t not in tags:
                tags.append(t)
    eid = hashlib.sha1(
        f"{normalize_title_key(title_full)}|{start_date or date_text}|{normalize_venue_key(location)}".encode()
    ).hexdigest()[:12]
    return {
        "id": eid,
        "title": title,
        "title_full": title_full,
        "location": location,
        "budget": budget_display,  # 未知 / 免費 / $explicit
        "budget_tag": budget_tag,  # None if unknown — UI must not invent
        "tags": tags,
        "display_tags": display_tags(tags, 2),
        "date_text": clean_text(date_text),
        "start_date": start_date,
        "end_date": end_date,
        "source": source,
        "source_url": source_url,
    }


def dedupe_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dedupe by normalized title+date+venue."""
    seen: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for ev in events:
        key = f"{normalize_title_key(ev['title'])}|{(ev.get('start_date') or ev.get('date_text') or '')[:32]}|{normalize_venue_key(ev.get('location',''))}"
        if key in seen:
            # merge tags
            old = seen[key]
            merged = list(dict.fromkeys(old.get("tags", []) + ev.get("tags", [])))
            old["tags"] = [t for t in merged if t in ALL_ALLOWED]
            old["display_tags"] = display_tags(old["tags"], 2)
            if old.get("budget") == "未知" and ev.get("budget") != "未知":
                old["budget"] = ev["budget"]
                old["budget_tag"] = ev.get("budget_tag")
            continue
        seen[key] = ev
        order.append(key)
    return [seen[k] for k in order]


def now_hkt_iso() -> str:
    return datetime.now(HKT).strftime("%Y-%m-%dT%H:%M:%S%z")
