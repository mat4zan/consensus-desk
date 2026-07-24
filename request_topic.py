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


def normalize_nums(text: str) -> str:
    """
    Make money/number mentions comparable across venues: "$150,000", "150k",
    "1.5m" all become plain digits. Prediction markets phrase the same threshold
    every which way, so matching fails without this.
    """
    t = text.lower().replace(",", "")
    t = re.sub(r"\$?(\d+(?:\.\d+)?)\s*k\b", lambda m: str(int(float(m.group(1)) * 1_000)), t)
    t = re.sub(r"\$?(\d+(?:\.\d+)?)\s*m\b", lambda m: str(int(float(m.group(1)) * 1_000_000)), t)
    return t.replace("$", " ")


def keywords(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", normalize_nums(text))
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
        q = normalize_nums(m.get("question") or "")
        hits = sum(1 for k in kws if k in q)
        if hits:
            out.append({"venue": "polymarket", "id": m.get("slug"),
                        "question": m.get("question"),
                        "prob": (m.get("outcomePrices") or [None])[0],
                        "volume": m.get("volumeNum"), "_hits": hits})
    out.sort(key=lambda x: (x["_hits"], x.get("volume") or 0), reverse=True)
    return out[:limit]


def _manifold_query(term: str, limit: int) -> list:
    try:
        r = requests.get("https://api.manifold.markets/v0/search-markets",
                         params={"term": term, "filter": "open",
                                 "contractType": "BINARY", "sort": "liquidity", "limit": limit},
                         headers=UA, timeout=T)
        r.raise_for_status()
        return r.json()
    except Exception:
        return []


def search_manifold(kws: list[str], limit: int = 8) -> list[dict]:
    # Manifold's fulltext is finicky: try the full keyword query, then fall back
    # to the most salient single keyword so we don't miss on phrasing.
    terms = [" ".join(kws)]
    if kws:
        terms.append(max(kws, key=len))
    seen = {}
    for term in terms:
        for m in _manifold_query(term, limit):
            slug = m.get("slug")
            if slug and slug not in seen:
                seen[slug] = {"venue": "manifold", "id": slug, "question": m.get("question"),
                              "prob": m.get("probability"), "bettors": m.get("uniqueBettorCount")}
        if len(seen) >= 3:
            break
    return list(seen.values())[:limit]


def search_predictit(kws: list[str], limit: int = 10) -> list[dict]:
    try:
        r = requests.get("https://www.predictit.org/api/marketdata/all/", headers=UA, timeout=T)
        r.raise_for_status()
        markets = r.json().get("markets", [])
    except Exception:
        return []
    out = []
    for mk in markets:
        name = normalize_nums((mk.get("name") or "") + " " + (mk.get("shortName") or ""))
        hits = sum(1 for k in kws if k in name)
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
        "Also draft the canonical topic. Add an `oracle` ONLY if the outcome is "
        "objectively resolvable from public price/economic data (crypto, indices, yields, "
        "rates) — NOT for elections, wars, approvals, or human events. Oracle schema, use "
        "these EXACT keys:\n"
        "  source: 'yahoo' with `symbol` (BTC-USD, ETH-USD, ^GSPC, ^TNX) OR "
        "'fred' with `series` (e.g. DFEDTARU).\n"
        "  rule + params (ALL required for that rule):\n"
        "    crossed_above / crossed_below: `threshold` (number), `window_start` (YYYY-MM-DD), `by` (YYYY-MM-DD)\n"
        "    above / below: `threshold` (number), `by` (YYYY-MM-DD)\n"
        "    dropped / rose: `amount` (number), `window_start`, `by`\n"
        "  Use the key `threshold` (never `value`). `by` is the resolution deadline; "
        "`window_start` is usually Jan 1 of the deadline's year. For 'reach/hit X by DATE', "
        "use crossed_above (any touch counts): threshold=X, window_start=<Jan 1 that year>, by=<DATE>. "
        "Omit the oracle entirely if unsure. Respond with ONLY a JSON object, no markdown fences:\n"
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
    r = None
    try:
        r = requests.post(API_URL,
                          headers={"content-type": "application/json", "x-api-key": key,
                                   "anthropic-version": "2023-06-01"},
                          json={"model": MODEL, "max_tokens": 1200,
                                "system": system,
                                "messages": [{"role": "user", "content": user}]},
                          timeout=90)
        if r.status_code != 200:
            print(f"Claude HTTP {r.status_code} (model={MODEL}): {r.text[:400]}", file=sys.stderr)
            return None
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


def _num(v):
    """Coerce a threshold/amount to float, tolerating '$150,000' / '150k' style."""
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = normalize_nums(v).strip()
        try:
            return float(s)
        except ValueError:
            return None
    return None


def sanitize_oracle(orc, expiry) -> dict | None:
    """
    Validate/repair a model-produced oracle against the schema core/oracles.py
    actually understands. Returns a clean oracle or None (drop it) — a broken
    oracle that silently fails to resolve is worse than no oracle.
    """
    if not isinstance(orc, dict):
        return None
    src, rule = orc.get("source"), orc.get("rule")
    if src not in ("yahoo", "fred"):
        return None
    if rule not in {"crossed_above", "crossed_below", "above", "below", "dropped", "rose"}:
        return None
    if src == "yahoo" and not orc.get("symbol"):
        return None
    if src == "fred" and not orc.get("series"):
        return None
    if "threshold" not in orc and "value" in orc:   # common model slip
        orc["threshold"] = orc["value"]
    orc.setdefault("by", expiry)                    # deadline defaults to expiry
    if rule in ("crossed_above", "crossed_below", "dropped", "rose"):
        orc.setdefault("window_start", str(orc["by"])[:4] + "-01-01")
    key = "amount" if rule in ("dropped", "rose") else "threshold"
    num = _num(orc.get(key))
    if num is None:
        return None
    orc[key] = num
    keep = {"source", "symbol", "series", "rule", "threshold",
            "amount", "window_start", "by"}
    return {k: orc[k] for k in keep if k in orc}


def main() -> int:
    request = (os.environ.get("REQUEST_TEXT") or "").strip()
    if not request:
        print("::error::empty request")
        return 1
    print(f"Request: {request}")

    kws = keywords(request)
    candidates = {
        "polymarket": search_polymarket(kws),
        "manifold": search_manifold(kws),
        "predictit": search_predictit(kws),
    }
    n = sum(len(v) for v in candidates.values())
    print(f"Found {n} candidate markets "
          f"(pm={len(candidates['polymarket'])} mf={len(candidates['manifold'])} "
          f"pi={len(candidates['predictit'])})")
    if n == 0:
        print("::warning::no candidate markets matched")
        print("REASON=No prediction markets matched that request on any venue.")
        return 2

    result = choose_topic(request, candidates)
    if not result or not result.get("ok"):
        reason = (result.get("reason") if result else None) or "the matcher could not use the request"
        print(f"::warning::no topic wired: {reason}")
        print(f"REASON={reason}")
        return 2
    topic = result["topic"]
    print(f"Draft topic: {topic.get('id')} — {topic.get('question')}")

    if topic["id"] in existing_ids():
        print(f"::warning::topic id {topic['id']} already exists")
        print("ALREADY_EXISTS=" + topic["id"])
        return 0

    verified = {}
    for venue, scfg in (topic.get("sources") or {}).items():
        ok = verify_source(venue, scfg)
        print(f"  verify {venue} {scfg.get('id')}: {'OK' if ok else 'FAIL'}")
        if ok:
            verified[venue] = scfg
    if not verified:
        print("::warning::no source verified with a live price")
        print("REASON=A match was found but its market had no live price.")
        return 2
    topic["sources"] = verified

    if topic.get("oracle"):
        clean = sanitize_oracle(topic["oracle"], topic.get("expiry"))
        if clean:
            topic["oracle"] = clean
            print(f"  oracle: {clean.get('source')} {clean.get('rule')} kept")
        else:
            topic.pop("oracle", None)
            print("  oracle: dropped (could not validate)")

    path = ROOT / "config" / "topics.yml"
    path.write_text(path.read_text().rstrip() + "\n\n" + yaml_block(topic))
    print(f"::notice::Added topic '{topic['id']}' with sources: {', '.join(verified)}")
    print("ADDED_TOPIC_ID=" + topic["id"])
    print("ADDED_QUESTION=" + topic["question"])
    print("ADDED_SOURCES=" + ", ".join(verified))
    return 0


if __name__ == "__main__":
    sys.exit(main())
