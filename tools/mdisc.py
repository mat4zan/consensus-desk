#!/usr/bin/env python3
"""Find the correct path to Metaculus community prediction. Delete after."""
import json
import os
import requests

TOKEN = os.environ.get("METACULUS_TOKEN")
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
if TOKEN:
    H["Authorization"] = f"Token {TOKEN}"
T = 25


def dump(pid, params):
    print("\n" + "=" * 60)
    print(f"post {pid} params={params}")
    r = requests.get(f"https://www.metaculus.com/api/posts/{pid}/", headers=H, params=params, timeout=T)
    print("  HTTP", r.status_code)
    if r.status_code != 200:
        return
    d = r.json()
    q = d.get("question") or {}
    print("  question keys:", sorted(q.keys()))
    agg = q.get("aggregations")
    if agg:
        rw = agg.get("recency_weighted", {})
        latest = rw.get("latest")
        print("  recency_weighted.latest present:", bool(latest))
        if latest:
            print("    latest keys:", sorted(latest.keys()))
            print("    centers:", latest.get("centers"))
            print("    forecast_values:", str(latest.get("forecast_values"))[:120])
    # group?
    grp = d.get("group_of_questions")
    if grp:
        for sub in grp.get("questions", [])[:6]:
            latest = (sub.get("aggregations", {}).get("recency_weighted", {}).get("latest") or {})
            print(f"    subid={sub.get('id')} label={sub.get('label')!r} centers={latest.get('centers')}")


# Ukraine ceasefire binary — try with and without with_cp
dump(41138, {})
dump(41138, {"with_cp": "true"})
# Taiwan invasion group with with_cp
dump(11480, {"with_cp": "true"})

print("\nDONE.")
