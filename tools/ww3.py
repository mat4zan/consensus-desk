#!/usr/bin/env python3
"""Check Polymarket + PredictIt for WW3 markets. Delete after."""
import requests
UA = {"User-Agent": "Mozilla/5.0 consensus-desk"}
T = 25

print("=== POLYMARKET public-search ===")
for q in ("world war", "ww3", "world war 3", "nuclear weapon detonation"):
    try:
        r = requests.get("https://gamma-api.polymarket.com/public-search",
                         params={"q": q, "limit_per_type": 6}, headers=UA, timeout=T)
        evs = r.json().get("events", []) if r.status_code == 200 else []
        print(f"-- '{q}': {len(evs)} events")
        for e in evs[:5]:
            for m in (e.get("markets") or [])[:2]:
                if not m.get("closed"):
                    print(f"    {m.get('slug')}  p={m.get('outcomePrices')}")
    except Exception as ex:
        print("  ERR", ex)

print("\n=== PREDICTIT ===")
try:
    r = requests.get("https://www.predictit.org/api/marketdata/all/", headers=UA, timeout=T)
    for mk in r.json().get("markets", []):
        n = (mk.get("shortName") or "") + " " + (mk.get("name") or "")
        if any(k in n.lower() for k in ("war", "nuclear", "ww3")):
            print(f"  id={mk.get('id')} '{mk.get('shortName')}'")
except Exception as ex:
    print("  ERR", ex)
print("DONE.")
