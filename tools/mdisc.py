#!/usr/bin/env python3
"""Decisive: does ANY question expose CP to this token? Delete after."""
import os
import requests

TOKEN = os.environ.get("METACULUS_TOKEN")
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
if TOKEN:
    H["Authorization"] = f"Token {TOKEN}"
T = 25


def check(pid):
    r = requests.get(f"https://www.metaculus.com/api/posts/{pid}/?with_cp=true", headers=H, timeout=T)
    if r.status_code != 200:
        print(f"  post {pid}: HTTP {r.status_code}"); return
    d = r.json(); q = d.get("question") or {}
    agg = (q.get("aggregations") or {}).get("recency_weighted") or {}
    hist = agg.get("history") or []
    latest = agg.get("latest")
    pt = latest or (hist[-1] if hist else None)
    centers = pt.get("centers") if pt else None
    print(f"  post {pid}: nf={q.get('nr_forecasters')} fcount={q.get('forecast_count')} "
          f"hist_len={len(hist)} centers={centers}  | {(d.get('title') or '')[:50]}")


# 1) list endpoint — does with_cp populate aggregations there?
print("=== LIST /api/posts/?with_cp=true (order by activity) ===")
r = requests.get("https://www.metaculus.com/api/posts/",
                 params={"limit": 3, "with_cp": "true", "order_by": "-activity",
                         "statuses": "open", "forecast_type": "binary"},
                 headers=H, timeout=T)
print("  HTTP", r.status_code)
if r.status_code == 200:
    for p in r.json().get("results", []):
        q = p.get("question") or {}
        agg = (q.get("aggregations") or {}).get("recency_weighted") or {}
        hist = agg.get("history") or []
        latest = agg.get("latest")
        pt = latest or (hist[-1] if hist else None)
        print(f"    id={p.get('id')} nf={q.get('nr_forecasters')} hist={len(hist)} "
              f"centers={pt.get('centers') if pt else None} | {(p.get('title') or '')[:45]}")

print("\n=== DETAIL famous questions ===")
for pid in (5253, 578, 349):   # Iran nuke 2030; classic long-running questions
    check(pid)

print("\nmy_forecasts empty check:")
r = requests.get("https://www.metaculus.com/api/posts/5253/?with_cp=true", headers=H, timeout=T)
if r.status_code == 200:
    q = (r.json().get("question") or {})
    print("  my_forecasts:", q.get("my_forecasts"))
print("\nDONE.")
