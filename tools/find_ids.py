#!/usr/bin/env python3
"""Final targeted verification of the exact IDs to wire. Delete after use."""
import sys
import requests

UA = {"User-Agent": "consensus-desk/idfinder"}
T = 25


def section(t):
    print("\n" + "=" * 70 + f"\n{t}\n" + "=" * 70)


def kalshi_fed():
    section("KALSHI — all KXFEDDECISION meetings (find Sep/Oct 2026)")
    try:
        r = requests.get(
            "https://api.elections.kalshi.com/trade-api/v2/events",
            params={"series_ticker": "KXFEDDECISION", "status": "open",
                    "with_nested_markets": "true", "limit": 200},
            headers=UA, timeout=T,
        )
        r.raise_for_status()
        for ev in r.json().get("events", []):
            print(f"  event {ev.get('event_ticker')}  |  {ev.get('title')}")
            for m in ev.get("markets") or []:
                print(f"      {m.get('ticker')}  ({m.get('yes_sub_title')})  "
                      f"bid={m.get('yes_bid')} ask={m.get('yes_ask')} status={m.get('status')}")
    except Exception as e:
        print("  ERROR:", e)


def poly_confirm():
    section("POLYMARKET — confirm chosen slugs return a price")
    slugs = [
        "will-china-invade-taiwan-by-december-31-2027",
        "china-x-taiwan-military-clash-before-2027",
        "russia-x-ukraine-ceasefire-agreement-by-december-31-2026",
        "will-the-us-invade-iran-before-2027",
        "will-the-iranian-regime-fall-by-the-end-of-2026",
        "will-no-fed-rate-cuts-happen-in-2026",
    ]
    for slug in slugs:
        try:
            r = requests.get("https://gamma-api.polymarket.com/markets",
                             params={"slug": slug}, headers=UA, timeout=T)
            data = r.json()
            if not data:
                print(f"  MISS {slug}")
                continue
            m = data[0]
            prices = m.get("outcomePrices")
            print(f"  OK   {slug}")
            print(f"         '{m.get('question')}'  prices={prices} vol=${float(m.get('volumeNum') or 0):,.0f} closed={m.get('closed')}")
        except Exception as e:
            print(f"  ERR  {slug}: {e}")


if __name__ == "__main__":
    kalshi_fed()
    poly_confirm()
    print("\nDONE.", file=sys.stderr)
