import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.store import Store  # noqa: E402


def _store():
    d = tempfile.mkdtemp()
    return Store(Path(d) / "t.db")


def test_backoff_trips_after_threshold():
    s = _store()
    for _ in range(3):
        s.mark_failure("polymarket", "boom")
    assert s.is_backed_off("polymarket", threshold=3) is True
    s.close()


def test_success_resets_backoff():
    s = _store()
    for _ in range(3):
        s.mark_failure("polymarket", "boom")
    s.mark_success("polymarket")
    assert s.is_backed_off("polymarket", threshold=3) is False
    s.close()


def test_backoff_self_heals_after_retry_window():
    """A venue that trips backoff must get retried eventually, not stay
    silenced forever — this is the bug: without the retry window, a fetch
    is never attempted again so mark_success can never fire to clear it."""
    s = _store()
    for _ in range(3):
        s.mark_failure("polymarket", "boom")
    assert s.is_backed_off("polymarket", threshold=3, retry_after_hours=6) is True

    # Simulate 7 hours having passed since the last failure.
    old = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
    s.conn.execute("UPDATE collector_health SET last_failure=? WHERE source=?",
                    (old, "polymarket"))
    s.conn.commit()

    assert s.is_backed_off("polymarket", threshold=3, retry_after_hours=6) is False
    s.close()


def test_still_backed_off_within_retry_window():
    s = _store()
    for _ in range(3):
        s.mark_failure("polymarket", "boom")
    recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    s.conn.execute("UPDATE collector_health SET last_failure=? WHERE source=?",
                    (recent, "polymarket"))
    s.conn.commit()
    assert s.is_backed_off("polymarket", threshold=3, retry_after_hours=6) is True
    s.close()
