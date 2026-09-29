"""LCSD free permanent museum visits — curated from official public pages.

Policy (museum pass page): permanent exhibitions of all LCSD museums are free
except HK Science Museum and HK Space Museum. We emit evergreen date-cards with
real source URLs; do not invent special-exhibition prices.
"""
from __future__ import annotations

from typing import Any

from .common import make_event, polite_get

SOURCE = "康文署博物館（常設免費）"
PASS_URL = "https://www.museums.gov.hk/tc/web/portal/museum-pass.html"
LIST_URL = "https://www.lcsd.gov.hk/tc/facilities/facilitieslist/museums/lcsdmuseums.html"

# Official free permanent venues (Science / Space excluded — they charge).
# Locations are well-known public addresses; source_url points at official site.
FREE_MUSEUMS = [
    {
        "title": "香港藝術館常設展覽",
        "location": "尖沙咀梳士巴利道10號香港藝術館",
        "url": "https://hk.art.museum/tc/web/ma/home.html",
        "type": "美術館",
    },
    {
        "title": "茶具文物館常設展覽",
        "location": "中環紅棉路10號茶具文物館",
        "url": "https://hk.art.museum/tc/web/ma/home.html",
        "type": "美術館",
    },
    {
        "title": "香港歷史博物館常設展覽「香港故事」",
        "location": "尖沙咀漆咸道南100號香港歷史博物館",
        "url": "https://hk.history.museum/",
        "type": "美術館",
    },
    {
        "title": "香港文化博物館常設展覽",
        "location": "沙田文林路1號香港文化博物館",
        "url": "https://hk.heritage.museum/",
        "type": "美術館",
    },
    {
        "title": "孫中山紀念館常設展覽",
        "location": "中環堅尼地道7號孫中山紀念館",
        "url": "https://hk.drsunyatsen.museum/tc/web/sysm/home.html",
        "type": "美術館",
    },
    {
        "title": "香港抗戰及海防博物館常設展覽",
        "location": "筲箕灣東喜道175號",
        "url": "https://hk.waranddefence.museum/tc/web/mcd/home.html",
        "type": "美術館",
    },
    {
        "title": "香港電影資料館常設展覽",
        "location": "西灣河鯉景道50號香港電影資料館",
        "url": "https://www.lcsd.gov.hk/CE/CulturalService/HKFA/index.html",
        "type": "展覽",
    },
    {
        "title": "香港鐵路博物館常設展覽",
        "location": "大埔墟崇德街13號",
        "url": "https://hk.heritage.museum/",
        "type": "美術館",
    },
    {
        "title": "油街實現免費藝術空間",
        "location": "北角油街12號",
        "url": "https://www.apo.hk/tc/web/apo/oi.html",
        "type": "美術館",
    },
    {
        "title": "葛量洪號滅火輪展覽館",
        "location": "紅磡海濱長廊",
        "url": "https://www.lcsd.gov.hk/tc/facilities/facilitieslist/museums/lcsdmuseums.html",
        "type": "展覽",
    },
]


def fetch_events(session=None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    meta: dict[str, Any] = {
        "source": SOURCE,
        "url": PASS_URL,
        "ok": False,
        "count": 0,
        "error": None,
    }
    try:
        # Verify policy page still states free permanent exhibitions
        resp = polite_get(PASS_URL, session=session)
        text = resp.text
        free_ok = (
            "常設展覽免費開放" in text
            or "permanent exhibitions of all LCSD museums are open to all free of charge" in text
            or ("免費開放" in text and "常設" in text)
        )
        # Also touch list page (polite) to confirm museums listing exists
        try:
            polite_get(LIST_URL, session=session)
        except Exception:
            pass

        if not free_ok:
            meta["skipped"] = True
            meta["error"] = (
                "Soft-skip: museum-pass page no longer clearly states free permanent exhibitions; "
                "refusing to emit free-museum seeds without policy confirmation."
            )
            return [], meta

        events = []
        for m in FREE_MUSEUMS:
            ev = make_event(
                title=m["title"],
                location=m["location"],
                source=SOURCE,
                source_url=m["url"],
                date_text="常設展覽（除科學館／太空館外免費）",
                start_date=None,
                end_date=None,
                budget_text="免費參觀 免費入場 常設展覽免費開放",
                extra_text="博物館 常設展覽 室內 半日 安靜",
                tags_extra=[m["type"], "室內", "半日", "安靜"],
                type_hint=m["type"],
                evergreen=True,
            )
            events.append(ev)

        meta["ok"] = True
        meta["count"] = len(events)
        meta["note"] = "Evergreen free permanent LCSD museum cards; policy confirmed on museum-pass page"
        return events, meta
    except Exception as e:
        meta["error"] = f"{type(e).__name__}: {e}"
        return [], meta
