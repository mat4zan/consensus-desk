"""
Source plugin interface.

Adding a source is a new file plus a config line. Nothing in core/ needs
to change. Every collector normalises to the same shape, so the pooling
layer never knows or cares where a number came from.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Quote:
    """Normalised output. Every collector returns these."""

    probability: float
    raw_price: float | None = None
    volume_usd: float | None = None
    n_traders: int | None = None
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    raw: dict = field(default_factory=dict)


class Collector(ABC):
    #: Registry key. Must match the source names used in settings.yml.
    name: str = "unnamed"

    #: Which polling tier this belongs to: markets | forecasters | bookmakers | commentary
    tier: str = "markets"

    #: If True, the runner will not fail the whole collect when this errors.
    optional: bool = True

    def __init__(self, cfg: dict, secrets: dict | None = None):
        self.cfg = cfg
        self.secrets = secrets or {}

    @abstractmethod
    def fetch(self, source_cfg: dict) -> Quote | None:
        """
        Fetch one topic's current quote.

        `source_cfg` is the per-topic mapping block from topics.yml,
        e.g. {"id": "will-china-...", "criteria_note": "..."}.

        Return None when the source has no usable data — an illiquid
        market, a closed question, a missing ID. Returning None is not
        an error; raising is.
        """
        ...

    def discover(self, filters: dict) -> list[dict]:
        """
        Optional. Return untracked questions matching the discovery filters.
        Each dict: {external_id, question, volume_usd}.
        Default is no discovery support.
        """
        return []

    def liquidity_ok(self, quote: Quote) -> bool:
        """
        A price on thin volume is not a signal. Override per source where
        the threshold differs.
        """
        min_vol = self.cfg.get("discovery", {}).get("min_volume_usd", 0)
        if quote.volume_usd is None:
            return True
        return quote.volume_usd >= min_vol * 0.1


_REGISTRY: dict[str, type[Collector]] = {}


def register(cls: type[Collector]) -> type[Collector]:
    _REGISTRY[cls.name] = cls
    return cls


def get_collector(name: str) -> type[Collector] | None:
    return _REGISTRY.get(name)


def all_collectors() -> dict[str, type[Collector]]:
    return dict(_REGISTRY)
