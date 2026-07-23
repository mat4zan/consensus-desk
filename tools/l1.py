#!/usr/bin/env python3
"""Find a 2026-midterm control market across all four venues. Delete after."""
import time
import requests

UA = {"User-Agent": "consensus-desk/idfinder"}
T = 25


def sec(t):
    print("\n" + "=" * 60 + f"\n{t}\n" + "=" * 60)


# ---- PredictIt: get contract names/prices for the control markets ----
sec("PREDICTIT — Senate/House control contracts")
for mid in (8155, 8157, 8163, 7589):
    try:
        r = requests.get(f"https://www.predictit.org/api/marketdata/markets/{mid}",
                         headers=UA, timeout=T)
        if r.status_code != 200:
            print(f"  {mid}: HTTP {r.status_code}"); continue
        d = r.json()
        print(f"  id={mid} '{d.get('shortName')}'")
        for c in d.get("contracts", []):
            print(f"      contract id={c.get('id')} name='{c.get('name')}' "
                  f"last={c.get('lastTradePrice')}")
    except Exception as e:
        print(f"  {mid}: ERR {e}")

# ---- Polymarket: grep active markets for congressional control ----
sec("POLYMARKET — senate/house/midterm markets")
try:
    markets = []
    for off in range(0, 600, 100):
        r = requests.get("https://gamma-api.polymarket.com/markets",
                         params={"active": "true", "closed": "false", "limit": 100,
                                 "offset": off, "order": "volumeNum", "ascending": "false"},
                         headers=UA, timeout=T)
        r.raise_for_status()
        b = r.json()
        if not b:
            break
        markets += b
    for m in markets:
        q = (m.get("question") or "").lower()
        if any(k in q for k in ("senate", "house of represent"," midterm", "congress")) \
           and "2026" in q:
            print(f"  slug={m.get('slug')}  p={m.get('outcomePrices')}  ${float(m.get('volumeNum') or 0):,.0f}")
            print(f"     {m.get('question')}")
except Exception as e:
    print("  ERR", e)

# ---- Kalshi: control events ----
sec("KALSHI — senate/house control events")
try:
    events = []; cursor = None
    for _ in range(10):
        p = {"limit": 200, "status": "open", "with_nested_markets": "true"}
        if cursor:
            p["cursor"] = cursor
        r = requests.get("https://api.elections.kalshi.com/trade-api/v2/events",
                         headers=UA, params=p, timeout=T)
        r.raise_for_status(); d = r.json(); events += d.get("events", []); cursor = d.get("cursor")
        if not cursor:
            break
    for ev in events:
        t = (ev.get("title") or "").lower()
        if ("senate" in t or "house" in t or "congress" in t) and "2026" in t:
            print(f"  {ev.get('event_ticker')} | {ev.get('title')}")
            for m in (ev.get("markets") or [])[:4]:
                print(f"      {m.get('ticker')} bid={m.get('yes_bid')} ask={m.get('yes_ask')} ({m.get('yes_sub_title')})")
except Exception as e:
    print("  ERR", e)

# ---- Manifold ----
sec("MANIFOLD — senate/house 2026 control")
for term in ("2026 senate control party", "2026 house control party", "republicans senate 2026"):
    try:
        r = requests.get("https://api.manifold.markets/v0/search-markets",
                         params={"term": term, "filter": "open", "contractType": "BINARY",
                                 "sort": "liquidity", "limit": 4}, headers=UA, timeout=T)
        print(f"  '{term}':")
        for m in r.json():
            print(f"      slug={m.get('slug')} p={m.get('probability')} bettors={m.get('uniqueBettorCount')} | {(m.get('question') or '')[:55]}")
    except Exception as e:
        print("  ERR", e)

print("\nDONE.")
