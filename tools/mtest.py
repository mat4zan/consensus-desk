#!/usr/bin/env python3
"""Probe whether Metaculus works without a token given a browser UA. Delete after."""
import requests

BROWSER = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/126.0 Safari/537.36"}
BOT = {"User-Agent": "consensus-desk/1.0"}
T = 25

print("=" * 70)
print("METACULUS UA TEST (no token)")
print("=" * 70)
for label, hdr in (("bot-UA", BOT), ("browser-UA", BROWSER)):
    try:
        r = requests.get("https://www.metaculus.com/api/posts/?limit=1",
                         headers=hdr, timeout=T)
        print(f"  [{label}] /api/posts/ -> HTTP {r.status_code}")
    except Exception as e:
        print(f"  [{label}] ERROR {e}")

print("\n--- search for real question IDs (browser UA) ---")
for term in ("taiwan china invade", "russia ukraine ceasefire", "iran", "fed rate"):
    try:
        r = requests.get(
            "https://www.metaculus.com/api/posts/",
            params={"search": term, "limit": 5, "statuses": "open",
                    "forecast_type": "binary"},
            headers=BROWSER, timeout=T,
        )
        print(f"\n  search='{term}' -> HTTP {r.status_code}")
        if r.status_code == 200:
            for p in r.json().get("results", [])[:5]:
                q = p.get("question") or {}
                latest = (q.get("aggregations", {})
                          .get("recency_weighted", {}).get("latest") or {})
                centers = latest.get("centers")
                cp = centers[0] if centers else None
                print(f"    id={p.get('id')}  cp={cp}  |  {p.get('title')}")
    except Exception as e:
        print(f"  ERROR {e}")

print("\nDONE.")
