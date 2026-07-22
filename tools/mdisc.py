#!/usr/bin/env python3
"""Confirm CP via history[-1]. Delete after."""
import json
import os
import requests

TOKEN = os.environ.get("METACULUS_TOKEN")
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
if TOKEN:
    H["Authorization"] = f"Token {TOKEN}"
T = 25


def probe(url):
    print("\n" + "=" * 60)
    print("URL:", url)
    r = requests.get(url, headers=H, timeout=T)
    print("  HTTP", r.status_code)
    if r.status_code != 200:
        print("  body:", r.text[:150]); return
    d = r.json()
    q = d.get("question") or d
    print("  title:", (q.get("title") or d.get("title")))
    agg = q.get("aggregations") or {}
    for method, val in agg.items():
        if not isinstance(val, dict):
            continue
        hist = val.get("history") or []
        latest = val.get("latest")
        print(f"  [{method}] history_len={len(hist)} latest={bool(latest)}")
        pt = latest or (hist[-1] if hist else None)
        if pt:
            print(f"    centers={pt.get('centers')} means={pt.get('means')} "
                  f"fv={str(pt.get('forecast_values'))[:80]} at={pt.get('start_time')}")


# Ukraine ceasefire (post) and the Taiwan-2028 subquestion (as a question)
probe("https://www.metaculus.com/api/posts/41138/?with_cp=true")
probe("https://www.metaculus.com/api/questions/34363/?with_cp=true")
print("\nDONE.")
