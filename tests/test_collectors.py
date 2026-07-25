import sys
from pathlib import Path
from unittest.mock import patch

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from collectors.sources import PolymarketCollector  # noqa: E402

CFG = yaml.safe_load(open(Path(__file__).parent.parent / "config" / "settings.yml"))


class FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _market(slug, price, vol=1000):
    return [{"slug": slug, "outcomePrices": [str(price), str(1 - price)],
              "volumeNum": vol, "closed": False}]


def test_single_id_unchanged():
    c = PolymarketCollector(CFG)
    with patch("collectors.sources.requests.get", return_value=FakeResp(_market("a", 0.30, 500))):
        q = c.fetch({"id": "a"})
    assert q is not None
    assert abs(q.probability - 0.30) < 1e-9
    assert q.volume_usd == 500


def test_ids_are_summed_as_mutually_exclusive_buckets():
    # e.g. Fed "hike 25bp" (0.24) + "hike 50bp" (0.0075) = P(any hike)
    responses = {"hike25": _market("hike25", 0.24, 100), "hike50": _market("hike50", 0.0075, 50)}

    def fake_get(url, params=None, **kw):
        return FakeResp(responses[params["slug"]])

    c = PolymarketCollector(CFG)
    with patch("collectors.sources.requests.get", side_effect=fake_get):
        q = c.fetch({"ids": ["hike25", "hike50"]})
    assert q is not None
    assert abs(q.probability - 0.2475) < 1e-9
    assert q.volume_usd == 150
    assert q.raw["summed"] is True


def test_ids_skips_dead_slug_rather_than_failing():
    def fake_get(url, params=None, **kw):
        return FakeResp([] if params["slug"] == "dead" else _market("live", 0.5, 10))

    c = PolymarketCollector(CFG)
    with patch("collectors.sources.requests.get", side_effect=fake_get):
        q = c.fetch({"ids": ["dead", "live"]})
    assert q is not None
    assert abs(q.probability - 0.5) < 1e-9


def test_no_ids_or_id_returns_none():
    c = PolymarketCollector(CFG)
    assert c.fetch({}) is None
