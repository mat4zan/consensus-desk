#!/usr/bin/env python3
"""
Consensus Desk runner.

    python run.py collect --tier markets
    python run.py collect --tier all
    python run.py pool
    python run.py digest
    python run.py discover
    python run.py resolve --topic taiwan_blockade_2028 --outcome 0
    python run.py score
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))

from collectors import sources  # noqa: F401  (registers collectors)
from collectors.base import all_collectors, get_collector
from core.alerts import detect
from core.explain import Explainer
from core.pooling import Observation, pool
from core.scoring import compute_source_scores, effective_weights
from core.store import Store

ROOT = Path(__file__).parent


def load_cfg() -> dict:
    with open(ROOT / "config" / "settings.yml") as f:
        return yaml.safe_load(f)


def load_topics() -> list[dict]:
    with open(ROOT / "config" / "topics.yml") as f:
        return yaml.safe_load(f).get("topics", [])


def active_topics(topics: list[dict]) -> list[dict]:
    today = datetime.now(timezone.utc).date()
    out = []
    for t in topics:
        exp = t.get("expiry")
        if exp:
            exp_date = exp if hasattr(exp, "year") else datetime.fromisoformat(str(exp)).date()
            if exp_date < today:
                continue
        out.append(t)
    return out


# ---------------------------------------------------------------- collect

def cmd_collect(args, cfg, store):
    topics = active_topics(load_topics())
    tier = args.tier
    tiers_cfg = cfg.get("polling", {}).get("tiers", {})
    min_delta = cfg.get("polling", {}).get("min_delta_to_record", 0.0)
    backoff = cfg.get("polling", {}).get("failure_backoff_threshold", 3)

    registry = all_collectors()
    written = skipped = failed = 0

    for topic in topics:
        tid = topic["id"]
        for source_name, source_cfg in (topic.get("sources") or {}).items():
            cls = get_collector(source_name)
            if cls is None:
                continue
            if tier != "all" and cls.tier != tier:
                continue
            if store.is_backed_off(source_name, backoff):
                print(f"  [backoff] {source_name} — skipping")
                continue

            collector = cls(cfg, secrets=dict(os.environ))
            if isinstance(source_cfg, str):
                source_cfg = {"id": source_cfg}

            try:
                quote = collector.fetch(source_cfg)
            except Exception as e:
                failed += 1
                n = store.mark_failure(source_name, str(e))
                print(f"  [fail {n}] {tid}/{source_name}: {e}")
                continue

            if quote is None:
                skipped += 1
                continue
            if not collector.liquidity_ok(quote):
                print(f"  [thin] {tid}/{source_name} — below liquidity floor")
                skipped += 1
                continue

            wrote = store.record_observation(
                topic_id=tid,
                source=source_name,
                probability=quote.probability,
                raw_price=quote.raw_price,
                volume_usd=quote.volume_usd,
                n_traders=quote.n_traders,
                raw=quote.raw,
                min_delta=min_delta,
            )
            store.mark_success(source_name)
            if wrote:
                written += 1
                print(f"  {tid}/{source_name}: {quote.probability * 100:.1f}%")
            else:
                skipped += 1

    print(f"\ncollect[{tier}]: {written} written, {skipped} skipped, {failed} failed")


# ---------------------------------------------------------------- pool

def cmd_pool(args, cfg, store):
    topics = active_topics(load_topics())
    scores = compute_source_scores(store.scoring_rows(), cfg) if store.scoring_rows() else None
    weights = effective_weights(cfg, scores)
    explainer = Explainer(cfg)

    max_age = cfg["pooling"]["max_age_hours"]
    all_alerts, snapshot_topics = [], []

    for topic in topics:
        tid = topic["id"]
        rows = store.latest_by_source(tid)
        if not rows:
            continue

        obs = [
            Observation(
                source=r["source"],
                probability=r["probability"],
                timestamp=datetime.fromisoformat(r["ts"]),
                volume_usd=r["volume_usd"],
                n_traders=r["n_traders"],
            )
            for r in rows
        ]

        result = pool(obs, weights, cfg)
        if result.probability != result.probability:
            print(f"  [no data] {tid}")
            continue

        store.record_pooled(tid, result)

        alerts = detect(tid, topic["question"], result, store, cfg)
        for a in alerts:
            store.record_alert(a.topic_id, a.kind, a.detail)
            all_alerts.append(a)

        criteria_notes = {
            s: (c.get("criteria_note") or "").strip()
            for s, c in (topic.get("sources") or {}).items()
            if isinstance(c, dict) and c.get("criteria_note")
        }
        explanation = explainer.explain_disagreement(
            topic["question"], topic.get("resolution", ""), result, criteria_notes
        )

        history = [
            {"ts": h["ts"], "p": round(h["probability"] * 100, 2)}
            for h in store.pooled_history(tid, cfg["output"]["history_days_in_snapshot"])
        ]
        prior_24 = store.pooled_at_or_before(tid, 24)
        delta = (result.probability - prior_24) * 100 if prior_24 is not None else None

        snapshot_topics.append(
            {
                "id": tid,
                "question": topic["question"],
                "domain": topic.get("domain"),
                "probability": round(result.probability * 100, 1),
                "delta_24h_pp": round(delta, 1) if delta is not None else None,
                "spread_pp": result.spread_pp,
                "n_sources": result.n_sources,
                "contributions": result.contributions,
                "excluded": result.excluded,
                "explanation": explanation,
                "criteria_notes": criteria_notes,
                "history": history,
                "expiry": str(topic.get("expiry", "")),
            }
        )
        print(f"  {tid}: {result.probability * 100:.1f}% (spread {result.spread_pp:.0f}pp)")

    snapshot = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": cfg["pooling"]["method"],
        "extremize": cfg["pooling"]["extremize"],
        "weights": {k: round(v, 3) for k, v in weights.items()},
        "weight_strategy": cfg["weights"]["strategy"],
        "n_resolved": len({r["topic_id"] for r in store.scoring_rows()}),
        "alerts": [
            {"topic_id": a.topic_id, "kind": a.kind, "headline": a.headline, "detail": a.detail}
            for a in all_alerts
        ],
        "topics": sorted(snapshot_topics, key=lambda t: -abs(t.get("delta_24h_pp") or 0)),
    }

    out_path = ROOT / cfg["output"]["snapshot_path"]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(snapshot, f, indent=2)

    dash = ROOT / "dashboard" / "snapshot.json"
    dash.parent.mkdir(parents=True, exist_ok=True)
    with open(dash, "w") as f:
        json.dump(snapshot, f, indent=2)

    print(f"\npool: {len(snapshot_topics)} topics, {len(all_alerts)} alerts → {out_path}")


# ---------------------------------------------------------------- digest

def cmd_digest(args, cfg, store):
    snap_path = ROOT / cfg["output"]["snapshot_path"]
    if not snap_path.exists():
        print("No snapshot. Run `pool` first.")
        return
    snap = json.loads(snap_path.read_text())

    lines = ["# Consensus desk — daily digest", ""]
    lines.append(f"_{snap['generated_at'][:16]}Z · {len(snap['topics'])} topics_")
    lines.append("")

    if snap["alerts"]:
        lines.append("## Alerts")
        for a in snap["alerts"]:
            lines.append(f"- **{a['headline']}**")
        lines.append("")
    else:
        lines.append("No alerts. Nothing crossed threshold.")
        lines.append("")

    lines.append("## Board")
    lines.append("")
    lines.append("| Topic | Now | 24h | Spread | Sources |")
    lines.append("|---|---|---|---|---|")
    for t in snap["topics"]:
        d = t["delta_24h_pp"]
        arrow = "—" if d is None or abs(d) < 0.5 else ("▲" if d > 0 else "▼")
        dtxt = "—" if d is None else f"{arrow} {abs(d):.1f}"
        lines.append(
            f"| {t['question']} | {t['probability']}% | {dtxt} | "
            f"{t['spread_pp']:.0f}pp | {t['n_sources']} |"
        )

    pending = store.pending_discoveries(cfg["discovery"]["max_suggestions_per_digest"])
    if pending:
        lines += ["", "## Untracked, above volume threshold", ""]
        for p in pending:
            lines.append(f"- {p['question']}  _(${p['volume_usd']:,.0f}, {p['source']})_")

    out = ROOT / "data" / "digest.md"
    out.write_text("\n".join(lines))
    print("\n".join(lines))
    print(f"\n→ {out}")


# ---------------------------------------------------------------- discover

def cmd_discover(args, cfg, store):
    filters = cfg.get("discovery", {})
    if not filters.get("enabled"):
        print("Discovery disabled in settings.")
        return

    tracked = set()
    for t in load_topics():
        for s, c in (t.get("sources") or {}).items():
            cid = c.get("id") if isinstance(c, dict) else c
            if cid:
                tracked.add((s, cid))

    added = 0
    for name, cls in all_collectors().items():
        collector = cls(cfg, secrets=dict(os.environ))
        try:
            found = collector.discover(filters)
        except Exception as e:
            print(f"  [fail] discover/{name}: {e}")
            continue
        for item in found:
            if (name, item["external_id"]) in tracked:
                continue
            if store.queue_discovery(
                name, item["external_id"], item["question"], item["volume_usd"]
            ):
                added += 1

    print(f"discover: {added} new candidates queued")


# ---------------------------------------------------------------- resolve / score

def cmd_resolve(args, cfg, store):
    store.record_resolution(args.topic, args.outcome, args.note or "")
    print(f"Resolved {args.topic} = {args.outcome}")


def cmd_resolve_auto(args, cfg, store):
    """Layer 2: auto-resolve topics whose `oracle:` condition has closed."""
    from core.oracles import evaluate

    resolved = 0
    for topic in load_topics():
        oracle = topic.get("oracle")
        if not oracle:
            continue
        tid = topic["id"]
        if store.is_resolved(tid):
            continue
        try:
            result = evaluate(oracle)
        except Exception as e:
            print(f"  [oracle error] {tid}: {e}")
            continue
        if result is None:
            print(f"  [pending] {tid} — window open or data not yet available")
            continue
        outcome, note = result
        store.record_resolution(tid, outcome, f"auto[{oracle.get('source')}]: {note}")
        resolved += 1
        print(f"  [resolved] {tid} = {outcome}  ({note})")

    print(f"\nresolve-auto: {resolved} newly resolved")


def cmd_score(args, cfg, store):
    rows = store.scoring_rows()
    if not rows:
        print("No resolved topics yet. Weights remain at configured defaults.")
        return
    scores = compute_source_scores(rows, cfg)
    print(f"{'source':<16}{'n':>6}{'brier':>10}{'skill':>10}{'weight':>10}")
    for s in sorted(scores.values(), key=lambda x: -x.derived_weight):
        print(
            f"{s.source:<16}{s.n_resolved:>6}{s.brier:>10.4f}"
            f"{s.brier_skill:>10.4f}{s.derived_weight:>10.4f}"
        )
    min_r = cfg["weights"]["min_resolved"]
    n_topics = len({r["topic_id"] for r in rows})
    if n_topics < min_r:
        print(f"\n{n_topics}/{min_r} resolved topics — still using fixed weights.")


# ---------------------------------------------------------------- main

def main():
    p = argparse.ArgumentParser(prog="consensus-desk")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("collect")
    c.add_argument("--tier", default="all",
                   choices=["all", "markets", "forecasters", "bookmakers", "commentary"])
    c.set_defaults(fn=cmd_collect)

    sub.add_parser("pool").set_defaults(fn=cmd_pool)
    sub.add_parser("digest").set_defaults(fn=cmd_digest)
    sub.add_parser("discover").set_defaults(fn=cmd_discover)
    sub.add_parser("score").set_defaults(fn=cmd_score)
    sub.add_parser("resolve-auto").set_defaults(fn=cmd_resolve_auto)

    r = sub.add_parser("resolve")
    r.add_argument("--topic", required=True)
    r.add_argument("--outcome", type=int, required=True, choices=[0, 1])
    r.add_argument("--note", default="")
    r.set_defaults(fn=cmd_resolve)

    args = p.parse_args()
    cfg = load_cfg()
    store = Store(ROOT / "data" / "consensus.db")
    try:
        args.fn(args, cfg, store)
    finally:
        store.close()


if __name__ == "__main__":
    main()
