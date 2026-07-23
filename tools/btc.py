#!/usr/bin/env python3
"""Find a Bitcoin threshold market + live BTC price for a Yahoo oracle. Delete after."""
import time
import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
T = 30

print("=== Yahoo BTC-USD current price ===")
r = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/BTC-USD?range=5d&interval=1d",
                 headers=UA, timeout=T)
res = r.json()["chart"]["result"][0]
closes = [c for c in res["indicators"]["quote"][0]["close"] if c]
print(f"latest BTC-USD close: {closes[-1]:,.0f}")

print("\n=== Manifold bitcoin threshold markets ===")
for term in ("bitcoin above 2026", "bitcoin reach 2026", "bitcoin all time high 2026", "bitcoin 200k"):
    r = requests.get("https://api.manifold.markets/v0/search-markets",
                     params={"term": term, "filter": "open", "contractType": "BINARY",
                             "sort": "liquidity", "limit": 4}, headers=UA, timeout=T)
    print(f"-- '{term}'")
    for m in r.json():
        close = m.get("closeTime")
        days = round((close/1000 - time.time())/86400, 1) if close else None
        print(f"   {m.get('slug')} p={m.get('probability'):.3f} bettors={m.get('uniqueBettorCount')} "
              f"closes_in={days}d | {(m.get('question') or '')[:52]}")

print("\n=== Polymarket bitcoin threshold markets ===")
markets = []
for off in range(0, 500, 100):
    r = requests.get("https://gamma-api.polymarket.com/markets",
                     params={"active": "true", "closed": "false", "limit": 100,
                             "offset": off, "order": "volumeNum", "ascending": "false"},
                     headers=UA, timeout=T)
    b = r.json()
    if not b:
        break
    markets += b
for m in markets:
    q = (m.get("question") or "").lower()
    if "bitcoin" in q and any(k in q for k in ("above", "reach", "hit", "$", "k by", "all-time", "all time")):
        print(f"   {m.get('slug')} p={m.get('outcomePrices')} ${float(m.get('volumeNum') or 0):,.0f} | {m.get('question')[:52]}")

print("\nDONE.")
