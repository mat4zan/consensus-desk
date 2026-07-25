#!/usr/bin/env python3
"""Verify current Polymarket Fed-July sub-markets (increase buckets). Delete after."""
import requests
UA = {"User-Agent": "Mozilla/5.0 consensus-desk"}
T = 25

slugs = [
    "will-the-fed-increase-interest-rates-by-25-bps-after-the-july-2026-meeting",
    "will-the-fed-increase-interest-rates-by-50-bps-after-the-july-2026-meeting",
    "will-there-be-no-change-in-fed-interest-rates-after-the-july-2026-meeting",
    "will-the-fed-decrease-interest-rates-by-25-bps-after-the-july-2026-meeting",
]
for slug in slugs:
    try:
        r = requests.get("https://gamma-api.polymarket.com/markets",
                         params={"slug": slug}, headers=UA, timeout=T)
        data = r.json()
        if not data:
            print(f"MISS {slug}"); continue
        m = data[0]
        print(f"OK   {slug}")
        print(f"     '{m.get('question')}'  p={m.get('outcomePrices')}  "
              f"closed={m.get('closed')}  vol=${float(m.get('volumeNum') or 0):,.0f}")
    except Exception as e:
        print(f"ERR  {slug}: {e}")

print("\n=== public-search 'fed july 2026' (in case slugs shifted) ===")
r = requests.get("https://gamma-api.polymarket.com/public-search",
                 params={"q": "fed interest rate july 2026", "limit_per_type": 10},
                 headers=UA, timeout=T)
for e in r.json().get("events", []):
    print(f"EVENT: {e.get('title')}")
    for m in (e.get("markets") or []):
        print(f"   slug={m.get('slug')} closed={m.get('closed')} p={m.get('outcomePrices')}")
print("\nDONE.")
