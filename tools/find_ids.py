#!/usr/bin/env python3
"""
Throwaway helper: query the live source APIs and print exact IDs
(Polymarket market slugs, Kalshi tickers) for the themes we track.
Run on GitHub Actions (real clock + network). Delete after use.
"""
import sys
import requests

UA = {"User-Agent": "consensus-desk/idfinder"}
T = 25

THEMES = {
    "taiwan":   ["taiwan"],
    "ru_ua":    ["ceasefire", "ukraine war", "russia ukraine"],
    "isr_iran": ["israel", "iran"],
    "fed":      ["fed ", "interest rate", "rate cut", "fomc"],
}


def hit(text):
    t = (text or "").lower()
    return {k for k, terms in THEMES.items() if any(x in t for x in terms)}


def section(t):
    print("\n" + "=" * 70 + f"\n{t}\n" + "=" * 70)


def polymarket():
    section("POLYMARKET — market slugs (paginated, 800 markets)")
    markets = []
    for off in range(0, 800, 100):
        try:
            r = requests.get(
                "https://gamma-api.polymarket.com/markets",
                params={"active": "true", "closed": "false", "limit": 100,
                        "offset": off, "order": "volumeNum", "ascending": "false"},
                headers=UA, timeout=T,
            )
            r.raise_for_status()
            batch = r.json()
            if not batch:
                break
            markets.extend(batch)
        except Exception as e:
            print("  ERROR page", off, e)
            break
    print(f"  scanned {len(markets)} markets")
    by_theme = {k: [] for k in THEMES}
    for m in markets:
        q = m.get("question") or ""
        for k in hit(q):
            by_theme[k].append((m.get("slug"), q, m.get("volumeNum") or 0))
    for k, items in by_theme.items():
        print(f"\n  --- {k} ---")
        if not items:
            print("    (none)")
        for slug, q, vol in items[:10]:
            print(f"    {slug}\n       {q}  (${float(vol):,.0f})")

    # Direct probes for the exact markets we want.
    section("POLYMARKET — direct slug probes")
    probes = [
        "russia-x-ukraine-ceasefire-before-2027",
        "russia-x-ukraine-ceasefire-in-2026",
        "will-the-fed-decrease-interest-rates-by-25-bps-after-the-september-2026-meeting",
        "will-there-be-no-change-in-fed-interest-rates-after-the-september-2026-meeting",
        "israel-x-iran-ceasefire-in-2026",
    ]
    for slug in probes:
        try:
            r = requests.get("https://gamma-api.polymarket.com/markets",
                             params={"slug": slug}, headers=UA, timeout=T)
            data = r.json()
            if data:
                m = data[0]
                print(f"  OK   {slug}\n         {m.get('question')}  (${float(m.get('volumeNum') or 0):,.0f})")
            else:
                print(f"  MISS {slug}")
        except Exception as e:
            print(f"  ERR  {slug}: {e}")


def kalshi():
    section("KALSHI — events (title) then their markets (ticker)")
    events = []
    cursor = None
    for _ in range(10):
        try:
            params = {"limit": 200, "status": "open", "with_nested_markets": "true"}
            if cursor:
                params["cursor"] = cursor
            r = requests.get("https://api.elections.kalshi.com/trade-api/v2/events",
                             params=params, headers=UA, timeout=T)
            r.raise_for_status()
            d = r.json()
            events.extend(d.get("events", []))
            cursor = d.get("cursor")
            if not cursor:
                break
        except Exception as e:
            print("  ERROR", e)
            break
    print(f"  scanned {len(events)} events")
    for k in THEMES:
        print(f"\n  --- {k} ---")
        n = 0
        for ev in events:
            title = ev.get("title") or ""
            if k in hit(title):
                print(f"    event: {ev.get('event_ticker')}  |  {title}")
                for m in (ev.get("markets") or [])[:6]:
                    print(f"        ticker: {m.get('ticker')}  |  {m.get('yes_sub_title') or m.get('subtitle') or ''}")
                n += 1
                if n >= 5:
                    break
        if n == 0:
            print("    (none)")


if __name__ == "__main__":
    polymarket()
    kalshi()
    print("\nDONE.", file=sys.stderr)
