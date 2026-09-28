#!/usr/bin/env python3
"""Refresh HK date-cards event JSON from public sources (best-effort)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
OUT = DATA / "events.json"
LOG = DATA / "refresh_log.json"
SAMPLE = DATA / "sample_events.json"

from scrapers.common import dedupe_events, now_hkt_iso
from scrapers import lcsd_free, weekendhk, timable, lcsd_calendar


def load_sample() -> list[dict]:
    if SAMPLE.exists():
        return json.loads(SAMPLE.read_text(encoding="utf-8")).get("events", [])
    return []


def main() -> int:
    ap = argparse.ArgumentParser(description="Refresh HK date-cards data")
    ap.add_argument("--sample-only", action="store_true", help="Write sample JSON only (no network)")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    DATA.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    sources_meta = []
    events: list[dict] = []

    if args.sample_only:
        events = load_sample()
        sources_meta.append({"source": "hand-curated sample", "ok": True, "count": len(events)})
    else:
        for mod in (lcsd_free, weekendhk, timable, lcsd_calendar):
            print(f"→ {mod.SOURCE} ...", flush=True)
            evs, meta = mod.fetch_events(session=session)
            sources_meta.append(meta)
            status = "OK" if meta.get("ok") else ("SKIP" if meta.get("skipped") else "FAIL")
            print(f"  {status} count={meta.get('count', 0)} err={meta.get('error')}", flush=True)
            events.extend(evs)

        events = dedupe_events(events)
        if not events:
            print("No live events; seeding from sample_events.json", flush=True)
            events = load_sample()
            sources_meta.append(
                {
                    "source": "hand-curated sample (fallback)",
                    "ok": True,
                    "count": len(events),
                    "note": "Used because live scrapers returned 0 events",
                }
            )

    payload = {
        "updated_at": now_hkt_iso(),
        "timezone": "Asia/Hong_Kong",
        "tag_taxonomy": {
            "occasion": ["室內", "戶外", "半日", "夜晚", "週末"],
            "mood": ["安靜", "熱鬧", "行路多", "坐低傾"],
            "budget": ["免費", "$100內", "$100–300", "$300–600", "$600+"],
            "optional": ["要早訂", "親子向", "大型公演"],
            "rules": [
                "卡片最多顯示 1–2 個 tags",
                "預算未知時顯示「預算未知」，不發明 budget tag",
                "地區寫在地點欄，不當 tag",
            ],
        },
        "events": events,
        "sources": sources_meta,
    }
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    LOG.write_text(
        json.dumps({"updated_at": payload["updated_at"], "sources": sources_meta, "event_count": len(events)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {len(events)} events → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
