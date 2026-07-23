#!/usr/bin/env python3
"""Diagnostic: do Kalshi's most-liquid markets expose quotes publicly? Delete after."""
import requests

UA = {"User-Agent": "consensus-desk/idfinder"}
T = 25

markets = []
cursor = None
for _ in range(8):
    p = {"limit": 1000, "status": "open"}
    if cursor:
        p["cursor"] = cursor
    r = requests.get("https://api.elections.kalshi.com/trade-api/v2/markets",
                     headers=UA, params=p, timeout=T)
    r.raise_for_status()
    d = r.json()
    markets += d.get("markets", [])
    cursor = d.get("cursor")
    if not cursor:
        break

print(f"scanned {len(markets)} open markets")


def vol(m):
    return m.get("dollar_volume") or m.get("volume") or 0


top = sorted(markets, key=vol, reverse=True)[:20]
print("\nTOP 20 BY VOLUME — do they have bid/ask?")
quoted = 0
for m in top:
    b, a, l = m.get("yes_bid"), m.get("yes_ask"), m.get("last_price")
    if b is not None or a is not None or l:
        quoted += 1
    print(f"  {m.get('ticker'):32} vol={vol(m):>10}  bid={b} ask={a} last={l} status={m.get('status')}")

print(f"\n{quoted}/20 top markets have a quote.")

# How many of ALL open markets have any quote?
any_quote = sum(1 for m in markets
                if m.get("yes_bid") is not None or m.get("yes_ask") is not None or m.get("last_price"))
print(f"{any_quote}/{len(markets)} of ALL open markets have any quote.")
print("\nDONE.")
