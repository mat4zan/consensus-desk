#!/usr/bin/env python3
"""Verify Metaculus detail responses for candidate posts. Delete after."""
import json
import os
import requests

TOKEN = os.environ.get("METACULUS_TOKEN")
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
if TOKEN:
    H["Authorization"] = f"Token {TOKEN}"
T = 25


def cp_of(q):
    latest = (q.get("aggregations", {}).get("recency_weighted", {}).get("latest") or {})
    c = latest.get("centers")
    return c[0] if c else None


for pid in (41138, 11480, 12309, 43688):
    print("\n" + "=" * 60)
    try:
        r = requests.get(f"https://www.metaculus.com/api/posts/{pid}/", headers=H, timeout=T)
        print(f"post {pid} -> HTTP {r.status_code}")
        if r.status_code != 200:
            continue
        d = r.json()
        print(f"  title: {d.get('title')}")
        q = d.get("question")
        if q:
            print(f"  SINGLE  type={q.get('type')}  cp={cp_of(q)}  nf={q.get('nr_forecasters')}")
        grp = d.get("group_of_questions")
        if grp:
            print("  GROUP subquestions:")
            for sub in grp.get("questions", []):
                print(f"    subid={sub.get('id')}  label={sub.get('label')!r}  "
                      f"type={sub.get('type')}  cp={cp_of(sub)}")
    except Exception as e:
        print("  ERROR:", e)

print("\nDONE.")
