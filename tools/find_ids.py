#!/usr/bin/env python3
"""
Throwaway helper: query the live source APIs and print exact IDs
(Polymarket market slugs, Kalshi tickers, Metaculus question ids) for the
themes we track, so config/topics.yml can be wired with verified values.

Run on GitHub Actions (real clock + network). Delete after use.
"""
import json
import sys

import requests

UA = {"User-Agent": "consensus-desk/idfinder"}
T = 25

THEMES = {
    "taiwan": ["taiwan", "china invade", "china blockade", "china attack"],
    "ru_ua": ["ukraine", "russia", "ceasefire"],
    "isr_iran": ["israel", "iran"],
    "fed": ["fed", "rate cut", "interest rate", "fomc"],
    "italy": ["italy", "btp", "bund", "spread"],
}


def hit(theme, text):
    t = (text or "").lower()
    return any(k in t for k in THEMES[theme])


def section(title):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def polymarket():
    section("POLYMARKET  (use the 'slug' field as the id in topics.yml)")
    try:
        r = requests.get(
            "https://gamma-api.polymarket.com/markets",
            params={"active": "true", "closed": "false", "limit": 500,
                    "order": "volumeNum", "ascending": "false"},
            headers=UA, timeout=T,
        )
        r.raise_for_status()
        markets = r.json()
    except Exception as e:
        print("  ERROR:", e)
        return
    print(f"  fetched {len(markets)} active markets")
    for theme in THEMES:
        print(f"\n  --- {theme} ---")
        n = 0
        for m in markets:
            q = m.get("question") or ""
            if hit(theme, q):
                vol = m.get("volumeNum") or m.get("volume") or 0
                print(f"    slug: {m.get('slug')}")
                print(f"      q : {q}  (${float(vol):,.0f})")
                n += 1
                if n >= 6:
                    break
        if n == 0:
            print("    (none found in top 500 by volume)")


def kalshi():
    section("KALSHI  (use the 'ticker' field as the id in topics.yml)")
    try:
        seen = []
        cursor = None
        for _ in range(6):  # up to 6 pages
            params = {"limit": 1000, "status": "open"}
            if cursor:
                params["cursor"] = cursor
            r = requests.get(
                "https://api.elections.kalshi.com/trade-api/v2/markets",
                params=params, headers=UA, timeout=T,
            )
            r.raise_for_status()
            d = r.json()
            seen.extend(d.get("markets", []))
            cursor = d.get("cursor")
            if not cursor:
                break
    except Exception as e:
        print("  ERROR:", e)
        return
    print(f"  fetched {len(seen)} open markets")
    for theme in THEMES:
        print(f"\n  --- {theme} ---")
        n = 0
        for m in seen:
            title = (m.get("title") or "") + " " + (m.get("subtitle") or "")
            if hit(theme, title):
                print(f"    ticker: {m.get('ticker')}")
                print(f"      t   : {title.strip()}")
                n += 1
                if n >= 8:
                    break
        if n == 0:
            print("    (none found)")


def metaculus():
    section("METACULUS  (use the numeric 'id' in topics.yml)")
    for theme, terms in THEMES.items():
        q = terms[0]
        print(f"\n  --- {theme} (search='{q}') ---")
        got = False
        # Try modern posts API first, then legacy api2.
        for url in (
            f"https://www.metaculus.com/api/posts/?search={q}&limit=5&statuses=open",
            f"https://www.metaculus.com/api2/questions/?search={q}&limit=5",
        ):
            try:
                r = requests.get(url, headers=UA, timeout=T)
                if r.status_code != 200:
                    print(f"    [{url.split('/api')[1][:12]}] HTTP {r.status_code}")
                    continue
                results = r.json().get("results", [])
                for item in results[:5]:
                    qid = item.get("id")
                    title = item.get("title") or item.get("question", {}).get("title")
                    print(f"    id: {qid}  |  {title}")
                got = True
                break
            except Exception as e:
                print("    ERROR:", e)
        if not got:
            print("    (no usable API response)")


if __name__ == "__main__":
    polymarket()
    kalshi()
    metaculus()
    print("\nDONE.", file=sys.stderr)
