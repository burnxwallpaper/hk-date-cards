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
FORCE_FREE_TYPES = {"商場漫遊", "長廳", "開放日", "市集", "室內打卡"}

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


def _extract_price_amounts(text: str) -> list[int]:
    """Pull explicit HKD amounts from text. Never invent — digits must appear with currency cues."""
    t = clean_text(text)
    if not t:
        return []
    amounts: list[int] = []

    def _to_int(raw: str) -> int | None:
        s = raw.replace(",", "").replace("，", "")
        if not s.isdigit():
            return None
        return int(s)

    # HK$200 / HKD 200 / 港幣$50 / 港幣$1,100 / 港幣 50 / $80 / $1,380
    for x in re.findall(
        r"(?:HK\s*\$|HKD|港幣\s*\$|港幣|\$)\s*(\d{1,3}(?:[,，]\d{3})+|\d{1,5})(?!\d)",
        t,
        re.I,
    ):
        n = _to_int(x)
        if n is not None:
            amounts.append(n)
    # 門票金額：120 / 票價：80 / 入場費 30 (no currency symbol, but labeled)
    for x in re.findall(
        r"(?:門票金額|門票|票價|入場費|收費|票價為|票價是)\s*[:：]?\s*(\d{1,3}(?:[,，]\d{3})+|\d{1,5})\s*(?:元|港幣|HKD?)?",
        t,
        re.I,
    ):
        n = _to_int(x)
        if n is not None:
            amounts.append(n)
    # 120元 / 80 元
    for x in re.findall(r"(?<![\d\.])(\d{2,5})\s*元", t):
        amounts.append(int(x))
    # de-dupe preserve order
    seen: set[int] = set()
    out: list[int] = []
    for a in amounts:
        if a <= 0 or a > 50000:
            continue
        if a not in seen:
            seen.add(a)
            out.append(a)
    return out


def parse_budget_from_text(text: str) -> tuple[str, str | None]:
    """
    Return (budget_display, budget_tag_or_None).
    Never invent prices — only explicit free / $ amounts.
    If both a $ amount and a conditional「免費」aside appear, prefer the explicit price
    (LOCKED: never leave 未知 when $ / 港幣 / 門票金額 is visible).
    """
    t = clean_text(text)
    if not t:
        return "未知", None

    amounts = _extract_price_amounts(t)
    if amounts:
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

    # Strong free signals only — ignore "免費特飲/免費燈籠" promo asides in long blurbs.
    if re.search(
        r"免費入場|免費參加|免費參觀|免費開放|免費體檢|免費文化|免費導賞|"
        r"免費對外|費用全免|無需門票|免票|公開展出|常設展覽免費|"
        r"Free Admission|free admission|admission\s*free|"
        r"費用\s*[：:]\s*免費|收費\s*[：:]\s*免費|票價\s*[：:]?\s*免費|"
        r"^免費$|(?:^|[【\s])免費(?:活動|節目|音樂會|演奏會|市集|展覽|參觀)",
        t,
        re.I,
    ):
        return "免費", "免費"
    # Title-level: short strings that literally start with 免費…
    if len(t) <= 80 and re.match(r"^免費", t):
        return "免費", "免費"

    return "未知", None


def looks_paid(text: str) -> bool:
    """True if text clearly indicates paid admission / ticket price."""
    t = clean_text(text)
    if not t:
        return False
    if _extract_price_amounts(t):
        return True
    if re.search(r"(門票|票價|收費|入場費|門票金額)", t) and not re.search(r"免費", t):
        return True
    return False


def force_free_for_type(
    event_type: str | None,
    budget_display: str,
    budget_tag: str | None,
    budget_text: str = "",
) -> tuple[str, str | None]:
    """
    Force 免費 for 商場漫遊／長廳／開放日／市集／室內打卡
    unless source text already states a paid amount.
    Also force 免費 for 美術館／展覽 when text clearly says permanent/free admission
    (never invent free for ticketed concerts or special paid shows).
    """
    t = clean_text(budget_text)
    free_art = event_type in {"美術館", "展覽"} and bool(
        re.search(
            r"常設展覽免費|常設.*免費|免費參觀|免費入場|免費開放|公開展出|"
            r"Free Admission|free admission|admission\s*free",
            t,
            re.I,
        )
    )
    if event_type not in FORCE_FREE_TYPES and not free_art:
        return budget_display, budget_tag
    if budget_tag and budget_tag != "免費" and budget_tag in BUDGET_TAGS:
        return budget_display, budget_tag
    if looks_paid(budget_text) and budget_display != "免費":
        return budget_display, budget_tag
    return "免費", "免費"


# Mall / soft-venue names → 商場漫遊 / 室內打卡 (not occasion-only)
MALL_VENUES = (
    "海港城",
    "Harbour City",
    "時代廣場",
    "朗豪坊",
    "國際金融中心",
    "IFC Mall",
    "ifc",
    "apm",
    "MegaBox",
    "置富",
    "領展",
    "尖沙咀中心",
    "帝國中心",
    "The Twins",
    "雙子匯",
    "圓方",
    "Elements",
    "K11",
    "希慎",
    "利園",
    "SOGO",
    "崇光",
    "荷里活廣場",
    "新城市廣場",
    "屯門市廣場",
    "YOHO",
    "荃灣廣場",
    "太古城中心",
    "又一城",
    "Festival Walk",
    "PMQ",
    "元創方",
)

# Food / buffet / ticketed sports — NOT couple outdoor-walk types
_FOOD_NOT_OUTDOOR = (
    "放題",
    "自助餐",
    "海鮮燒烤",
    "燒烤放題",
    "BBQ",
    "buffet",
    "Buffet",
    "美酒佳餚",
    "餐酒",
    "品酒",
)
_RACE_SPORT_NOT_WALK = (
    "帆船",
    "錦標賽",
    "世界錦標",
    "馬拉松",
    "賽馬",
    "龍舟賽",
    "公開賽",  # golf etc. — spectator sport, not 戶外走走 date walk
)
_PERF_KW = (
    "演唱會",
    "音樂會",
    "演奏會",
    "公演",
    "音樂劇",
    "歌劇",
    "舞台劇",
    "匯演",
    "standup",
    "Stand-up",
    "Standup",
)


def _is_food_not_walk(blob: str) -> bool:
    return any(k in blob for k in _FOOD_NOT_OUTDOOR)


def _is_race_sport(blob: str) -> bool:
    return any(k in blob for k in _RACE_SPORT_NOT_WALK)


def _is_performance(blob: str, *, title: str = "") -> bool:
    """Strong concert/show signals. Weak words (表演/舞台) only count in the title
    so festival blurbs mentioning '街頭表演' do not become 表演 over 市集/展覽."""
    check = title or blob
    if any(k in check for k in _PERF_KW):
        return True
    # Title-level weak signals only
    if title and any(k in title for k in ("表演", "劇場", "舞台劇", "舞蹈匯演", "舞劇")):
        return True
    return False


def _has_museum_signal(blob: str) -> bool:
    """True museum/gallery venue — ignore street names like 博物館道."""
    # Strip street-name false positives before matching
    scrubbed = re.sub(r"博物館道\d*", " ", blob)
    scrubbed = re.sub(r"美術館道\d*", " ", scrubbed)
    return any(
        k in scrubbed
        for k in (
            "美術館",
            "藝術館",
            "博物館",
            "文物館",
            "紀念館",
            "藝廊",
            "畫廊",
            "Museum of Art",
            "M+",
            "故宮",
        )
    )


def _has_mall_signal(blob: str) -> bool:
    if any(k in blob for k in ("商場", "mall", "Mall", "快閃店", "pop-up", "Pop-up", "POP UP", "逛街", "中庭打卡")):
        return True
    if any(k in blob for k in MALL_VENUES):
        return True
    return False


def infer_type(title: str, location: str = "", extra_text: str = "") -> str | None:
    """Pick exactly ONE type tag (prefer TYPE_PRIORITY #1 match order).

    Overrides:
    - Concerts / 音樂會 → 表演 (never 美術館 via 博物館道 etc.)
    - Food buffet / sailing race / ticketed sports → no 戶外走走 (None or better type)
    - Mall collabs / soft venues → 商場漫遊 or 室內打卡
    """
    blob = f"{title} {location} {extra_text}"
    candidates: list[str] = []

    # 1) Performance beats museum/street-name false positives
    # Wine & dine with "現場表演" is still a food festival — don't force 表演
    # Use title for performance check so desc "街頭表演" does not override 市集
    if _is_performance(blob, title=title) and not _is_food_not_walk(blob):
        candidates.append("表演")

    # Food buffet / race: never 戶外走走; leave no wrong type unless another type fits
    food_block = _is_food_not_walk(blob)
    race_block = _is_race_sport(blob) and not any(
        k in blob for k in ("展覽", "市集", "開放日", "音樂會", "演唱會")
    )

    if _has_museum_signal(blob) and "表演" not in candidates:
        candidates.append("美術館")
    if any(k in blob for k in ("展覽", "展覧", "特展", "常設展", "exhibition", "Exhibition", "紀念展")):
        candidates.append("展覽")
    if _has_mall_signal(blob):
        candidates.append("商場漫遊")
    if any(k in blob for k in ("市集", "墟", "bazaar", "market", "嘉年華市集", "農墟", "廟會")):
        candidates.append("市集")
    if any(k in blob for k in ("開放日", "Open Day", "open day", "開放參觀", "開放予公眾")):
        candidates.append("開放日")
    if any(
        k in blob
        for k in (
            "夜景",
            "夜遊",
            "燈光展",
            "燈飾",
            "亮燈",
            "煙花",
            "維港夜",
            "倒數",
            "跨年",
            "舞火龍",
            "綵燈",
            "花燈",
            "冬日巡禮",
            "繽紛冬日",
        )
    ):
        candidates.append("夜景散步")
    # Soft mall collabs / photo spots without explicit 商場 keyword
    if any(k in blob for k in ("打卡", "影相位", "必影", "裝置藝術", "室內装置", "室內打卡", "藝術裝置")):
        candidates.append("室內打卡")
    elif _has_mall_signal(blob) and any(k in title for k in ("×", "x ", " x", "Ｘ", "快閃", "聯乘", "期間限定")):
        candidates.append("室內打卡")
    if any(k in blob for k in ("長廳", "大堂", "Foyer", "foyer", "免費文化節目", "大堂音樂會")):
        candidates.append("長廳")

    # Outdoor walk — exclude food buffets & spectator sports/races
    if not food_block and not race_block and "表演" not in candidates:
        if any(
            k in blob
            for k in (
                "行山",
                "海濱長廊",
                "散步",
                "戶外走走",
                "公園散步",
                "綠道",
                "步道",
                "郊遊",
            )
        ):
            candidates.append("戶外走走")
        # Bare 海濱 / 嘉年華 only if not already typed as mall/market/show
        elif "海濱" in blob and not any(
            c in candidates for c in ("市集", "商場漫遊", "夜景散步", "展覽", "表演")
        ):
            candidates.append("戶外走走")

    # Soft mall venues: prefer 商場漫遊 over museum-category text in extra_text
    if _has_mall_signal(f"{title} {location}") and "商場漫遊" in candidates:
        if "美術館" in candidates and not _has_museum_signal(f"{title} {location}"):
            candidates = [c for c in candidates if c != "美術館"]

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
    evergreen: bool = False,
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
        "evergreen": bool(evergreen),
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


# --- Post-dedupe card disambiguation -----------------------------------------

_VAGUE_LOCATION_RE = re.compile(r"不同地點|詳情請瀏覽|多個地點")


def is_vague_location(loc: str | None) -> bool:
    """True when location is a placeholder rather than a concrete venue."""
    s = clean_text(loc or "")
    if not s or s == "地點待查":
        return True
    return bool(_VAGUE_LOCATION_RE.search(s))


def short_date_label(ev: dict[str, Any]) -> str:
    """Compact day.month label for card titles, e.g. 5.9 from 2026-09-05."""
    sd = (ev.get("start_date") or "").strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", sd):
        _y, m, d = sd.split("-")
        return f"{int(d)}.{int(m)}"
    dt = clean_text(ev.get("date_text") or "")
    # 5.9.2026 or 5.9.26
    m = re.match(r"(\d{1,2})\.(\d{1,2})(?:\.\d{2,4})?", dt)
    if m:
        return f"{int(m.group(1))}.{int(m.group(2))}"
    # 2026年9月5日 / 2026年9月5至6日
    m = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?", dt)
    if m:
        return f"{int(m.group(3))}.{int(m.group(2))}"
    # 9月5日
    m = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日", dt)
    if m:
        return f"{int(m.group(2))}.{int(m.group(1))}"
    if sd:
        return sd
    return dt[:12] if dt else ""



def _parse_iso_date(s: str | None):
    """Parse YYYY-MM-DD → datetime.date, else None."""
    from datetime import date as _date

    s = (s or "").strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s)
    if not m:
        return None
    try:
        return _date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _parse_dates_from_text(date_text: str) -> list:
    """Best-effort extract concrete calendar dates from date_text (HKT local)."""
    from datetime import date as _date

    t = clean_text(date_text or "")
    if not t:
        return []
    out: list = []

    def add(y: int, m: int, d: int) -> None:
        try:
            out.append(_date(y, m, d))
        except ValueError:
            pass

    # ISO ranges / singles: 2026-09-23 至 2026-11-29
    for m in re.finditer(r"(\d{4})-(\d{2})-(\d{2})", t):
        add(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    # d.m.yyyy or d.m.yy — 5.9.2026
    for m in re.finditer(r"\b(\d{1,2})\.(\d{1,2})\.(\d{2,4})\b", t):
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
        add(y, mo, d)

    # 2026年9月10日至10月22日 / 2026年4月17至9月2日 / 2026年9月5至27日 / 2026年9月5日
    for m in re.finditer(
        r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?"
        r"(?:\s*[至到\-–—~～]\s*"
        r"(?:(\d{4})\s*年\s*)?(\d{1,2})\s*月\s*(\d{1,2})\s*日?"
        r"|"
        r"\s*[至到\-–—~～]\s*(\d{1,2})\s*日)?",
        t,
    ):
        y1, m1, d1 = int(m.group(1)), int(m.group(2)), int(m.group(3))
        add(y1, m1, d1)
        if m.group(6):  # full or month-day end: ...至[yyyy年]M月D日
            y2 = int(m.group(4)) if m.group(4) else y1
            add(y2, int(m.group(5)), int(m.group(6)))
        elif m.group(7):  # same-month end: 9月5至27日
            add(y1, m1, int(m.group(7)))

    # Bare multi-day: 9月19-20、25-26日 / 9月19至20、25至26日
    years = [d.year for d in out]
    default_year = years[0] if years else datetime.now(HKT).year
    for m in re.finditer(
        r"(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*[\-–—~～至到]\s*(\d{1,2})"
        r"(?:\s*、\s*(\d{1,2})\s*[\-–—~～至到]\s*(\d{1,2}))?\s*日",
        t,
    ):
        mo = int(m.group(1))
        add(default_year, mo, int(m.group(2)))
        add(default_year, mo, int(m.group(3)))
        if m.group(4) and m.group(5):
            add(default_year, mo, int(m.group(4)))
            add(default_year, mo, int(m.group(5)))

    # Bare 9月6日 / 9月13日 (inherit year from any ISO/year already found, else current HKT year)
    years = [d.year for d in out]
    default_year = years[0] if years else datetime.now(HKT).year
    for m in re.finditer(r"(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*日", t):
        add(default_year, int(m.group(1)), int(m.group(2)))

    # de-dupe preserve
    seen = set()
    uniq = []
    for d in out:
        if d not in seen:
            seen.add(d)
            uniq.append(d)
    return uniq


def _is_evergreen_or_open_recurring(ev: dict[str, Any]) -> bool:
    """Permanent venues / open-ended 每逢 series with no concrete end → never expire."""
    dt = clean_text(ev.get("date_text") or "")
    title = clean_text(ev.get("title") or "") + " " + clean_text(ev.get("title_full") or "")
    blob = f"{dt} {title}"
    if re.search(r"常設|長期開放|全年開放|永久", blob):
        return True
    tags = set(ev.get("tags") or [])
    # Evergreen card types with no concrete end date in text
    evergreen_types = {"長廳", "商場漫遊", "室內打卡", "美術館"}
    has_concrete = bool(_parse_dates_from_text(dt)) or bool(ev.get("end_date") or ev.get("start_date"))
    if (tags & evergreen_types) and not has_concrete and not dt:
        return True
    # Open recurring with no year-bounded range end (e.g. 每逢週末 alone)
    if re.search(r"每逢|逢星期|逢週|逢周六|逢週末|逢星期六|逢星期日", dt):
        dates = _parse_dates_from_text(dt)
        if not dates:
            return True
    # Open-ended start with no end bound: "2026年6月13日起" / "即日起每晚"
    # (still honour an explicit 至/到 range end elsewhere in the string)
    if re.search(r"(?:即日)?起(?:\s|$|，|,|。|每晚|每日|每逢|逢)", dt) and not re.search(
        r"[至到\-–—~～]", dt
    ):
        return True
    return False


def event_last_date(ev: dict[str, Any]):
    """Latest known date for expiry checks, or None if unknown / evergreen.

    Prefer end_date; else max date parsed from date_text; else start_date
    for a specific session. Unparseable / evergreen / open recurring → None.
    """
    if _is_evergreen_or_open_recurring(ev):
        # Still honour an explicit past end_date if present
        ed = _parse_iso_date(ev.get("end_date"))
        if ed is not None:
            return ed
        dt = clean_text(ev.get("date_text") or "")
        # Open-ended "X日起" — start date alone is NOT an expiry bound
        if re.search(r"(?:即日)?起(?:\s|$|，|,|。|每晚|每日|每逢|逢)", dt) and not re.search(
            r"[至到\-–—~～]", dt
        ):
            return None
        # If date_text has a bounded range, use its last date even for 逢…
        parsed = _parse_dates_from_text(dt)
        if parsed:
            return max(parsed)
        return None

    ed = _parse_iso_date(ev.get("end_date"))
    if ed is not None:
        return ed

    parsed = _parse_dates_from_text(ev.get("date_text") or "")
    if parsed:
        return max(parsed)

    sd = _parse_iso_date(ev.get("start_date"))
    if sd is not None:
        return sd

    return None


def drop_expired_events(
    events: list[dict[str, Any]],
    *,
    today=None,
) -> tuple[list[dict[str, Any]], int]:
    """Drop events whose last known date is already past today (Asia/Hong_Kong).

    Keep evergreen / permanent (常設, 長廳, …) and open recurring (每逢…) with
    no concrete end. Unparseable dates → keep (do not invent expiry).
    Returns (kept_events, dropped_count).
    """
    from datetime import date as _date

    if today is None:
        today = datetime.now(HKT).date()
    elif isinstance(today, str):
        today = _parse_iso_date(today) or datetime.now(HKT).date()

    kept: list[dict[str, Any]] = []
    dropped = 0
    for ev in events:
        last = event_last_date(ev)
        if last is not None and last < today:
            dropped += 1
            continue
        kept.append(ev)
    return kept, dropped


def extract_admission_text(html: str) -> str:
    """
    Pull admission / ticket-price section text from a detail page.
    Prefer structured DiscoverHK ticketPrice nodes; else a short window around
    票價／門票／收費／Admission. Empty string if nothing useful.
    """
    if not html:
        return ""
    soup = soup_html(html)
    parts: list[str] = []
    for el in soup.select('[data-event-property="ticketPrice"]'):
        p = clean_text(el.get_text(" ", strip=True))
        if p:
            parts.append(p)
    if parts:
        return "票價 " + " ".join(parts)

    text = clean_text(soup.get_text(" ", strip=True))
    if not text:
        return ""
    # Window: label → next field (購票/查詢/網址/主辦…)
    m = re.search(
        r"(?:票價|門票金額|門票|入場費|收費|Admission(?:\s*Fee)?|Ticket\s*Price)"
        r"\s*[:：]?\s*(.+?)"
        r"(?=\s*(?:購票|查詢|網址|主辦機構|聯絡|Close|展開|收起|$))",
        text,
        re.I,
    )
    if m:
        return clean_text(m.group(0))[:500]
    # Free-only admission cue without a 票價 label
    m = re.search(
        r".{0,10}(?:免費入場|免費參觀|免費開放|Free Admission|admission\s*free).{0,40}",
        text,
        re.I,
    )
    if m:
        return clean_text(m.group(0))[:200]
    return ""



def _prop_texts(soup, prop: str) -> list[str]:
    out: list[str] = []
    for el in soup.select(f'[data-event-property="{prop}"]'):
        p = clean_text(el.get_text(" ", strip=True))
        if p:
            out.append(p)
    return out


_TIME_OF_DAY_RE = re.compile(
    r"(\d{1,2}\s*[:：]\s*\d{2}|\d{1,2}\s*[時点]\s*\d{0,2}\s*分?"
    r"|\d{1,2}\s*(?:am|pm|AM|PM)|上午|下午|晚上|午|閉館|開放時間)",
    re.I,
)


def date_text_is_weak(date_text: str | None) -> bool:
    """True when card has no usable schedule, or only ISO dates without clock time."""
    s = clean_text(date_text or "")
    if not s:
        return True
    # Already has clock / session wording → keep
    if _TIME_OF_DAY_RE.search(s):
        return False
    # Chinese calendar range / open-ended start already explicit → keep
    # (do NOT re-scrape roundup articles; first 日期: on page is often another event)
    if re.search(r"即日|(?:\d{4}\s*年\s*)?\d{1,2}\s*月\s*\d{1,2}\s*日", s):
        return False
    # Pure ISO / ISO range only → weak (enrichable)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:\s*至\s*\d{4}-\d{2}-\d{2})?", s):
        return True
    # Very short date-only without time
    if len(s) <= 16 and not _TIME_OF_DAY_RE.search(s):
        return True
    return False


def extract_schedule_text(html: str) -> str:
    """
    Pull explicit date/time text from a detail page. Never invent.
    Prefer DiscoverHK eventDetailDate + eventTime; else labeled 日期/時間 windows.
    """
    if not html:
        return ""
    soup = soup_html(html)
    date_parts = _prop_texts(soup, "eventDetailDate")
    time_parts = _prop_texts(soup, "eventTime")
    chunks: list[str] = []
    if date_parts:
        chunks.append(date_parts[0])
    if time_parts:
        # Keep first sentence-ish of opening hours; cap length for cards
        tp = time_parts[0]
        # Prefer opening-hours clause before long performance calendars
        m = re.split(r"(?:開幕周|期間限定|查詢|購票)", tp, maxsplit=1)
        tp = clean_text(m[0] if m else tp)
        if len(tp) > 100:
            tp = tp[:97].rstrip("，,;；、 ") + "…"
        if tp:
            chunks.append(tp)
    if chunks:
        return clean_text(" ".join(chunks))[:220]

    text = clean_text(soup.get_text(" ", strip=True))
    if not text:
        return ""
    date_m = re.search(
        r"日期\s*[:：]?\s*(.+?)(?=\s*(?:時間|地點|票價|購票|查詢|網址|主辦機構|$))",
        text,
    )
    time_m = re.search(
        r"時間\s*[:：]?\s*(.+?)(?=\s*(?:地點|票價|購票|查詢|網址|主辦機構|開幕周|$))",
        text,
    )
    parts: list[str] = []
    if date_m:
        parts.append(clean_text(date_m.group(1))[:80])
    if time_m:
        tm = clean_text(time_m.group(1))
        if _TIME_OF_DAY_RE.search(tm):
            if len(tm) > 100:
                tm = tm[:97].rstrip("，,;；、 ") + "…"
            parts.append(tm)
    if parts and any(_TIME_OF_DAY_RE.search(p) or re.search(r"\d{4}\s*年|\d{1,2}\s*月", p) for p in parts):
        return clean_text(" ".join(parts))[:220]
    return ""


def short_schedule_label(ev: dict[str, Any]) -> str:
    """
    Shortened time line for cards, e.g. 「9/28 六 3–4:30pm」.
    Empty string when nothing explicit — UI must omit the row (never 待定/未知).
    """
    raw = clean_text(ev.get("date_text") or "")
    if not raw:
        sd = (ev.get("start_date") or "").strip()
        ed = (ev.get("end_date") or "").strip()
        if sd and ed and sd != ed:
            # ISO-only fallback — still show compact date range (no clock)
            def _md(iso: str) -> str:
                m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", iso)
                if not m:
                    return iso
                return f"{int(m.group(2))}/{int(m.group(3))}"
            return f"{_md(sd)}–{_md(ed)}"
        if sd:
            m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", sd)
            if m:
                return f"{int(m.group(2))}/{int(m.group(3))}"
            return sd
        return ""

    s = raw
    # 17.10.2026 (六) 3pm – 4:30pm → 10/17 六 3–4:30pm
    m = re.match(
        r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})\s*(?:\(([^)]+)\))?\s*(.*)$",
        s,
    )
    if m:
        d, mo = int(m.group(1)), int(m.group(2))
        wd = (m.group(4) or "").strip()
        rest = clean_text(m.group(5) or "")
        rest = rest.replace("–", "–").replace("—", "–")
        rest = re.sub(r"\s*–\s*", "–", rest)
        rest = re.sub(r"\s+", " ", rest)
        bits = [f"{mo}/{d}"]
        if wd:
            bits.append(wd)
        if rest:
            bits.append(rest)
        return " ".join(bits)[:60]

    # 2026年9月25日至2027年1月3日 …
    m = re.match(
        r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"
        r"(?:\s*[至到\-–—~～]\s*(?:(\d{4})\s*年\s*)?(\d{1,2})\s*月\s*(\d{1,2})\s*日)?\s*(.*)$",
        s,
    )
    if m:
        y1, mo1, d1 = int(m.group(1)), int(m.group(2)), int(m.group(3))
        rest = clean_text(m.group(7) or "")
        if m.group(6):
            y2 = int(m.group(4)) if m.group(4) else y1
            mo2, d2 = int(m.group(5)), int(m.group(6))
            head = f"{mo1}/{d1}–{mo2}/{d2}"
            if y2 != y1:
                head = f"{y1}/{mo1}/{d1}–{y2}/{mo2}/{d2}"
        else:
            head = f"{mo1}/{d1}"
        # Compress common opening-hours phrasing
        rest = re.sub(r"星期二至日", "二至日", rest)
        rest = re.sub(r"上午\s*", "", rest)
        rest = re.sub(r"晚上\s*", "", rest)
        rest = re.sub(r"至", "–", rest, count=2)
        if len(rest) > 36:
            rest = rest[:33].rstrip("，,;；、 ") + "…"
        return clean_text(f"{head} {rest}")[:60]

    # ISO range already in date_text
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})\s*至\s*(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{int(m.group(2))}/{int(m.group(3))}–{int(m.group(5))}/{int(m.group(6))}"
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{int(m.group(2))}/{int(m.group(3))}"

    # Fallback: trim raw source text
    if len(s) > 56:
        s = s[:53].rstrip("，,;；、 ") + "…"
    return s


def enrich_budgets_from_source_pages(
    events: list[dict[str, Any]],
    session=None,
    *,
    max_fetches: int = 40,
) -> dict[str, Any]:
    """
    Polite enrichment pass (capped detail fetches):
    - Budget: if still 未知, extract admission text → parse_budget_from_text.
    - Schedule: if date_text weak/empty, fill from explicit detail date/time only.
    Soft-fails on 403/timeout. Never invents prices or times.
    """
    stats: dict[str, Any] = {
        "candidates": 0,
        "fetched": 0,
        "unknown_to_priced": 0,
        "unknown_to_free": 0,
        "still_unknown": 0,
        "schedule_filled": 0,
        "errors": 0,
        "skipped_cap": 0,
        "samples_priced": [],
        "samples_free": [],
        "samples_schedule": [],
    }
    if not events:
        return stats

    def _is_unknown(ev: dict[str, Any]) -> bool:
        if ev.get("budget_tag") is None:
            return True
        b = ev.get("budget")
        return b in (None, "", "未知", "預算未知")

    def _needs_schedule(ev: dict[str, Any]) -> bool:
        if ev.get("evergreen"):
            return False
        return date_text_is_weak(ev.get("date_text"))

    candidates = [
        ev
        for ev in events
        if (ev.get("source_url") or "").startswith("http")
        and "timable.com" not in (ev.get("source_url") or "")
        and (_is_unknown(ev) or _needs_schedule(ev))
    ]
    stats["candidates"] = len(candidates)

    for ev in candidates:
        need_budget = _is_unknown(ev)
        need_sched = _needs_schedule(ev)
        if stats["fetched"] >= max_fetches:
            stats["skipped_cap"] += 1
            if need_budget:
                stats["still_unknown"] += 1
            continue
        url = ev.get("source_url") or ""
        try:
            resp = polite_get(url, session=session, timeout=20)
            stats["fetched"] += 1
            html = resp.text

            if need_sched:
                sched = extract_schedule_text(html)
                if sched and not date_text_is_weak(sched):
                    ev["date_text"] = sched
                    stats["schedule_filled"] += 1
                    if len(stats["samples_schedule"]) < 6:
                        stats["samples_schedule"].append(
                            f"{(ev.get('title') or '')[:28]} → {sched[:40]}"
                        )

            if need_budget:
                admission = extract_admission_text(html)
                if not admission:
                    stats["still_unknown"] += 1
                    continue
                display, tag = parse_budget_from_text(admission)
                event_type = None
                for tt in ev.get("tags") or []:
                    if tt in TYPE:
                        event_type = tt
                        break
                display, tag = force_free_for_type(event_type, display, tag, admission)
                if display in ("未知", "預算未知") or tag is None:
                    stats["still_unknown"] += 1
                    continue
                ev["budget"] = display
                ev["budget_tag"] = tag
                tags = [tt for tt in (ev.get("tags") or []) if tt not in BUDGET_TAGS]
                if tag in BUDGET_TAGS:
                    tags.append(tag)
                ev["tags"] = tags
                ev["display_tags"] = display_tags(tags, 2)
                title = (ev.get("title") or "")[:40]
                if tag == "免費":
                    stats["unknown_to_free"] += 1
                    if len(stats["samples_free"]) < 6:
                        stats["samples_free"].append(title)
                else:
                    stats["unknown_to_priced"] += 1
                    if len(stats["samples_priced"]) < 6:
                        stats["samples_priced"].append(f"{title} → {display}/{tag}")
            # if only schedule was needed and budget already known, fine
        except Exception:
            stats["errors"] += 1
            if need_budget:
                stats["still_unknown"] += 1
    return stats


def postprocess_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """After dedupe_events:

    1. Same normalized title, vague location vs specific → drop vague.
    2. Same normalized title + same venue, different dates → append · D.M
       to card ``title`` (``title_full`` unchanged) so UI cards differ.
    """
    if not events:
        return events

    # Group by normalized short title
    by_title: dict[str, list[dict[str, Any]]] = {}
    for ev in events:
        key = normalize_title_key(ev.get("title") or "")
        by_title.setdefault(key, []).append(ev)

    drop_ids: set[str] = set()
    for _key, group in by_title.items():
        if len(group) < 2:
            continue
        specific = [e for e in group if not is_vague_location(e.get("location"))]
        vague = [e for e in group if is_vague_location(e.get("location"))]
        if specific and vague:
            for e in vague:
                eid = e.get("id")
                if eid:
                    drop_ids.add(eid)

    kept = [e for e in events if e.get("id") not in drop_ids]

    # Re-group remaining by title+venue for date disambiguation
    by_tv: dict[str, list[dict[str, Any]]] = {}
    for ev in kept:
        key = (
            f"{normalize_title_key(ev.get('title') or '')}|"
            f"{normalize_venue_key(ev.get('location') or '')}"
        )
        by_tv.setdefault(key, []).append(ev)

    for _key, group in by_tv.items():
        if len(group) < 2:
            continue
        date_keys = {
            (e.get("start_date") or e.get("date_text") or "").strip() for e in group
        }
        if len(date_keys) <= 1:
            continue
        for e in group:
            # Skip if title already carries a · date suffix
            if " · " in (e.get("title") or ""):
                continue
            label = short_date_label(e)
            if not label:
                continue
            e["title"] = f"{e['title']} · {label}"

    return kept
