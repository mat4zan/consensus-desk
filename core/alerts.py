"""
Alert detection.

The alerting logic matters more than the collection. Without it you have
built a dashboard you check twice and abandon. Each alert kind answers a
different question, so they are kept separate rather than collapsed into
a single severity score.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Alert:
    topic_id: str
    kind: str
    headline: str
    detail: dict

    @property
    def priority(self) -> int:
        return {"move_24h": 0, "move_7d": 1, "spread": 2, "volume_divergence": 3}.get(
            self.kind, 9
        )


def detect(topic_id: str, question: str, result, store, cfg: dict) -> list[Alert]:
    acfg = cfg.get("alerts", {})
    cooldown = acfg.get("cooldown_hours", 24)
    out: list[Alert] = []

    current = result.probability
    if current != current:  # NaN
        return out

    # --- movement ---
    # A 7-day alert on a topic that already fired at 24h is redundant: the
    # week's move IS the last day's move. Only report the longer window when
    # it reveals a slow drift the daily check missed.
    fired_24h = False
    for window_h, key, thresh_key in (
        (24, "move_24h", "move_24h_pp"),
        (168, "move_7d", "move_7d_pp"),
    ):
        if key == "move_7d" and fired_24h:
            continue
        prior = store.pooled_at_or_before(topic_id, window_h)
        if prior is None:
            continue
        delta_pp = (current - prior) * 100
        thresh = acfg.get(thresh_key, 5.0)
        if abs(delta_pp) < thresh:
            continue
        if store.recent_alert(topic_id, key, cooldown):
            continue
        if key == "move_24h":
            fired_24h = True
        direction = "up" if delta_pp > 0 else "down"
        out.append(
            Alert(
                topic_id=topic_id,
                kind=key,
                headline=f"{question} moved {direction} {abs(delta_pp):.1f}pp",
                detail={
                    "from": round(prior * 100, 1),
                    "to": round(current * 100, 1),
                    "delta_pp": round(delta_pp, 1),
                    "window_hours": window_h,
                },
            )
        )

    # --- disagreement ---
    spread_thresh = acfg.get("source_spread_pp", 20.0)
    if result.spread_pp >= spread_thresh and not store.recent_alert(
        topic_id, "spread", cooldown
    ):
        hi = max(result.contributions, key=lambda c: c["probability"])
        lo = min(result.contributions, key=lambda c: c["probability"])
        out.append(
            Alert(
                topic_id=topic_id,
                kind="spread",
                headline=f"{question}: sources disagree by {result.spread_pp:.0f}pp",
                detail={
                    "spread_pp": result.spread_pp,
                    "highest": {"source": hi["source"], "p": round(hi["probability"] * 100, 1)},
                    "lowest": {"source": lo["source"], "p": round(lo["probability"] * 100, 1)},
                },
            )
        )

    # --- volume moved, price did not ---
    mult = acfg.get("volume_spike_multiple", 3.0)
    for c in result.contributions:
        vol = c.get("volume_usd")
        if not vol:
            continue
        hist = store.pooled_history(topic_id, days=7)
        if len(hist) < 3:
            continue
        recent_move = abs(current - hist[0]["probability"]) * 100
        if recent_move > 2.0:
            continue  # price did move; not the pattern we are looking for
        prev = store.last_observation(topic_id, c["source"])
        if prev is None:
            continue
        prev_vol = prev["volume_usd"]
        if not prev_vol or prev_vol <= 0:
            continue
        if vol / prev_vol < mult:
            continue
        if store.recent_alert(topic_id, "volume_divergence", cooldown):
            continue
        out.append(
            Alert(
                topic_id=topic_id,
                kind="volume_divergence",
                headline=f"{question}: volume up {vol / prev_vol:.1f}x, price flat",
                detail={
                    "source": c["source"],
                    "volume_now": vol,
                    "volume_prev": prev_vol,
                    "price_move_pp": round(recent_move, 2),
                },
            )
        )
        break

    return sorted(out, key=lambda a: a.priority)
