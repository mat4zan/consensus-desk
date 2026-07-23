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

    The public API requires a token (unauthenticated requests get 403), and
    even with a token the aggregate community prediction is only returned to
    accounts granted aggregate-data access — a basic/new account gets an empty
    `aggregations` block (history_len 0, nr_forecasters null) for every
    question. When that happens this returns None (no usable data), so the
    source simply does not contribute rather than erroring. Set METACULUS_TOKEN
    as an Actions secret; auth uses the "Token <key>" scheme.
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

        # with_cp=true asks for the community-prediction aggregation inline.
        r = requests.get(
            f"{self.BASE}/posts/{qid}/",
            params={"with_cp": "true"},
            headers=headers,
            timeout=TIMEOUT,
        )
        # No token / not permitted / gone: no usable data, but not an error
        # worth backing off on. Return None rather than raise.
        if r.status_code in (401, 403, 404):
            return None
        r.raise_for_status()
        d = r.json()

        # post -> question -> aggregations.<method>. The current CP is the
        # `latest` snapshot, or the last `history` point when latest is unset.
        q = d.get("question") or d
        cp = None
        aggs = q.get("aggregations") or {}
        agg = aggs.get("recency_weighted") or aggs.get("unweighted") or {}
        point = agg.get("latest")
        if not point:
            hist = agg.get("history") or []
            point = hist[-1] if hist else None
        if point:
            centers = point.get("centers") or point.get("means")
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
    """
    Kalshi. The public API returns market metadata but strips all pricing —
    live quotes require an authenticated, RSA-signed session. Provide two
    secrets and this signs each request; without them it stays unauthenticated
    (and returns None, contributing nothing).

      KALSHI_ACCESS_KEY_ID  — the API key id (a UUID) from Kalshi account settings
      KALSHI_PRIVATE_KEY    — the RSA private key (PEM) downloaded with that key

    READ-ONLY: this collector only issues GET requests for market data. It never
    touches orders, positions, or funds.
    """

    name = "kalshi"
    tier = "markets"

    HOST = "https://api.elections.kalshi.com"

    def _auth_headers(self, method: str, path: str) -> dict:
        key_id = self.secrets.get("KALSHI_ACCESS_KEY_ID") or os.environ.get("KALSHI_ACCESS_KEY_ID")
        pem = self.secrets.get("KALSHI_PRIVATE_KEY") or os.environ.get("KALSHI_PRIVATE_KEY")
        if not key_id or not pem:
            return {}

        import base64
        import time

        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding

        ts = str(int(time.time() * 1000))
        # A secret stored via the web UI can arrive with literal "\n" escapes.
        priv = serialization.load_pem_private_key(
            pem.replace("\\n", "\n").encode(), password=None
        )
        signature = priv.sign(
            (ts + method + path).encode(),
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                        salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256(),
        )
        return {
            "KALSHI-ACCESS-KEY": key_id,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode(),
            "KALSHI-ACCESS-TIMESTAMP": ts,
        }

    def fetch(self, source_cfg: dict) -> Quote | None:
        ticker = source_cfg.get("id")
        if not ticker:
            return None

        path = f"/trade-api/v2/markets/{ticker}"
        headers = dict(UA)
        headers.update(self._auth_headers("GET", path))

        r = requests.get(f"{self.HOST}{path}", headers=headers, timeout=TIMEOUT)
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
class ManifoldCollector(Collector):
    """
    Manifold Markets. Open API, no auth. Play-money (mana), so it is a softer
    signal than real-money venues — it carries a lower base weight and is not
    clustered with Polymarket/Kalshi (an independent crowd, not an arbitrage
    counterpart). `id` is the market slug from the market URL.
    """

    name = "manifold"
    tier = "markets"

    BASE = "https://api.manifold.markets/v0"

    def fetch(self, source_cfg: dict) -> Quote | None:
        slug = source_cfg.get("id")
        if not slug:
            return None

        r = requests.get(f"{self.BASE}/slug/{slug}", headers=UA, timeout=TIMEOUT)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        m = r.json()

        # Only binary markets carry a single probability; skip anything else,
        # and skip already-resolved markets (a resolved price is not a forecast).
        if m.get("outcomeType") != "BINARY" or m.get("isResolved"):
            return None
        p = _f(m.get("probability"))
        if p is None:
            return None

        return Quote(
            probability=p,
            raw_price=p,
            volume_usd=_f(m.get("volume")),
            n_traders=m.get("uniqueBettorCount"),
            raw={"slug": slug, "url": m.get("url")},
        )

    def liquidity_ok(self, quote: Quote) -> bool:
        # `volume` is mana (play money), not USD, so the shared USD floor does
        # not apply. Gate on participation instead.
        return (quote.n_traders or 0) >= 15


@register
class PredictItCollector(Collector):
    """
    PredictIt. Real-money (dollar-capped) US-politics exchange. Open JSON API,
    no auth. A market has several contracts; `id` is the market id and
    `outcome` selects the contract by name (e.g. "Republican"). The contract's
    lastTradePrice is already a 0-1 probability.
    """

    name = "predictit"
    tier = "markets"

    BASE = "https://www.predictit.org/api/marketdata"

    def fetch(self, source_cfg: dict) -> Quote | None:
        mid = source_cfg.get("id")
        if not mid:
            return None

        r = requests.get(f"{self.BASE}/markets/{mid}", headers=UA, timeout=TIMEOUT)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        contracts = (r.json() or {}).get("contracts") or []
        if not contracts:
            return None

        want = (source_cfg.get("outcome") or "").strip().lower()
        chosen = None
        if want:
            chosen = next(
                (c for c in contracts if (c.get("name") or "").strip().lower() == want),
                None,
            )
        if chosen is None:
            chosen = contracts[0]

        p = _f(chosen.get("lastTradePrice"))
        # 0.0 usually means "no trades yet", not a real 0% — treat as no data.
        if p is None or p <= 0:
            return None

        return Quote(
            probability=p,
            raw_price=p,
            raw={"market": mid, "contract": chosen.get("name")},
        )


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
