#!/usr/bin/env python3
"""Verify oracle fetchers + evaluation on live data. Delete after."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.oracles import apply_rule, fred_series, yahoo_series

print("=== FRED DFEDTARU (fed funds target upper) ===")
f = fred_series("DFEDTARU")
print(f"points={len(f)}  latest 4: {f[-4:]}")

print("\n=== Yahoo ^GSPC (S&P 500) ===")
y = yahoo_series("^GSPC")
print(f"points={len(y)}  latest: {y[-1] if y else None}")

print("\n=== end-to-end eval on REAL data ===")
# Did the fed funds upper target drop >=0.25 during H2-2024 (real, historical)?
fed_cfg = {"rule": "dropped", "amount": 0.25,
           "window_start": "2024-08-01", "by": "2025-01-01"}
print("fed 2024H2 dropped>=0.25:", apply_rule(fed_cfg, f))

# Did the S&P cross above 5000 in the past year (real)?
sp_cfg = {"rule": "crossed_above", "threshold": 5000,
          "window_start": "2025-07-01", "by": "2026-07-01"}
print("sp500 crossed_above 5000:", apply_rule(sp_cfg, y))

print("\nDONE.")
