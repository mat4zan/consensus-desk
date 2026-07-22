#!/usr/bin/env python3
"""Authenticated Metaculus discovery. Confirms token + finds question IDs. Delete after."""
import os
import requests

TOKEN = os.environ.get("METACULUS_TOKEN")
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
if TOKEN:
    H["Authorization"] = f"Token {TOKEN}"
T = 25

print("token present:", bool(TOKEN), "| len:", len(TOKEN or ""))
try:
    r = requests.get("https://www.metaculus.com/api/posts/?limit=1", headers=H, timeout=T)
    print("auth check /api/posts/ -> HTTP", r.status_code)
except Exception as e:
    print("auth check ERROR:", e)

for term in ("taiwan", "russia ukraine ceasefire", "iran", "federal reserve rate"):
    print(f"\n--- search='{term}' ---")
    try:
        r = requests.get(
            "https://www.metaculus.com/api/posts/",
            params={"search": term, "limit": 6, "statuses": "open"},
            headers=H, timeout=T,
        )
        print("  HTTP", r.status_code)
        if r.status_code == 200:
            for p in r.json().get("results", []):
                q = p.get("question") or {}
                latest = (q.get("aggregations", {})
                          .get("recency_weighted", {}).get("latest") or {})
                centers = latest.get("centers")
                cp = centers[0] if centers else None
                ftype = q.get("type")
                print(f"    id={p.get('id')}  type={ftype}  cp={cp}  |  {p.get('title')}")
    except Exception as e:
        print("  ERROR:", e)

print("\nDONE.")
