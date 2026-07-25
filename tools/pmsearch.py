#!/usr/bin/env python3
"""Find the Romania PM market + test Polymarket's relevance search. Delete after."""
import requests
UA = {"User-Agent": "Mozilla/5.0 consensus-desk"}
T = 25

print("=== public-search q=romania prime minister ===")
for q in ("romania prime minister", "romania pm", "romanian prime minister"):
    try:
        r = requests.get("https://gamma-api.polymarket.com/public-search",
                         params={"q": q, "limit_per_type": 10}, headers=UA, timeout=T)
        print(f"\n-- '{q}' HTTP {r.status_code}")
        if r.status_code == 200:
            d = r.json()
            evs = d.get("events", [])
            print(f"   events: {len(evs)}")
            for e in evs[:6]:
                mk = e.get("markets") or []
                print(f"   event slug={e.get('slug')} | {e.get('title')}")
                for m in mk[:3]:
                    print(f"       market slug={m.get('slug')} p={m.get('outcomePrices')}")
    except Exception as ex:
        print("  ERR", ex)

print("\n=== paginate 800, grep 'romania' ===")
markets = []
for off in range(0, 800, 100):
    try:
        r = requests.get("https://gamma-api.polymarket.com/markets",
                         params={"active": "true", "closed": "false", "limit": 100,
                                 "offset": off, "order": "volumeNum", "ascending": "false"},
                         headers=UA, timeout=T)
        markets += r.json()
    except Exception:
        break
hits = [m for m in markets if "romania" in (m.get("question") or "").lower()]
print(f"scanned {len(markets)}, romania hits: {len(hits)}")
for m in hits[:8]:
    print(f"   slug={m.get('slug')} vol=${float(m.get('volumeNum') or 0):,.0f} | {m.get('question')}")
print("\nDONE.")
