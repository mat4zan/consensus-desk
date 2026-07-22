#!/usr/bin/env python3
"""Dump raw Metaculus aggregations to find the CP path. Delete after."""
import json
import os
import requests

TOKEN = os.environ.get("METACULUS_TOKEN")
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
if TOKEN:
    H["Authorization"] = f"Token {TOKEN}"
T = 25

for url in (
    "https://www.metaculus.com/api/posts/41138/?with_cp=true",
    "https://www.metaculus.com/api/questions/41138/?with_cp=true",
):
    print("\n" + "=" * 60)
    print("URL:", url)
    try:
        r = requests.get(url, headers=H, timeout=T)
        print("  HTTP", r.status_code)
        if r.status_code != 200:
            print("  body:", r.text[:200])
            continue
        d = r.json()
        q = d.get("question") or d
        print("  cp_reveal_time:", q.get("cp_reveal_time"))
        print("  default_aggregation_method:", q.get("default_aggregation_method"))
        agg = q.get("aggregations") or {}
        print("  aggregations keys:", list(agg.keys()))
        for method, val in agg.items():
            if isinstance(val, dict):
                latest = val.get("latest")
                print(f"    [{method}] keys={list(val.keys())} latest_present={bool(latest)}")
                if latest:
                    print(f"      latest keys: {list(latest.keys())}")
                    print(f"      centers={latest.get('centers')} means={latest.get('means')} "
                          f"fv={str(latest.get('forecast_values'))[:80]}")
    except Exception as e:
        print("  ERROR:", e)

print("\nDONE.")
