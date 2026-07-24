#!/usr/bin/env python3
"""
No-LLM topic wiring.

Takes an explicitly chosen market (the user picked it in the dashboard's
"add a topic" box, which opened a GitHub issue carrying the choice) and wires
it as a tracked topic. No model, no matching — the market id is already decided;
this only fetches its metadata, verifies it returns a live price, and appends a
topic to config/topics.yml. Reads the issue body from ISSUE_BODY.
"""

from __future__ import annotations

import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from request_topic import T, UA, existing_ids, verify_source, yaml_block


def parse_issue(body: str) -> dict:
    fields = {}
    for line in body.splitlines():
        m = re.match(r"^\s*([a-zA-Z_]+):\s*(.+?)\s*$", line)
        if m and m.group(1).lower() in ("venue", "id", "question"):
            fields[m.group(1).lower()] = m.group(2)
    return fields


def slug_id(question: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", question.lower()).strip("_")
    return (s[:48].rstrip("_")) or "topic"


def main() -> int:
    fields = parse_issue(os.environ.get("ISSUE_BODY", ""))
    venue = (fields.get("venue") or "").strip().lower()
    mid = (fields.get("id") or "").strip()
    if venue != "manifold" or not mid:
        print("::warning::no usable market in request (expected a Manifold pick)")
        return 2

    try:
        m = requests.get(f"https://api.manifold.markets/v0/slug/{mid}",
                         headers=UA, timeout=T).json()
    except Exception as e:
        print(f"::warning::could not fetch market: {e}")
        return 2

    question = (m.get("question") or fields.get("question") or mid).strip()
    tid = slug_id(question)
    if tid in existing_ids():
        print(f"::notice::topic '{tid}' already tracked — nothing to do")
        print("ALREADY_EXISTS=" + tid)
        return 0

    close = m.get("closeTime")
    exp = (datetime.fromtimestamp(close / 1000, tz=timezone.utc).date()
           if close else date.today() + timedelta(days=365))
    if exp <= date.today():
        exp = date.today() + timedelta(days=365)

    desc = " ".join((m.get("textDescription") or "").split())[:360]
    resolution = desc or f"Resolves per the linked Manifold market: {question}"

    topic = {"id": tid, "question": question, "domain": "other",
             "resolution": resolution, "expiry": exp.isoformat(),
             "sources": {"manifold": {"id": mid}}}

    if not verify_source("manifold", {"id": mid}):
        print("::warning::market did not return a live price; not adding")
        return 2

    path = ROOT / "config" / "topics.yml"
    path.write_text(path.read_text().rstrip() + "\n\n" + yaml_block(topic))
    print(f"::notice::Added topic '{tid}' from Manifold market {mid}")
    print("ADDED_TOPIC_ID=" + tid)
    print("ADDED_QUESTION=" + question)
    return 0


if __name__ == "__main__":
    sys.exit(main())
