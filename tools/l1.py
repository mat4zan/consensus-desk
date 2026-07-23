#!/usr/bin/env python3
"""Discover more Layer-1 sources: Kalshi liquidity + PredictIt. Delete after."""
import requests

UA = {"User-Agent": "consensus-desk/idfinder"}
T = 25

print("=" * 60)
print("KALSHI — are the wired Fed markets quoted now?")
print("=" * 60)
for tk in ("KXFEDDECISION-26JUL-C25", "KXFEDDECISION-26JUL-C26",
           "KXFEDDECISION-26SEP-C25", "KXFEDDECISION-26SEP-C26"):
    try:
        r = requests.get(f"https://api.elections.kalshi.com/trade-api/v2/markets/{tk}",
                         headers=UA, timeout=T)
        if r.status_code != 200:
            print(f"  {tk}: HTTP {r.status_code}"); continue
        m = r.json().get("market", {})
        print(f"  {tk}: bid={m.get('yes_bid')} ask={m.get('yes_ask')} "
              f"last={m.get('last_price')} vol={m.get('volume')} oi={m.get('open_interest')} "
              f"status={m.get('status')}")
    except Exception as e:
        print(f"  {tk}: ERR {e}")

print("\n" + "=" * 60)
print("KALSHI — liquid markets overlapping our themes (events w/ quotes)")
print("=" * 60)
try:
    events = []
    cursor = None
    for _ in range(8):
        p = {"limit": 200, "status": "open", "with_nested_markets": "true"}
        if cursor:
            p["cursor"] = cursor
        r = requests.get("https://api.elections.kalshi.com/trade-api/v2/events",
                         headers=UA, params=p, timeout=T)
        r.raise_for_status()
        d = r.json(); events += d.get("events", []); cursor = d.get("cursor")
        if not cursor:
            break
    kws = ("recession", "cpi", "inflation", "gdp", "government shutdown",
           "ukraine", "iran", "russia", "nuclear")
    seen = 0
    for ev in events:
        title = (ev.get("title") or "").lower()
        if any(k in title for k in kws):
            liquid = [m for m in (ev.get("markets") or [])
                      if m.get("yes_bid") is not None or m.get("last_price")]
            if liquid:
                print(f"  {ev.get('event_ticker')} | {ev.get('title')}")
                for m in liquid[:3]:
                    print(f"      {m.get('ticker')} bid={m.get('yes_bid')} ask={m.get('yes_ask')} "
                          f"last={m.get('last_price')} ({m.get('yes_sub_title')})")
                seen += 1
        if seen >= 12:
            break
except Exception as e:
    print("  ERR", e)

print("\n" + "=" * 60)
print("PREDICTIT — public API test + top political markets")
print("=" * 60)
try:
    r = requests.get("https://www.predictit.org/api/marketdata/all/", headers=UA, timeout=T)
    print("  HTTP", r.status_code)
    if r.status_code == 200:
        markets = r.json().get("markets", [])
        print(f"  {len(markets)} markets")
        for mk in markets[:12]:
            contracts = mk.get("contracts", [])
            top = max(contracts, key=lambda c: c.get("lastTradePrice") or 0, default=None)
            price = top.get("lastTradePrice") if top else None
            print(f"    id={mk.get('id')} '{(mk.get('shortName') or '')[:45]}' "
                  f"contracts={len(contracts)} topPrice={price}")
except Exception as e:
    print("  ERR", e)

print("\nDONE.")
