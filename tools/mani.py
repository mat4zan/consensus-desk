#!/usr/bin/env python3
"""Discover Manifold markets (open API, no auth). Delete after."""
import time
import requests

UA = {"User-Agent": "consensus-desk/idfinder"}
T = 25
BASE = "https://api.manifold.markets/v0"


def show(m):
    close = m.get("closeTime")
    days = None
    if close:
        days = round((close / 1000 - time.time()) / 86400, 1)
    print(f"    slug={m.get('slug')}")
    print(f"       p={m.get('probability')}  vol={round(m.get('volume') or 0)}  "
          f"bettors={m.get('uniqueBettorCount')}  closes_in_days={days}")
    print(f"       q: {(m.get('question') or '')[:70]}")


def search(term, **extra):
    params = {"term": term, "filter": "open", "contractType": "BINARY",
              "sort": "liquidity", "limit": 6}
    params.update(extra)
    r = requests.get(f"{BASE}/search-markets", params=params, headers=UA, timeout=T)
    print(f"\n--- '{term}' {extra} -> HTTP {r.status_code} ---")
    if r.status_code == 200:
        for m in r.json():
            show(m)


print("=" * 60)
print("MANIFOLD theme search")
print("=" * 60)
for term in ("china taiwan invade", "russia ukraine ceasefire", "iran", "fed rate cut september"):
    search(term)

print("\n" + "=" * 60)
print("SHORT-TERM markets closing this week (for resolution test)")
print("=" * 60)
# high-activity binary markets closing within a week
r = requests.get(f"{BASE}/search-markets",
                 params={"term": "", "filter": "closing-week", "contractType": "BINARY",
                         "sort": "liquidity", "limit": 15},
                 headers=UA, timeout=T)
print("HTTP", r.status_code)
if r.status_code == 200:
    for m in r.json():
        if (m.get("uniqueBettorCount") or 0) >= 20:
            show(m)

print("\nDONE.")
