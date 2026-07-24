#!/usr/bin/env python3
"""
Turn a free-text topic request into a wired, verified topic.

Pipeline (this is the "background worker" behind the dashboard's Add-a-topic form):
  1. search Polymarket / Manifold / PredictIt for markets matching the request
  2. ask Claude to pick the single best market on each venue and draft the topic
     (it may only choose ids that appear in the candidate lists)
  3. verify each chosen id actually returns a live price (via the real collectors)
  4. append the topic to config/topics.yml

The request text arrives in REQUEST_TEXT; ANTHROPIC_API_KEY must be set.
Nothing is invented: ids come from live search results and are re-verified, so a
hallucinated or dead market cannot enter the board.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from collectors import sources  # noqa: F401  registers collectors
from collectors.base import get_collector

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
T = 25
MODEL = os.environ.get("TOPIC_MODEL", "claude-sonnet-5")
API_URL = "https://api.anthropic.com/v1/messages"

STOP = {"will", "the", "any", "before", "after", "by", "in", "on", "of", "to",
        "a", "an", "and", "or", "be", "is", "are", "at", "for", "this", "that",
        "2025", "2026", "2027", "reach", "above", "below", "topic", "add"}


def keywords(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9$]+", text.lower())
    return [w for w in words if len(w) > 2 and w not in STOP]


# --------------------------------------------------------------- venue search

def search_polymarket(kws: list[str], limit: int = 12) -> list[dict]:
    markets = []
    for off in range(0, 600, 100):
        try:
            r = requests.get("https://gamma-api.polymarket.com/markets",
                             params={"active": "true", "closed": "false", "limit": 100,
                                     "offset": off, "order": "volumeNum", "ascending": "false"},
                             headers=UA, timeout=T)
            r.raise_for_status()
            b = r.json()
        except Exception:
            break
        if not b:
            break
        markets += b
    out = []
    for m in markets:
        q = (m.get("question") or "").lower()
        hits = sum(1 for k in kws if k in q)
        if hits:
            out.append({"venue": "polymarket", "id": m.get("slug"),
                        "question": m.get("question"),
                        "prob": (m.get("outcomePrices") or [None])[0],
                        "volume": m.get("volumeNum"), "_hits": hits})
    out.sort(key=lambda x: (x["_hits"], x.get("volume") or 0), reverse=True)
    return out[:limit]


def search_manifold(request: str, limit: int = 8) -> list[dict]:
    try:
        r = requests.get("https://api.manifold.markets/v0/search-markets",
                         params={"term": request, "filter": "open",
                                 "contractType": "BINARY", "sort": "score", "limit": limit},
                         headers=UA, timeout=T)
        r.raise_for_status()
    except Exception:
        return []
    return [{"venue": "manifold", "id": m.get("slug"), "question": m.get("question"),
             "prob": m.get("probability"), "bettors": m.get("uniqueBettorCount")}
            for m in r.json()]


def search_predictit(kws: list[str], limit: int = 10) -> list[dict]:
    try:
        r = requests.get("https://www.predictit.org/api/marketdata/all/", headers=UA, timeout=T)
        r.raise_for_status()
        markets = r.json().get("markets", [])
    except Exception:
        return []
    out = []
    for mk in markets:
        name = (mk.get("name") or "") + " " + (mk.get("shortName") or "")
        hits = sum(1 for k in kws if k in name.lower())
        if hits:
            out.append({"venue": "predictit", "id": mk.get("id"),
                        "question": mk.get("shortName"),
                        "contracts": [{"name": c.get("name"), "price": c.get("lastTradePrice")}
                                      for c in mk.get("contracts", [])][:8],
                        "_hits": hits})
    out.sort(key=lambda x: x["_hits"], reverse=True)
    return out[:limit]


# --------------------------------------------------------------- Claude

def choose_topic(request: str, candidates: dict) -> dict | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        print("No ANTHROPIC_API_KEY", file=sys.stderr)
        return None

    system = (
        "You wire a forecasting request into a tracked topic for a probability "
        "aggregator. You are given a user's request and candidate prediction markets "
        "from several venues. Choose the SINGLE best-matching market on each venue "
        "whose resolution criteria fit the request; omit a venue if nothing fits. "
        "You may ONLY use ids that appear verbatim in the candidates. Do not invent ids. "
        "Also draft the canonical topic. If (and only if) the outcome is objectively "
        "resolvable from public market/economic data, add an oracle: use source 'yahoo' "
        "with a `symbol` (e.g. BTC-USD, ^GSPC, ^TNX) for prices, or source 'fred' with a "
        "`series` for macro; rules: above|below|crossed_above|crossed_below|dropped|rose. "
        "Otherwise omit the oracle. Respond with ONLY a JSON object, no markdown fences:\n"
        '{"ok": bool, "reason": str, "topic": {"id": snake_case_str, "question": str, '
        '"domain": "geopolitics|macro|elections|crypto|tech|other", "resolution": str, '
        '"expiry": "YYYY-MM-DD", "sources": {"<venue>": {"id": <id>, "outcome": <predictit '
        'contract name if predictit>}}, "oracle": {optional}}}. '
        "Set ok=false with a reason if no candidate genuinely matches."
    )
    user = (
        f"Request: {request}\n\nToday: {date.today().isoformat()}\n\n"
        f"Candidates JSON:\n{json.dumps(candidates, indent=1)[:12000]}"
    )
    try:
        r = requests.post(API_URL,
                          headers={"content-type": "application/json", "x-api-key": key,
                                   "anthropic-version": "2023-06-01"},
                          json={"model": MODEL, "max_tokens": 1200,
                                "system": system,
                                "messages": [{"role": "user", "content": user}]},
                          timeout=90)
        r.raise_for_status()
        blocks = r.json().get("content", [])
        raw = "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(raw)
    except Exception as e:
        print(f"Claude call failed: {e}", file=sys.stderr)
        return None


# --------------------------------------------------------------- verify + write

def verify_source(venue: str, scfg: dict) -> bool:
    cls = get_collector(venue)
    if cls is None:
        return False
    try:
        cfg = yaml.safe_load((ROOT / "config" / "settings.yml").read_text())
        quote = cls(cfg, secrets=dict(os.environ)).fetch(scfg)
        return quote is not None and quote.probability is not None
    except Exception as e:
        print(f"verify {venue} failed: {e}", file=sys.stderr)
        return False


def existing_ids() -> set:
    data = yaml.safe_load((ROOT / "config" / "topics.yml").read_text()) or {}
    return {t.get("id") for t in data.get("topics", [])}


def yaml_block(topic: dict) -> str:
    """Render one topic as a YAML list item, appended to preserve the file's comments."""
    lines = [f"  - id: {topic['id']}",
             f"    question: {json.dumps(topic['question'])}",
             f"    domain: {topic.get('domain', 'other')}",
             f"    resolution: >",
             f"      {topic['resolution'].strip()}",
             f"    expiry: {topic['expiry']}",
             f"    review: {topic.get('review', topic['expiry'])}",
             f"    # Auto-added from a topic request on {date.today().isoformat()}."]
    orc = topic.get("oracle")
    if orc:
        lines.append("    oracle:")
        for k, v in orc.items():
            lines.append(f"      {k}: {json.dumps(v) if isinstance(v, str) else v}")
    lines.append("    sources:")
    for venue, scfg in topic["sources"].items():
        lines.append(f"      {venue}:")
        lines.append(f"        id: {json.dumps(str(scfg['id']))}")
        if scfg.get("outcome"):
            lines.append(f"        outcome: {json.dumps(scfg['outcome'])}")
    return "\n".join(lines) + "\n"


def main() -> int:
    request = (os.environ.get("REQUEST_TEXT") or "").strip()
    if not request:
        print("::error::empty request")
        return 1
    print(f"Request: {request}")

    kws = keywords(request)
    candidates = {
        "polymarket": search_polymarket(kws),
        "manifold": search_manifold(request),
        "predictit": search_predictit(kws),
    }
    n = sum(len(v) for v in candidates.values())
    print(f"Found {n} candidate markets "
          f"(pm={len(candidates['polymarket'])} mf={len(candidates['manifold'])} "
          f"pi={len(candidates['predictit'])})")
    if n == 0:
        print("::warning::no candidate markets matched")
        return 2

    result = choose_topic(request, candidates)
    if not result or not result.get("ok"):
        print(f"::warning::no topic wired: {result.get('reason') if result else 'model error'}")
        return 2
    topic = result["topic"]
    print(f"Draft topic: {topic.get('id')} — {topic.get('question')}")

    if topic["id"] in existing_ids():
        print(f"::warning::topic id {topic['id']} already exists")
        return 2

    verified = {}
    for venue, scfg in (topic.get("sources") or {}).items():
        ok = verify_source(venue, scfg)
        print(f"  verify {venue} {scfg.get('id')}: {'OK' if ok else 'FAIL'}")
        if ok:
            verified[venue] = scfg
    if not verified:
        print("::warning::no source verified with a live price")
        return 2
    topic["sources"] = verified

    path = ROOT / "config" / "topics.yml"
    path.write_text(path.read_text().rstrip() + "\n\n" + yaml_block(topic))
    print(f"::notice::Added topic '{topic['id']}' with sources: {', '.join(verified)}")
    print("ADDED_TOPIC_ID=" + topic["id"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
