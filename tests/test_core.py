import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.pooling import (  # noqa: E402
    Observation,
    pool,
    strip_overround_proportional,
    strip_overround_shin,
)
from core.scoring import brier, brier_skill_score, compute_source_scores  # noqa: E402

CFG = yaml.safe_load(open(Path(__file__).parent.parent / "config" / "settings.yml"))
W = CFG["weights"]["fixed"]
NOW = datetime.now(timezone.utc)


def test_extremization_symmetric_about_half():
    a = pool([Observation("polymarket", 0.5, NOW), Observation("metaculus", 0.5, NOW)], W, CFG)
    assert abs(a.probability - 0.5) < 1e-6


def test_extremization_pushes_away_from_half():
    obs = [Observation("polymarket", 0.7, NOW), Observation("kalshi", 0.7, NOW)]
    r = pool(obs, W, CFG)
    assert r.probability > 0.7


def test_single_source_not_extremized():
    r = pool([Observation("polymarket", 0.15, NOW)], W, CFG)
    assert abs(r.probability - 0.15) < 0.005
    assert r.extremize == 1.0


def test_stale_source_excluded():
    obs = [
        Observation("polymarket", 0.2, NOW),
        Observation("metaculus", 0.1, NOW - timedelta(hours=100)),
    ]
    r = pool(obs, W, CFG)
    assert [c["source"] for c in r.contributions] == ["polymarket"]
    assert r.excluded[0]["reason"] == "stale"


def test_correlation_damping_reduces_cluster_weight():
    solo = pool([Observation("metaculus", 0.3, NOW), Observation("polymarket", 0.3, NOW)], W, CFG)
    m_solo = next(c["weight"] for c in solo.contributions if c["source"] == "metaculus")
    both = pool(
        [
            Observation("metaculus", 0.3, NOW),
            Observation("goodjudgment", 0.3, NOW),
            Observation("polymarket", 0.3, NOW),
        ],
        W,
        CFG,
    )
    m_both = next(c["weight"] for c in both.contributions if c["source"] == "metaculus")
    assert m_both < m_solo


def test_longshot_correction_shrinks_low_probabilities():
    r = pool([Observation("polymarket", 0.03, NOW), Observation("kalshi", 0.03, NOW)], W, CFG)
    assert r.contributions[0]["adjusted"] < 0.03


def test_longshot_leaves_mid_probabilities_alone():
    r = pool([Observation("polymarket", 0.4, NOW), Observation("kalshi", 0.4, NOW)], W, CFG)
    assert r.contributions[0]["adjusted"] == 0.4


def test_spread_reported():
    obs = [Observation("polymarket", 0.6, NOW), Observation("metaculus", 0.3, NOW)]
    assert pool(obs, W, CFG).spread_pp == 30.0


def test_no_observations_returns_nan():
    r = pool([], W, CFG)
    assert r.probability != r.probability


def test_out_of_range_excluded():
    r = pool([Observation("polymarket", 1.4, NOW), Observation("kalshi", 0.3, NOW)], W, CFG)
    assert any(e["reason"] == "out_of_range" for e in r.excluded)


def test_overround_sums_to_one():
    book = {"yes": 1 / 1.80, "no": 1 / 2.10}
    assert abs(sum(strip_overround_proportional(book).values()) - 1.0) < 1e-9
    assert abs(sum(strip_overround_shin(book).values()) - 1.0) < 1e-6


def test_shin_differs_from_proportional_on_skewed_book():
    book = {"long": 1 / 15.0, "short": 1 / 1.05}
    prop = strip_overround_proportional(book)
    shin = strip_overround_shin(book)
    assert abs(prop["long"] - shin["long"]) > 1e-4


def test_brier_perfect_is_zero():
    assert brier(1.0, 1) == 0.0
    assert brier(0.0, 0) == 0.0


def test_brier_coinflip_is_quarter():
    assert brier(0.5, 1) == 0.25


def test_skill_positive_when_better_than_reference():
    assert brier_skill_score(0.1, 0.25) > 0


def test_weights_stay_fixed_below_min_resolved():
    rows = [
        {"source": "polymarket", "topic_id": f"t{i}", "forecast": 0.9, "outcome": 1,
         "days_before_resolution": 40}
        for i in range(5)
    ]
    scores = compute_source_scores(rows, CFG)
    assert scores["polymarket"].derived_weight == CFG["weights"]["fixed"]["polymarket"]


def test_weights_move_above_min_resolved():
    rows = []
    for i in range(40):
        rows.append({"source": "good", "topic_id": f"t{i}", "forecast": 0.95,
                     "outcome": 1, "days_before_resolution": 40})
        rows.append({"source": "bad", "topic_id": f"t{i}", "forecast": 0.5,
                     "outcome": 1, "days_before_resolution": 40})
    scores = compute_source_scores(rows, CFG)
    assert scores["good"].brier < scores["bad"].brier
    assert scores["good"].derived_weight > scores["bad"].derived_weight
