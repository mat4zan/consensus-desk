"""
Storage. Append-only by design — we never overwrite an observation,
because the history IS the product. A snapshot tells you what the crowd
thinks; a time series tells you when it changed.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id          TEXT    NOT NULL,
    source            TEXT    NOT NULL,
    ts                TEXT    NOT NULL,
    raw_price         REAL,
    probability       REAL    NOT NULL,
    volume_usd        REAL,
    n_traders         INTEGER,
    raw               TEXT
);
CREATE INDEX IF NOT EXISTS idx_obs_topic_ts ON observations(topic_id, ts);
CREATE INDEX IF NOT EXISTS idx_obs_source   ON observations(source, ts);

CREATE TABLE IF NOT EXISTS pooled (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id          TEXT    NOT NULL,
    ts                TEXT    NOT NULL,
    probability       REAL    NOT NULL,
    spread_pp         REAL,
    n_sources         INTEGER,
    contributions     TEXT,
    method            TEXT,
    extremize         REAL
);
CREATE INDEX IF NOT EXISTS idx_pooled_topic_ts ON pooled(topic_id, ts);

CREATE TABLE IF NOT EXISTS resolutions (
    topic_id          TEXT PRIMARY KEY,
    outcome           INTEGER NOT NULL,
    resolved_at       TEXT    NOT NULL,
    note              TEXT
);

CREATE TABLE IF NOT EXISTS alerts (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id          TEXT NOT NULL,
    kind              TEXT NOT NULL,
    ts                TEXT NOT NULL,
    detail            TEXT
);
CREATE INDEX IF NOT EXISTS idx_alerts_topic_ts ON alerts(topic_id, ts);

CREATE TABLE IF NOT EXISTS collector_health (
    source            TEXT PRIMARY KEY,
    last_success      TEXT,
    consecutive_fails INTEGER DEFAULT 0,
    last_error        TEXT
);

CREATE TABLE IF NOT EXISTS discovery_queue (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    source            TEXT,
    external_id       TEXT,
    question          TEXT,
    volume_usd        REAL,
    first_seen        TEXT,
    status            TEXT DEFAULT 'pending',
    UNIQUE(source, external_id)
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path: str | Path = "data/consensus.db"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ---------- observations ----------

    def last_observation(self, topic_id: str, source: str) -> sqlite3.Row | None:
        cur = self.conn.execute(
            "SELECT * FROM observations WHERE topic_id=? AND source=? "
            "ORDER BY ts DESC LIMIT 1",
            (topic_id, source),
        )
        return cur.fetchone()

    def record_observation(
        self,
        topic_id: str,
        source: str,
        probability: float,
        raw_price: float | None = None,
        volume_usd: float | None = None,
        n_traders: int | None = None,
        raw: dict | None = None,
        min_delta: float = 0.0,
    ) -> bool:
        """Returns True if written. Skips near-duplicates to keep the DB lean."""
        if min_delta > 0:
            prev = self.last_observation(topic_id, source)
            if prev is not None and abs(prev["probability"] - probability) < min_delta:
                return False

        self.conn.execute(
            "INSERT INTO observations "
            "(topic_id, source, ts, raw_price, probability, volume_usd, n_traders, raw) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                topic_id,
                source,
                _now(),
                raw_price,
                probability,
                volume_usd,
                n_traders,
                json.dumps(raw or {}),
            ),
        )
        self.conn.commit()
        return True

    def latest_by_source(self, topic_id: str) -> list[sqlite3.Row]:
        cur = self.conn.execute(
            """
            SELECT o.* FROM observations o
            JOIN (
                SELECT source, MAX(ts) AS mts
                FROM observations WHERE topic_id = ?
                GROUP BY source
            ) m ON o.source = m.source AND o.ts = m.mts
            WHERE o.topic_id = ?
            """,
            (topic_id, topic_id),
        )
        return cur.fetchall()

    # ---------- pooled ----------

    def record_pooled(self, topic_id: str, result) -> None:
        self.conn.execute(
            "INSERT INTO pooled "
            "(topic_id, ts, probability, spread_pp, n_sources, contributions, method, extremize) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                topic_id,
                _now(),
                result.probability,
                result.spread_pp,
                result.n_sources,
                json.dumps(result.contributions),
                result.method,
                result.extremize,
            ),
        )
        self.conn.commit()

    def pooled_history(self, topic_id: str, days: int = 90) -> list[sqlite3.Row]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        cur = self.conn.execute(
            "SELECT ts, probability, spread_pp, n_sources FROM pooled "
            "WHERE topic_id=? AND ts >= ? ORDER BY ts ASC",
            (topic_id, cutoff),
        )
        return cur.fetchall()

    def pooled_at_or_before(self, topic_id: str, hours_ago: float):
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
        cur = self.conn.execute(
            "SELECT probability FROM pooled WHERE topic_id=? AND ts <= ? "
            "ORDER BY ts DESC LIMIT 1",
            (topic_id, cutoff),
        )
        row = cur.fetchone()
        return row["probability"] if row else None

    # ---------- resolutions ----------

    def record_resolution(self, topic_id: str, outcome: int, note: str = "") -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO resolutions (topic_id, outcome, resolved_at, note) "
            "VALUES (?,?,?,?)",
            (topic_id, outcome, _now(), note),
        )
        self.conn.commit()

    def is_resolved(self, topic_id: str) -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM resolutions WHERE topic_id=? LIMIT 1", (topic_id,)
        )
        return cur.fetchone() is not None

    def scoring_rows(self) -> list[dict]:
        """
        Every source forecast on a resolved topic, with days-before-resolution.
        This is the input to Brier scoring.
        """
        cur = self.conn.execute(
            """
            SELECT o.source, o.topic_id, o.probability AS forecast,
                   r.outcome, o.ts, r.resolved_at
            FROM observations o
            JOIN resolutions r ON o.topic_id = r.topic_id
            WHERE o.ts <= r.resolved_at
            """
        )
        out = []
        for row in cur.fetchall():
            try:
                obs_ts = datetime.fromisoformat(row["ts"])
                res_ts = datetime.fromisoformat(row["resolved_at"])
                days = (res_ts - obs_ts).total_seconds() / 86400
            except Exception:
                days = 0.0
            out.append(
                {
                    "source": row["source"],
                    "topic_id": row["topic_id"],
                    "forecast": row["forecast"],
                    "outcome": row["outcome"],
                    "days_before_resolution": days,
                }
            )
        return out

    # ---------- alerts ----------

    def recent_alert(self, topic_id: str, kind: str, cooldown_hours: float) -> bool:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=cooldown_hours)).isoformat()
        cur = self.conn.execute(
            "SELECT 1 FROM alerts WHERE topic_id=? AND kind=? AND ts >= ? LIMIT 1",
            (topic_id, kind, cutoff),
        )
        return cur.fetchone() is not None

    def record_alert(self, topic_id: str, kind: str, detail: dict) -> None:
        self.conn.execute(
            "INSERT INTO alerts (topic_id, kind, ts, detail) VALUES (?,?,?,?)",
            (topic_id, kind, _now(), json.dumps(detail)),
        )
        self.conn.commit()

    # ---------- health ----------

    def mark_success(self, source: str) -> None:
        self.conn.execute(
            "INSERT INTO collector_health (source, last_success, consecutive_fails, last_error) "
            "VALUES (?,?,0,NULL) "
            "ON CONFLICT(source) DO UPDATE SET last_success=excluded.last_success, "
            "consecutive_fails=0, last_error=NULL",
            (source, _now()),
        )
        self.conn.commit()

    def mark_failure(self, source: str, error: str) -> int:
        self.conn.execute(
            "INSERT INTO collector_health (source, last_success, consecutive_fails, last_error) "
            "VALUES (?,NULL,1,?) "
            "ON CONFLICT(source) DO UPDATE SET "
            "consecutive_fails=collector_health.consecutive_fails+1, last_error=excluded.last_error",
            (source, error[:500]),
        )
        self.conn.commit()
        cur = self.conn.execute(
            "SELECT consecutive_fails FROM collector_health WHERE source=?", (source,)
        )
        row = cur.fetchone()
        return row["consecutive_fails"] if row else 0

    def is_backed_off(self, source: str, threshold: int) -> bool:
        cur = self.conn.execute(
            "SELECT consecutive_fails FROM collector_health WHERE source=?", (source,)
        )
        row = cur.fetchone()
        return bool(row and row["consecutive_fails"] >= threshold)

    # ---------- discovery ----------

    def queue_discovery(
        self, source: str, external_id: str, question: str, volume_usd: float
    ) -> bool:
        try:
            self.conn.execute(
                "INSERT INTO discovery_queue (source, external_id, question, volume_usd, first_seen) "
                "VALUES (?,?,?,?,?)",
                (source, external_id, question, volume_usd, _now()),
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def pending_discoveries(self, limit: int = 8) -> list[sqlite3.Row]:
        cur = self.conn.execute(
            "SELECT * FROM discovery_queue WHERE status='pending' "
            "ORDER BY volume_usd DESC LIMIT ?",
            (limit,),
        )
        return cur.fetchall()
