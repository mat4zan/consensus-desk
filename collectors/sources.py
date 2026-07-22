"""
Concrete collectors.

Endpoints and response shapes drift. Each fetch() is defensive: if the
shape is not what we expect, return None rather than guessing. A missing
source is recoverable; a wrong number silently entering the pool is not.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import requests

from .base import Collector, Quote, register

TIMEOUT = 20
UA = {"User-Agent": "consensus-desk/1.0"}


def _f(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


@register
class PolymarketCollector(Collector):
    name = "polymarket"
    tier = "markets"

    BASE = "https://gamma-api.polymarket.com"

    def fetch(self, source_cfg: dict) -> Quote | None:
        slug = source_cfg.get("id")
        if not slug:
            return None

        r = requests.get(
            f"{self.BASE}/markets", params={"slug": slug}, headers=UA, timeout=TIMEOUT
        )
        r.raise_for_status()
        data = r.json()
        if not data:
            return None
        m = data[0] if isinstance(data, list) else data

        # outcomePrices arrives as a JSON-encoded string on this endpoint.
        prices = m.get("outcomePrices")
        if isinstance(prices, str):
            import json as _json

            try:
                prices = _json.loads(prices)
            except Exception:
                prices = None
        if not prices:
            return None

        p = _f(prices[0])
        if p is None:
            return None

        vol = _f(m.get("volumeNum") or m.get("volume"))

        return Quote(
            probability=p,
            raw_price=p,
            volume_usd=vol,
            raw={"slug": slug, "liquidity": m.get("liquidityNum"), "closed": m.get("closed")},
        )

    def discover(self, filters: dict) -> list[dict]:
        r = requests.get(
            f"{self.BASE}/markets",
            params={"active": "true", "closed": "false", "limit": 200, "order": "volumeNum",
                    "ascending": "false"},
            headers=UA,
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        out = []
        min_vol = filters.get("min_volume_usd", 50000)
        exclude = [k.lower() for k in filters.get("exclude_keywords", [])]

        for m in r.json():
            vol = _f(m.get("volumeNum"), 0) or 0
            if vol < min_vol:
                continue
            q = (m.get("question") or "").lower()
            if any(k in q for k in exclude):
                continue
            out.append(
                {
                    "external_id": m.get("slug"),
                    "question": m.get("question"),
                    "volume_usd": vol,
                }
            )
        return out


@register
class MetaculusCollector(Collector):
    """
    Metaculus community prediction.

    The public API now requires a token: unauthenticated requests get 403.
    Set METACULUS_TOKEN as an Actions secret (see README). Auth uses the
    "Token <key>" scheme. Endpoint is the modern /api/posts/{id}/; the older
    api2 shape is kept as a fallback so pre-migration IDs still resolve.
    """

    name = "metaculus"
    tier = "forecasters"

    BASE = "https://www.metaculus.com/api"

    def fetch(self, source_cfg: dict) -> Quote | None:
        qid = source_cfg.get("id")
        if not qid:
            return None

        token = self.secrets.get("METACULUS_TOKEN") or os.environ.get("METACULUS_TOKEN")
        headers = dict(UA)
        if token:
            headers["Authorization"] = f"Token {token}"

        r = requests.get(f"{self.BASE}/posts/{qid}/", headers=headers, timeout=TIMEOUT)
        # No token / not permitted / gone: no usable data, but not an error
        # worth backing off on. Return None rather than raise.
        if r.status_code in (401, 403, 404):
            return None
        r.raise_for_status()
        d = r.json()

        # Modern shape: post -> question -> aggregations.recency_weighted.latest.centers
        q = d.get("question") or d
        cp = None
        latest = (
            q.get("aggregations", {})
            .get("recency_weighted", {})
            .get("latest")
            or {}
        )
        centers = latest.get("centers")
        if centers:
            cp = centers[0]
        # Legacy api2 shape fallback.
        if cp is None:
            cp = d.get("community_prediction", {}).get("full", {}).get("q2")

        p = _f(cp)
        if p is None:
            return None

        return Quote(
            probability=p,
            raw_price=p,
            n_traders=q.get("nr_forecasters") or d.get("nr_forecasters"),
            raw={"question_id": qid, "title": d.get("title")},
        )


@register
class KalshiCollector(Collector):
    name = "kalshi"
    tier = "markets"

    BASE = "https://api.elections.kalshi.com/trade-api/v2"

    def fetch(self, source_cfg: dict) -> Quote | None:
        ticker = source_cfg.get("id")
        if not ticker:
            return None

        r = requests.get(f"{self.BASE}/markets/{ticker}", headers=UA, timeout=TIMEOUT)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        m = r.json().get("market", {})

        # Kalshi quotes in cents. Use the mid, not last trade — last trade
        # can be stale by hours on a thin market.
        bid = _f(m.get("yes_bid"))
        ask = _f(m.get("yes_ask"))
        if bid is not None and ask is not None and ask > 0:
            p = (bid + ask) / 200.0
        else:
            last = _f(m.get("last_price"))
            if last is None:
                return None
            p = last / 100.0

        return Quote(
            probability=p,
            raw_price=p,
            volume_usd=_f(m.get("volume")),
            raw={"ticker": ticker, "open_interest": m.get("open_interest")},
        )


@register
class OddsApiCollector(Collector):
    """
    Bookmaker lines via The Odds API. Overround is stripped downstream in
    pooling.strip_overround_shin — this collector returns the raw implied
    probabilities so the correction is visible and auditable.

    Free tier is 500 calls/month, which is the binding constraint on the
    whole system. Runs on the bookmakers tier (24h) for that reason.
    """

    name = "pinnacle"
    tier = "bookmakers"

    BASE = "https://api.the-odds-api.com/v4"
    BOOKMAKER = "pinnacle"

    def fetch(self, source_cfg: dict) -> Quote | None:
        key = self.secrets.get("ODDS_API_KEY") or os.environ.get("ODDS_API_KEY")
        if not key:
            return None

        sport = source_cfg.get("sport", "politics")
        event_id = source_cfg.get("id")
        if not event_id:
            return None

        r = requests.get(
            f"{self.BASE}/sports/{sport}/odds",
            params={
                "apiKey": key,
                "regions": "eu",
                "markets": "h2h",
                "bookmakers": self.BOOKMAKER,
            },
            headers=UA,
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            return None

        for event in r.json():
            if event.get("id") != event_id:
                continue
            for bk in event.get("bookmakers", []):
                for market in bk.get("markets", []):
                    outcomes = market.get("outcomes", [])
                    implied = {}
                    for o in outcomes:
                        price = _f(o.get("price"))
                        if price and price > 1:
                            implied[o.get("name")] = 1.0 / price
                    if not implied:
                        continue

                    from core.pooling import (
                        strip_overround_proportional,
                        strip_overround_shin,
                    )

                    method = (
                        self.cfg.get("bias_correction", {})
                        .get("overround", {})
                        .get("method", "shin")
                    )
                    fn = (
                        strip_overround_shin
                        if method == "shin"
                        else strip_overround_proportional
                    )
                    fair = fn(implied)

                    target = source_cfg.get("outcome") or outcomes[0].get("name")
                    p = fair.get(target)
                    if p is None:
                        return None

                    return Quote(
                        probability=p,
                        raw_price=implied.get(target),
                        raw={
                            "bookmaker": self.BOOKMAKER,
                            "overround": round(sum(implied.values()), 4),
                            "method": method,
                        },
                    )
        return None


@register
class ManualCollector(Collector):
    """
    Escape hatch. Reads a hand-entered probability from topics.yml.
    Use for sources with no API, or to pin a value while debugging.
    """

    name = "manual"
    tier = "commentary"

    def fetch(self, source_cfg: dict) -> Quote | None:
        p = _f(source_cfg.get("probability"))
        if p is None:
            return None
        ts = source_cfg.get("as_of")
        try:
            when = datetime.fromisoformat(ts) if ts else datetime.now(timezone.utc)
        except Exception:
            when = datetime.now(timezone.utc)
        return Quote(probability=p, raw_price=p, ts=when, raw={"manual": True})
