"""LCSD monthly HKCC calendar / culture search — soft-fail probe only.

The monthly calendar and performing-arts e-calendar are JS-rendered;
the culture-search AJAX endpoint returned 404 from this environment.
We document the attempt and return empty rather than invent data.
"""
from __future__ import annotations

from typing import Any

from .common import polite_get

SOURCE = "康文署每月節目表（探測）"
URLS = [
    "https://www.lcsd.gov.hk/tc/hkcc/programmes/currentmonth.html",
    "https://www.performing-arts.gov.hk/tc/e-calendar.html?subscribe_code=HKCC",
]


def fetch_events(session=None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    meta: dict[str, Any] = {
        "source": SOURCE,
        "url": URLS[0],
        "ok": False,
        "skipped": True,
        "count": 0,
        "error": None,
    }
    notes = []
    try:
        for u in URLS:
            try:
                resp = polite_get(u, session=session)
                text = resp.text
                # Heuristic: real calendar rows usually include 票價 + programme titles densely.
                if "音樂廳" in text and "票價" in text and text.count("Concert Hall") + text.count("音樂廳") > 3:
                    # Still no reliable server-side rows in fetched HTML (SPA shell).
                    notes.append(f"{u}: HTML shell only / insufficient structured rows")
                else:
                    notes.append(f"{u}: no structured programme table in static HTML")
            except Exception as e:
                notes.append(f"{u}: {type(e).__name__}: {e}")
        meta["error"] = (
            "Soft-skip: HKCC monthly calendar / performing-arts e-calendar appear JS-rendered; "
            "static HTML lacks parseable event rows. Culture search AJAX also unavailable. "
            + " | ".join(notes)
        )
    except Exception as e:
        meta["error"] = f"{type(e).__name__}: {e}"
    return [], meta
