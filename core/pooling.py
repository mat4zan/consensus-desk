"""
Probability aggregation.

The design rule here: this module never sees an LLM, never fetches anything,
and never decides which sources to include on grounds other than staleness.
It takes observations in and produces one number plus an audit trail out.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable


@dataclass
class Observation:
    """One source's view of one topic at one moment."""

    source: str
    probability: float
    timestamp: datetime
    volume_usd: float | None = None
    n_traders: int | None = None
    raw: dict = field(default_factory=dict)

    @property
    def age_hours(self) -> float:
        now = datetime.now(timezone.utc)
        ts = self.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (now - ts).total_seconds() / 3600.0


@dataclass
class PoolResult:
    probability: float
    contributions: list[dict]
    spread_pp: float
    excluded: list[dict]
    method: str
    extremize: float

    @property
    def n_sources(self) -> int:
        return len(self.contributions)


def _logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1 / (1 + z)
    z = math.exp(x)
    return z / (1 + z)


def apply_longshot_correction(p: float, cfg: dict, source: str) -> float:
    """
    Real-money venues overprice low-probability outcomes. Punters buy
    lottery tickets; the price reflects that demand, not the true rate.
    Shrink sub-threshold probabilities toward zero.
    """
    ls = cfg.get("bias_correction", {}).get("longshot", {})
    if not ls.get("enabled"):
        return p
    if source not in ls.get("applies_to", []):
        return p
    threshold = ls.get("threshold", 0.05)
    if p >= threshold:
        return p
    return p * ls.get("factor", 0.75)


def strip_overround_proportional(implied: dict[str, float]) -> dict[str, float]:
    """Cheap version. Assumes the margin is spread evenly. It is not."""
    total = sum(implied.values())
    if total <= 0:
        return implied
    return {k: v / total for k, v in implied.items()}


def strip_overround_shin(implied: dict[str, float], max_iter: int = 100) -> dict[str, float]:
    """
    Shin's method. Solves for z, the proportion of insider money, then
    backs out true probabilities. Handles longshot bias more honestly
    than proportional normalisation because it does not assume the
    bookmaker's margin is uniform across outcomes.
    """
    total = sum(implied.values())
    if total <= 1.0 or len(implied) < 2:
        return strip_overround_proportional(implied)

    keys = list(implied.keys())
    pi = [implied[k] for k in keys]

    z = 0.0
    for _ in range(max_iter):
        denom = 0.0
        vals = []
        for p in pi:
            disc = z**2 + 4 * (1 - z) * (p**2) / total
            v = (math.sqrt(max(disc, 0.0)) - z) / (2 * (1 - z)) if z < 1 else p / total
            vals.append(v)
            denom += v
        if denom <= 0:
            break
        new_z = z + 0.5 * (denom - 1.0)
        new_z = min(max(new_z, 0.0), 0.35)
        if abs(new_z - z) < 1e-9:
            z = new_z
            break
        z = new_z

    out, denom = {}, 0.0
    for k, p in zip(keys, pi):
        disc = z**2 + 4 * (1 - z) * (p**2) / total
        v = (math.sqrt(max(disc, 0.0)) - z) / (2 * (1 - z)) if z < 1 else p / total
        out[k] = v
        denom += v
    if denom > 0:
        out = {k: v / denom for k, v in out.items()}
    return out


def _correlation_scaled_weights(
    weights: dict[str, float], present: list[str], cfg: dict
) -> dict[str, float]:
    """
    Polymarket and Kalshi on the same event are not two independent
    opinions — they arbitrage against each other. Counting both at full
    weight double-counts one view. Scale each cluster's members by
    1 / n_present ** damping.
    """
    corr = cfg.get("correlation", {})
    damping = corr.get("damping", 0.6)
    clusters = corr.get("clusters", {})
    if damping <= 0 or not clusters:
        return weights

    scaled = dict(weights)
    for members in clusters.values():
        in_play = [s for s in members if s in present]
        if len(in_play) <= 1:
            continue
        factor = 1.0 / (len(in_play) ** damping)
        for s in in_play:
            scaled[s] = scaled.get(s, 0.0) * factor
    return scaled


def pool(
    observations: Iterable[Observation],
    weights: dict[str, float],
    cfg: dict,
) -> PoolResult:
    """
    Combine observations into one probability.

    Averaging probabilities directly produces systematic underconfidence,
    because individual forecasters hedge toward the middle and averaging
    preserves that hedge. Pooling in log-odds space and then extremizing
    corrects for it.
    """
    pcfg = cfg.get("pooling", {})
    method = pcfg.get("method", "logodds")
    extremize = pcfg.get("extremize", 1.2)
    max_age = pcfg.get("max_age_hours", 72)
    fresh_hours = pcfg.get("fresh_hours", 12)

    obs = list(observations)
    kept, excluded = [], []

    for o in obs:
        if o.age_hours > max_age:
            excluded.append(
                {"source": o.source, "reason": "stale", "age_hours": round(o.age_hours, 1)}
            )
            continue
        if not (0.0 <= o.probability <= 1.0):
            excluded.append(
                {"source": o.source, "reason": "out_of_range", "value": o.probability}
            )
            continue
        kept.append(o)

    if not kept:
        return PoolResult(
            probability=float("nan"),
            contributions=[],
            spread_pp=0.0,
            excluded=excluded,
            method=method,
            extremize=extremize,
        )

    present = [o.source for o in kept]
    eff_weights = _correlation_scaled_weights(weights, present, cfg)

    contributions, num, den = [], 0.0, 0.0
    for o in kept:
        p_adj = apply_longshot_correction(o.probability, cfg, o.source)
        w = eff_weights.get(o.source, 0.0)
        if w <= 0:
            excluded.append({"source": o.source, "reason": "zero_weight"})
            continue

        if method == "logodds":
            num += w * _logit(p_adj)
        elif method == "geometric":
            num += w * math.log(min(max(p_adj, 1e-6), 1 - 1e-6))
        else:  # linear
            num += w * p_adj
        den += w

        contributions.append(
            {
                "source": o.source,
                "probability": round(o.probability, 4),
                "adjusted": round(p_adj, 4),
                "weight": round(w, 4),
                "raw_weight": round(weights.get(o.source, 0.0), 4),
                "age_hours": round(o.age_hours, 1),
                "stale": o.age_hours > fresh_hours,
                "volume_usd": o.volume_usd,
            }
        )

    if den <= 0 or not contributions:
        return PoolResult(
            probability=float("nan"),
            contributions=[],
            spread_pp=0.0,
            excluded=excluded,
            method=method,
            extremize=extremize,
        )

    agg = num / den

    # Extremization corrects for the hedging that averaging introduces.
    # With a single source there is no averaging, so there is nothing to
    # correct — applying it anyway would just manufacture confidence.
    eff_extremize = extremize if len(contributions) > 1 else 1.0

    if method == "logodds":
        pooled = _sigmoid(agg * eff_extremize)
    elif method == "geometric":
        pooled = math.exp(agg)
        pooled = _sigmoid(_logit(pooled) * eff_extremize)
    else:
        pooled = _sigmoid(_logit(agg) * eff_extremize)

    floor = pcfg.get("floor", 0.005)
    ceiling = pcfg.get("ceiling", 0.995)
    pooled = min(max(pooled, floor), ceiling)

    probs = [c["probability"] for c in contributions]
    spread_pp = (max(probs) - min(probs)) * 100 if len(probs) > 1 else 0.0

    return PoolResult(
        probability=round(pooled, 4),
        contributions=sorted(contributions, key=lambda c: -c["weight"]),
        spread_pp=round(spread_pp, 1),
        excluded=excluded,
        method=method,
        extremize=eff_extremize,
    )
