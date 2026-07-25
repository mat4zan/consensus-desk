#!/usr/bin/env python3
"""Show Polymarket WW3-ish markets in detail. Delete after."""
import requests
UA = {"User-Agent": "Mozilla/5.0 consensus-desk"}
T = 25
for q in ("world war 3", "nuclear", "us russia war", "nato russia"):
    r = requests.get("https://gamma-api.polymarket.com/public-search",
                     params={"q": q, "limit_per_type": 6}, headers=UA, timeout=T)
    print(f"\n== '{q}' ==")
    for e in (r.json().get("events", []) if r.status_code == 200 else []):
        print(f"  EVENT: {e.get('title')}")
        for m in (e.get("markets") or [])[:4]:
            print(f"     slug={m.get('slug')} closed={m.get('closed')} p={m.get('outcomePrices')} vol={m.get('volumeNum')}")
print("DONE.")
