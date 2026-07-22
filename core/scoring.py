"""
Source calibration.

Weights should be earned. A source that has been right, early, and
confident deserves more of the pool than one that drifts along behind
the consensus. Brier score measures exactly that, and it is proper —
you cannot improve it by hedging.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class SourceScore:
    source: str
    n_resolved: int
    brier: float
    brier_skill: float
    lead_bonus: float
    derived_weight: float


def brier(forecast: float, outcome: int) -> float:
    """Squared error. Lower is better. 0.25 is what you get from always saying 50%."""
    return (forecast - outcome) ** 2


def brier_skill_score(source_brier: float, reference_brier: float) -> float:
    """
    Skill relative to a reference. Positive means better than reference,
    zero means no better, negative means worse. Reference is normally the
    pooled forecast, so this answers: does this source add anything the
    pool does not already have?
    """
    if reference_brier <= 0:
        return 0.0
    return 1.0 - (source_brier / reference_brier)


def compute_source_scores(
    resolutions: list[dict],
    cfg: dict,
    lead_window_days: int = 30,
) -> dict[str, SourceScore]:
    """
    resolutions: list of dicts with keys
        source, topic_id, forecast, outcome (0/1), days_before_resolution

    The lead bonus rewards sources that were right *early*. A source that
    matched the consensus on the last day before resolution has told you
    nothing. One that was right 30 days out has.
    """
    by_source: dict[str, list[dict]] = {}
    for r in resolutions:
        by_source.setdefault(r["source"], []).append(r)

    all_briers = [brier(r["forecast"], r["outcome"]) for r in resolutions]
    reference = sum(all_briers) / len(all_briers) if all_briers else 0.25

    wcfg = cfg.get("weights", {})
    min_resolved = wcfg.get("min_resolved", 30)
    blend = wcfg.get("brier_blend", 0.7)
    fixed = wcfg.get("fixed", {})
    strategy = wcfg.get("strategy", "hybrid")

    scores: dict[str, SourceScore] = {}

    for source, rows in by_source.items():
        n = len(rows)
        b = sum(brier(r["forecast"], r["outcome"]) for r in rows) / n
        bss = brier_skill_score(b, reference)

        early = [r for r in rows if r.get("days_before_resolution", 0) >= lead_window_days]
        if early:
            eb = sum(brier(r["forecast"], r["outcome"]) for r in early) / len(early)
            lead_bonus = max(0.0, brier_skill_score(eb, reference)) * 0.25
        else:
            lead_bonus = 0.0

        base = fixed.get(source, 0.15)

        if strategy == "fixed" or n < min_resolved:
            derived = base
        else:
            # Map skill onto a weight multiplier. Deliberately conservative:
            # a source cannot earn more than ~2x or fall below ~0.3x its base
            # on the strength of Brier alone.
            mult = math.exp(1.4 * (bss + lead_bonus))
            mult = min(max(mult, 0.3), 2.0)
            earned = base * mult
            if strategy == "hybrid":
                derived = base * (1 - blend) + earned * blend
            else:
                derived = earned

        scores[source] = SourceScore(
            source=source,
            n_resolved=n,
            brier=round(b, 4),
            brier_skill=round(bss, 4),
            lead_bonus=round(lead_bonus, 4),
            derived_weight=round(derived, 4),
        )

    return scores


def effective_weights(cfg: dict, scores: dict[str, SourceScore] | None) -> dict[str, float]:
    """Current weights: derived where we have enough history, fixed otherwise."""
    fixed = dict(cfg.get("weights", {}).get("fixed", {}))
    if not scores:
        return fixed
    out = dict(fixed)
    for source, s in scores.items():
        out[source] = s.derived_weight
    return out
