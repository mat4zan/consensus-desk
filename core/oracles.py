"""
Resolution oracles (Layer 2).

Auto-resolve topics from ground-truth data instead of a human running
`resolve` by hand. Two sources, both public and key-free:

  fred  — macro time series (https://fred.stlouisfed.org/graph/fredgraph.csv)
  yahoo — market prices     (https://query1.finance.yahoo.com/v8/finance/chart)

An oracle turns a topic's *quantitative* resolution criterion into a 0/1
outcome. It never produces or touches a probability — it only decides the
YES/NO that closes a question, which is what feeds Brier scoring.

Config lives on a topic as an `oracle:` block, e.g.

  oracle:
    source: fred
    series: DFEDTARU        # FRED series id  (yahoo uses `symbol:` instead)
    rule: dropped           # above|below|crossed_above|crossed_below|dropped|rose
    amount: 0.25            # for dropped/rose
    threshold: 200          # for above/below/crossed_*
    window_start: 2026-07-20
    by: 2026-08-01          # do not resolve before this date

The pipeline stays dumb: adding an oracle is a config block, not code.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, timezone

import requests

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
}
TIMEOUT = 25

Series = list[tuple[date, float]]


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _to_date(v) -> date:
    return v if isinstance(v, date) else datetime.fromisoformat(str(v)).date()


# --------------------------------------------------------------- fetchers

def fred_series(series_id: str) -> Series:
    """Daily series from FRED's public CSV export. No API key required."""
    r = requests.get(
        "https://fred.stlouisfed.org/graph/fredgraph.csv",
        params={"id": series_id}, headers=UA, timeout=TIMEOUT,
    )
    r.raise_for_status()
    out: Series = []
    reader = csv.reader(io.StringIO(r.text))
    next(reader, None)  # header
    for row in reader:
        if len(row) < 2:
            continue
        try:
            out.append((_to_date(row[0]), float(row[1])))
        except ValueError:
            continue  # FRED writes "." for missing observations
    return out


def yahoo_series(symbol: str) -> Series:
    """Daily closes from Yahoo's public chart endpoint. No API key required."""
    r = requests.get(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
        params={"range": "2y", "interval": "1d"}, headers=UA, timeout=TIMEOUT,
    )
    r.raise_for_status()
    result = (r.json().get("chart", {}).get("result") or [None])[0]
    if not result:
        return []
    stamps = result.get("timestamp") or []
    closes = (result.get("indicators", {}).get("quote") or [{}])[0].get("close") or []
    out: Series = []
    for t, c in zip(stamps, closes):
        if c is None:
            continue
        out.append((datetime.fromtimestamp(t, tz=timezone.utc).date(), float(c)))
    return out


def fetch_series(cfg: dict) -> Series:
    src = cfg.get("source")
    if src == "fred":
        return fred_series(cfg["series"])
    if src == "yahoo":
        return yahoo_series(cfg["symbol"])
    raise ValueError(f"unknown oracle source {src!r}")


# --------------------------------------------------------------- rule logic

def _value_asof(series: Series, d: date) -> float | None:
    """Most recent value on or before `d`."""
    val = None
    for sd, sv in series:
        if sd <= d:
            val = sv
        else:
            break
    return val


def _extreme_between(series: Series, start: date, end: date, want_max: bool):
    vals = [sv for sd, sv in series if start <= sd <= end]
    if not vals:
        return None
    return max(vals) if want_max else min(vals)


def apply_rule(cfg: dict, series: Series) -> tuple[int, str] | None:
    """
    Pure rule evaluation (no network). Returns (outcome, note) or None when
    the data needed is not present. Kept separate from fetching so the logic
    is unit-testable with synthetic series.
    """
    if not series:
        return None
    rule = cfg["rule"]
    by = _to_date(cfg["by"])
    ws = _to_date(cfg["window_start"]) if cfg.get("window_start") else series[0][0]

    if rule in ("above", "below"):
        v = _value_asof(series, by)
        if v is None:
            return None
        thr = float(cfg["threshold"])
        yes = v > thr if rule == "above" else v < thr
        return (int(yes), f"{rule} {thr}: value={v} as of {by}")

    if rule in ("crossed_above", "crossed_below"):
        thr = float(cfg["threshold"])
        ext = _extreme_between(series, ws, by, want_max=(rule == "crossed_above"))
        if ext is None:
            return None
        yes = ext > thr if rule == "crossed_above" else ext < thr
        return (int(yes), f"{rule} {thr}: extreme={ext} in [{ws}..{by}]")

    if rule in ("dropped", "rose"):
        amt = float(cfg["amount"])
        v0 = _value_asof(series, ws)
        v1 = _value_asof(series, by)
        if v0 is None or v1 is None:
            return None
        change = v1 - v0
        yes = (change <= -amt) if rule == "dropped" else (change >= amt)
        return (int(yes), f"{rule} {amt}: {v0}->{v1} (delta {change:+.3f})")

    raise ValueError(f"unknown oracle rule {rule!r}")


def evaluate(cfg: dict) -> tuple[int, str] | None:
    """
    Resolve a topic's oracle *now*, or return None if it is not yet decidable.
    Never resolves before `by` — the window must have closed.
    """
    if _today() < _to_date(cfg["by"]):
        return None
    return apply_rule(cfg, fetch_series(cfg))
