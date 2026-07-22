"""
LLM layer.

Hard rule enforced structurally, not by prompt discipline alone: this
module can only return text. It has no path to write a probability into
the pool. The model has no calibration and will anchor on whichever
source is loudest, so it is given the numbers as fixed inputs and asked
only to account for them.
"""

from __future__ import annotations

import json
import os

import requests

API_URL = "https://api.anthropic.com/v1/messages"


class Explainer:
    def __init__(self, cfg: dict, api_key: str | None = None):
        lcfg = cfg.get("llm", {})
        self.enabled = lcfg.get("enabled", True)
        self.model = lcfg.get("model", "claude-sonnet-4-6")
        self.max_tokens = lcfg.get("max_tokens", 1000)
        self.spread_threshold = lcfg.get("explain_when_spread_above_pp", 15.0)
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")

    def _call(self, system: str, user: str) -> str | None:
        if not self.enabled or not self.api_key:
            return None
        try:
            r = requests.post(
                API_URL,
                headers={
                    "content-type": "application/json",
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                },
                json={
                    "model": self.model,
                    "max_tokens": self.max_tokens,
                    "system": system,
                    "messages": [{"role": "user", "content": user}],
                },
                timeout=60,
            )
            r.raise_for_status()
            blocks = r.json().get("content", [])
            return "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
        except Exception:
            return None

    def explain_disagreement(
        self, question: str, resolution: str, result, criteria_notes: dict
    ) -> str | None:
        """
        Why do the sources differ? Usually the answer is a resolution-criteria
        mismatch rather than a genuine difference of opinion, and that
        distinction is the whole value of the panel.
        """
        if result.spread_pp < self.spread_threshold:
            return None

        rows = "\n".join(
            f"- {c['source']}: {c['probability'] * 100:.1f}% "
            f"(weight {c['weight']:.2f}, {c['age_hours']:.0f}h old)"
            + (f" — note: {criteria_notes[c['source']]}" if c["source"] in criteria_notes else "")
            for c in result.contributions
        )

        system = (
            "You analyse forecast disagreement. You are given fixed probabilities "
            "from multiple sources. You must NOT produce your own probability "
            "estimate, forecast, or recommendation. Explain only why the sources "
            "differ. Distinguish resolution-criteria mismatch from genuine "
            "disagreement about likelihood — the first is far more common. "
            "Two or three sentences. No preamble, no hedging language."
        )
        user = (
            f"Question: {question}\n\n"
            f"Canonical resolution: {resolution}\n\n"
            f"Sources:\n{rows}\n\n"
            f"Pooled: {result.probability * 100:.1f}%, spread {result.spread_pp:.0f}pp.\n\n"
            "Why do these sources differ?"
        )
        return self._call(system, user)

    def extract_from_commentary(self, question: str, text: str) -> dict | None:
        """
        Parse unstructured analyst commentary into a structured view.
        Returns None on any parse failure — a malformed extraction must
        never become a silent zero.
        """
        system = (
            "Extract a structured probability view from commentary. Respond with "
            "ONLY a JSON object, no markdown fences, no preamble. Schema: "
            '{"implied_probability": float 0-1 or null, "direction": '
            '"up"|"down"|"neutral", "confidence": "low"|"medium"|"high", '
            '"key_claim": string under 25 words}. '
            "If the text expresses no view on this question, set "
            "implied_probability to null."
        )
        user = f"Question: {question}\n\nCommentary:\n{text[:6000]}"
        raw = self._call(system, user)
        if not raw:
            return None
        cleaned = raw.replace("```json", "").replace("```", "").strip()
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            return None

        p = data.get("implied_probability")
        if p is not None:
            try:
                p = float(p)
            except (TypeError, ValueError):
                return None
            if not 0.0 <= p <= 1.0:
                return None
            data["implied_probability"] = p
        return data
