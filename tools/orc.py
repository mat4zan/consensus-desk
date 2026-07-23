#!/usr/bin/env python3
"""Find the correct DBnomics path for a FRED series. Delete after."""
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

UA = {"User-Agent": "Mozilla/5.0 consensus-desk"}
T = 40

print("=== DBnomics search for DFEDTARU (find provider/dataset/series) ===")
try:
    r = requests.get("https://api.db.nomics.world/v22/search",
                     params={"q": "DFEDTARU", "limit": 5}, headers=UA, timeout=T)
    print("HTTP", r.status_code)
    docs = r.json().get("results", {}).get("docs", [])
    for d in docs[:5]:
        print(f"  provider={d.get('provider_code')} dataset={d.get('dataset_code')} "
              f"series={d.get('series_code')} | {d.get('series_name')}")
except Exception as e:
    print("search ERR", e)

print("\n=== try direct path variants ===")
for url in (
    "https://api.db.nomics.world/v22/series/FRED/DFEDTARU/DFEDTARU?observations=1",
    "https://api.db.nomics.world/v22/series?series_ids=FRED/DFEDTARU/DFEDTARU&observations=1",
):
    try:
        r = requests.get(url, headers=UA, timeout=T)
        docs = r.json().get("series", {}).get("docs", []) if r.status_code == 200 else []
        n = len(docs[0].get("value", [])) if docs else 0
        print(f"  HTTP {r.status_code}  obs={n}  <- {url}")
    except Exception as e:
        print(f"  ERR {e}  <- {url}")

print("\nDONE.")
