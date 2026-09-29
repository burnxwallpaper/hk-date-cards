"""Careful evergreen free venue seeds with real official source URLs.

長廳 / 美術館 / 戶外走走 style cards for well-known always-on public spaces.
Soft-fail individual URLs if unreachable; never invent prices.
Tai Kwun (taikwun.hk) intentionally omitted: robots.txt User-agent:* Disallow:/.
"""
from __future__ import annotations

from typing import Any

from .common import make_event, polite_get

SOURCE = "常設免費場地（手選核對）"

SEEDS = [
    {
        "title": "香港文化中心大堂免費文化節目／長廳漫遊",
        "location": "尖沙咀梳士巴利道10號香港文化中心大堂",
        "url": "https://www.lcsd.gov.hk/tc/hkcc/programmes/audbuilding/freeculturalprogrammes.html",
        "type": "長廳",
        "date_text": "節目時間表見康文署頁（大堂免費開放）",
        "extra": "長廳 大堂 免費 室內 坐低傾",
        "tags": ["長廳", "室內", "坐低傾"],
        "budget": "免費入場",
    },
    {
        "title": "M+ 免費樓層／公共空間漫遊",
        "location": "西九文化區博物館道38號 M+",
        "url": "https://www.mplus.org.hk/tc/plan-your-visit/",
        "type": "美術館",
        "date_text": "詳見 M+ 參觀資訊（部分樓層／公共空間免費）",
        "extra": "美術館 西九 室內 安靜",
        "tags": ["美術館", "室內", "安靜"],
        # Do NOT force free if visit page mentions tickets — parse from page later
        "budget": "",
        "verify_free_kw": ("免費", "free"),
    },
    {
        "title": "PMQ 元創方免費逛店／展覽空間",
        "location": "中環鴨巴甸街35號 PMQ",
        "url": "https://www.pmq.org.hk/?lang=zh",
        "type": "商場漫遊",
        "date_text": "開放時間見官網",
        "extra": "PMQ 商場漫遊 室內 行路多",
        "tags": ["商場漫遊", "室內", "行路多"],
        "budget": "免費入場",
    },
    {
        "title": "海濱長廊夜景散步（灣仔／尖沙咀一段）",
        "location": "維港海濱長廊",
        "url": "https://www.discoverhongkong.com/tc/attractions.html",
        "type": "夜景散步",
        "date_text": "全日開放（公開海濱）",
        "extra": "夜景 戶外 行路多 夜晚",
        "tags": ["夜景散步", "戶外", "夜晚", "行路多"],
        "budget": "免費開放",
    },
]


def fetch_events(session=None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    meta: dict[str, Any] = {"source": SOURCE, "url": None, "ok": False, "count": 0, "error": None}
    events: list[dict[str, Any]] = []
    notes: list[str] = []
    try:
        for seed in SEEDS:
            url = seed["url"]
            try:
                resp = polite_get(url, session=session, timeout=20)
                body = resp.text
                budget_text = seed.get("budget") or ""
                verify = seed.get("verify_free_kw")
                if verify:
                    if any(k.lower() in body.lower() for k in verify):
                        budget_text = budget_text or "免費"
                    else:
                        # Page reachable but no free signal — leave unknown (do not invent)
                        budget_text = ""
                        notes.append(f"{seed['title']}: reachable but no free keyword; budget 未知")
                ev = make_event(
                    title=seed["title"],
                    location=seed["location"],
                    source=SOURCE,
                    source_url=url,
                    date_text=seed.get("date_text", ""),
                    budget_text=budget_text or seed["title"],
                    extra_text=seed.get("extra", ""),
                    tags_extra=seed.get("tags"),
                    type_hint=seed.get("type"),
                    evergreen=True,
                )
                events.append(ev)
            except Exception as e:
                notes.append(f"{seed['title']}: skip ({type(e).__name__}: {e})")
                continue

        meta["ok"] = True
        meta["count"] = len(events)
        if notes:
            meta["note"] = " | ".join(notes)
        if not events:
            meta["skipped"] = True
            meta["error"] = "All evergreen venue URLs failed or soft-skipped"
        return events, meta
    except Exception as e:
        meta["error"] = f"{type(e).__name__}: {e}"
        return [], meta
