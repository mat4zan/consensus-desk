"""Oracle rule logic — pure, synthetic series, no network."""

from datetime import date

from core.oracles import apply_rule


def S(*pairs):
    return [(date.fromisoformat(d), v) for d, v in pairs]


FED = S(("2026-07-19", 4.50), ("2026-07-29", 4.25), ("2026-08-01", 4.25))


def test_dropped_yes():
    cfg = {"rule": "dropped", "amount": 0.25,
           "window_start": "2026-07-20", "by": "2026-08-01"}
    outcome, note = apply_rule(cfg, FED)
    assert outcome == 1
    assert "4.5" in note and "4.25" in note


def test_dropped_no_when_flat():
    flat = S(("2026-07-19", 4.50), ("2026-08-01", 4.50))
    cfg = {"rule": "dropped", "amount": 0.25,
           "window_start": "2026-07-20", "by": "2026-08-01"}
    assert apply_rule(cfg, flat)[0] == 0


def test_rose_yes():
    cfg = {"rule": "rose", "amount": 0.25,
           "window_start": "2026-07-20", "by": "2026-08-01"}
    up = S(("2026-07-19", 4.00), ("2026-08-01", 4.50))
    assert apply_rule(cfg, up)[0] == 1


def test_above_and_below():
    s = S(("2026-01-01", 180), ("2026-12-30", 210))
    assert apply_rule({"rule": "above", "threshold": 200, "by": "2026-12-31"}, s)[0] == 1
    assert apply_rule({"rule": "below", "threshold": 200, "by": "2026-12-31"}, s)[0] == 0


def test_crossed_above_uses_window_extreme():
    # ends below 200 but spiked above it mid-window -> crossed_above YES
    s = S(("2026-03-01", 150), ("2026-06-01", 205), ("2026-12-30", 190))
    cfg = {"rule": "crossed_above", "threshold": 200,
           "window_start": "2026-01-01", "by": "2026-12-31"}
    assert apply_rule(cfg, s)[0] == 1


def test_crossed_below():
    s = S(("2026-03-01", 250), ("2026-06-01", 190), ("2026-12-30", 240))
    cfg = {"rule": "crossed_below", "threshold": 200,
           "window_start": "2026-01-01", "by": "2026-12-31"}
    assert apply_rule(cfg, s)[0] == 1


def test_none_when_no_data():
    assert apply_rule({"rule": "above", "threshold": 1, "by": "2026-01-01"}, []) is None
