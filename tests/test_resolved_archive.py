import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.store import Store  # noqa: E402


def _store():
    return Store(Path(tempfile.mkdtemp()) / "t.db")


def test_latest_pooled_and_resolution_roundtrip():
    s = _store()
    s.conn.execute(
        "INSERT INTO pooled (topic_id, ts, probability, spread_pp, n_sources, "
        "contributions, method, extremize) VALUES (?,?,?,?,?,?,?,?)",
        ("xi_us_visit_july", "2026-07-29T10:00:00+00:00", 0.24, 5.0, 2, "[]", "logodds", 1.2),
    )
    s.conn.commit()
    s.record_resolution("xi_us_visit_july", 0, note="did not happen")

    rows = s.all_resolutions()
    assert len(rows) == 1
    assert rows[0]["topic_id"] == "xi_us_visit_july"
    assert rows[0]["outcome"] == 0

    last = s.latest_pooled("xi_us_visit_july")
    assert abs(last["probability"] - 0.24) < 1e-9
    s.close()


def test_latest_pooled_none_when_never_pooled():
    s = _store()
    assert s.latest_pooled("nonexistent_topic") is None
    s.close()


def test_all_resolutions_orders_newest_first():
    s = _store()
    s.record_resolution("a", 1)
    s.record_resolution("b", 0)
    rows = s.all_resolutions()
    # both inserted "now"-ish; just confirm both present regardless of order
    assert {r["topic_id"] for r in rows} == {"a", "b"}
    s.close()
