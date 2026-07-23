#!/usr/bin/env python3
"""Verify FRED (official API + key) end-to-end. Delete after."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.oracles import apply_rule, fred_series

print("=== FRED DFEDTARU (fed funds target upper) via official API ===")
f = fred_series("DFEDTARU")
print(f"points={len(f)}  latest 4: {f[-4:]}")

print("\n=== end-to-end eval on REAL data ===")
# Real historical check: did the fed funds upper target drop >=0.25 in H2-2024?
cfg = {"rule": "dropped", "amount": 0.25,
       "window_start": "2024-08-01", "by": "2025-01-01"}
print("fed 2024H2 dropped>=0.25:", apply_rule(cfg, f))

# What the July-2026 oracle will compute once the window closes (by 2026-08-01):
jul = {"rule": "dropped", "amount": 0.25,
       "window_start": "2026-07-20", "by": "2026-08-01"}
print("fed_july_2026 window eval (today):", apply_rule(jul, f))

print("\nDONE.")
