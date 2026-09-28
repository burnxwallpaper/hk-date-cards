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

# Locked taxonomy
TYPE = {
    "美術館",
    "展覽",
    "商場漫遊",
    "市集",
    "開放日",
    "夜景散步",
    "室內打卡",
    "長廳",
    "表演",
    "戶外走走",
}
# Prefer this display order when choosing ONE type
TYPE_PRIORITY = [
    "美術館",
    "展覽",
    "商場漫遊",
    "市集",
    "開放日",
    "夜景散步",
    "室內打卡",
    "長廳",
    "表演",
    "戶外走走",
]
OCCASION = {"室內", "戶外", "半日", "夜晚", "週末"}
MOOD = {"安靜", "熱鬧", "行路多", "坐低傾"}
BUDGET_TAGS = {"免費", "$100內", "$100–300", "$300–600", "$600+"}
OPTIONAL = {"要早訂", "親子向", "大型公演"}
ALL_ALLOWED = TYPE | OCCASION | MOOD | BUDGET_TAGS | OPTIONAL

# Types that default to 免費 unless source explicitly says paid
FORCE_FREE_TYPES = {"商場漫遊", "長廳", "開放日", "市集"}

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


def looks_paid(text: str) -> bool:
    """True if text clearly indicates paid admission / ticket price."""
    t = clean_text(text)
    if not t:
        return False
    if re.search(r"(?:HK\$|港幣|\$)\s*\d{1,5}", t):
        return True
    if re.search(r"\d{2,5}\s*元", t):
        return True
    if re.search(r"(門票|票價|收費|入場費)", t) and not re.search(r"免費", t):
        return True
    return False


def force_free_for_type(
    event_type: str | None,
    budget_display: str,
    budget_tag: str | None,
    budget_text: str = "",
) -> tuple[str, str | None]:
    """
    Force 免費 for 商場漫遊／長廳／開放日／市集 (and 逛街-like → 商場漫遊)
    unless source text already states a paid amount.
    """
    if event_type not in FORCE_FREE_TYPES:
        return budget_display, budget_tag
    if budget_tag and budget_tag != "免費" and budget_tag in BUDGET_TAGS:
        return budget_display, budget_tag
    if looks_paid(budget_text) and budget_display != "免費":
        return budget_display, budget_tag
    return "免費", "免費"


def infer_type(title: str, location: str = "", extra_text: str = "") -> str | None:
    """Pick exactly ONE type tag (prefer TYPE_PRIORITY #1 match order)."""
    blob = f"{title} {location} {extra_text}"
    candidates: list[str] = []

    if any(k in blob for k in ("美術館", "藝術館", "博物館", "文物館", "紀念館", "藝廊", "畫廊", "Museum of Art", "M+")):
        candidates.append("美術館")
    if any(k in blob for k in ("展覽", "展覧", "特展", "常設展", "exhibition", "Exhibition")):
        candidates.append("展覽")
    if any(k in blob for k in ("商場", "mall", "Mall", "快閃店", "pop-up", "Pop-up", "POP UP", "逛街", "中庭打卡")):
        candidates.append("商場漫遊")
    if any(k in blob for k in ("市集", "墟", "bazaar", "market", "嘉年華市集", "農墟")):
        candidates.append("市集")
    if any(k in blob for k in ("開放日", "Open Day", "open day", "開放參觀", "開放予公眾")):
        candidates.append("開放日")
    if any(k in blob for k in ("夜景", "夜遊", "燈光展", "燈飾", "亮燈", "煙花", "維港夜", "倒數", "跨年", "舞火龍", "綵燈", "花燈", "冬日巡禮", "繽紛冬日")):
        candidates.append("夜景散步")
    if any(k in blob for k in ("打卡", "影相位", "必影", "裝置藝術", "室內装置", "室內打卡")):
        candidates.append("室內打卡")
    if any(k in blob for k in ("長廳", "大堂", "Foyer", "foyer", "免費文化節目", "大堂音樂會")):
        candidates.append("長廳")
    if any(
        k in blob
        for k in (
            "演唱會",
            "音樂會",
            "演奏會",
            "公演",
            "表演",
            "劇場",
            "舞台",
            "舞蹈",
            "歌劇",
            "音樂劇",
            "standup",
            "Stand-up",
        )
    ):
        candidates.append("表演")
    if any(k in blob for k in ("行山", "海濱", "散步", "戶外走走", "公園散步", "綠道", "步道", "郊遊", "巡禮", "廟會", "燒烤", "嘉年華")):
        candidates.append("戶外走走")

    for t in TYPE_PRIORITY:
        if t in candidates:
            return t
    return None


def infer_tags(
    *,
    title: str,
    location: str,
    date_text: str = "",
    budget_tag: str | None = None,
    extra_text: str = "",
    type_hint: str | None = None,
) -> list[str]:
    """Heuristic tags from locked taxonomy. Budget tag only if known. ONE type."""
    blob = f"{title} {location} {date_text} {extra_text}"
    tags: list[str] = []

    event_type = type_hint if type_hint in TYPE else infer_type(title, location, extra_text)
    if event_type:
        tags.append(event_type)

    outdoor_kw = ("戶外", "露天", "廣場", "海濱", "公園", "大坑", "浣紗", "街", "市集", "嘉年華", "跑", "行山")
    indoor_kw = ("音樂廳", "大劇院", "劇場", "展覽廳", "圖書館", "館", "商場", "中庭", "大堂", "會展", "室內")
    if any(k in blob for k in outdoor_kw) and not any(k in location for k in ("音樂廳", "大劇院", "劇場", "展覽廳")):
        tags.append("戶外")
    elif any(k in blob for k in indoor_kw):
        tags.append("室內")

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
    quiet = ("展覽", "導賞", "講座", "閱讀", "博物館", "安靜", "静", "靜", "美術館")
    walk = ("市集", "街", "行路", "海濱", "導賞", "巡", "行山", "開放日", "漫遊")
    sit = ("音樂會", "演奏會", "演唱會", "劇場", "電影", "傾", "長廳")
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

    # Dedupe preserve order; keep only allowed; ensure at most one type
    seen = set()
    out = []
    type_placed = False
    for t in tags:
        if t not in ALL_ALLOWED or t in seen:
            continue
        if t in TYPE:
            if type_placed:
                continue
            type_placed = True
        seen.add(t)
        out.append(t)
    return out


def display_tags(tags: list[str], limit: int = 2) -> list[str]:
    """Card UI: max 2 tags. Priority: type → mood → occasion. Never budget."""
    preferred_order = [
        # type first (display #1)
        *TYPE_PRIORITY,
        # mood second
        "熱鬧",
        "安靜",
        "行路多",
        "坐低傾",
        # occasion
        "週末",
        "夜晚",
        "半日",
        "戶外",
        "室內",
        # optional last
        "大型公演",
        "要早訂",
        "親子向",
    ]
    # Explicitly exclude budget from display
    eligible = [t for t in tags if t in ALL_ALLOWED and t not in BUDGET_TAGS]
    ranked = sorted(
        eligible,
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
    type_hint: str | None = None,
) -> dict[str, Any]:
    title_full = strip_detail_suffix(title)
    title = short_title(title_full)
    location = clean_location(location) or "地點待查"
    budget_display, budget_tag = parse_budget_from_text(budget_text or f"{title} {extra_text}")
    # Title starting with 免費… is authoritative even if blurb is long
    if budget_display == "未知" and re.match(r"^免費", clean_text(title)):
        budget_display, budget_tag = "免費", "免費"

    # Resolve type early so force_free can apply
    event_type = type_hint if type_hint in TYPE else None
    if tags_extra:
        for t in tags_extra:
            if t in TYPE:
                event_type = t
                break
    if not event_type:
        event_type = infer_type(title_full, location, extra_text)

    budget_display, budget_tag = force_free_for_type(
        event_type, budget_display, budget_tag, budget_text or f"{title_full} {extra_text}"
    )

    tags = infer_tags(
        title=title_full,
        location=location,
        date_text=date_text,
        budget_tag=budget_tag,
        extra_text=extra_text,
        type_hint=event_type,
    )
    if tags_extra:
        for t in tags_extra:
            if t in ALL_ALLOWED and t not in tags:
                # Don't add a second type
                if t in TYPE and any(x in TYPE for x in tags):
                    continue
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
            # keep only one type
            type_seen = False
            cleaned = []
            for t in merged:
                if t not in ALL_ALLOWED:
                    continue
                if t in TYPE:
                    if type_seen:
                        continue
                    type_seen = True
                cleaned.append(t)
            old["tags"] = cleaned
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
