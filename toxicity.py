"""Toxicity scoring via Google's Perspective API.

Scores each message 0..1 with the TOXICITY attribute and aggregates to a
1-100 report. Only raw message text is sent to the API (no usernames,
ids, or server info), with doNotStore=true.

Free tier is throttled to ~1 request/second, so messages are scored
sequentially with a small delay — ~1s per message analyzed.

Key setup: https://developers.perspectiveapi.com/ (enable the Comment
Analyzer API on a Google Cloud project, create an API key), then set
PERSPECTIVE_API_KEY in .env.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List, Optional

import requests

_URL = "https://commentanalyzer.googleapis.com/v1alpha1/comments:analyze"
_QPS_DELAY = 1.1  # free tier is ~1 QPS
_MAX_CHARS = 3000


class ToxicityError(Exception):
    pass


class QuotaExceeded(ToxicityError):
    pass


@dataclass
class ToxicityReport:
    analyzed: int
    score: int          # 1-100 average
    worst_score: int    # 1-100 max single message
    worst_excerpt: str  # short excerpt of the most toxic message


def _score_text(text: str, api_key: str, timeout: float) -> Optional[float]:
    body = {
        "comment": {"text": text[:_MAX_CHARS]},
        "requestedAttributes": {"TOXICITY": {}},
        "doNotStore": True,
    }
    resp = requests.post(
        _URL, params={"key": api_key}, json=body, timeout=timeout
    )
    if resp.status_code == 429:
        raise QuotaExceeded("Perspective API quota exceeded")
    if resp.status_code == 400:
        # Usually unsupported language for a short/odd message — skip it.
        return None
    if resp.status_code in (401, 403):
        raise ToxicityError("Perspective API key rejected")
    resp.raise_for_status()
    try:
        return resp.json()["attributeScores"]["TOXICITY"]["summaryScore"]["value"]
    except (KeyError, TypeError) as exc:
        raise ToxicityError("unexpected Perspective response") from exc


def analyze(texts: List[str], api_key: str, *, timeout: float = 10.0) -> ToxicityReport:
    """Score a list of messages; returns an aggregate 1-100 report."""
    if not api_key:
        raise ToxicityError("PERSPECTIVE_API_KEY not set")

    scores: List[tuple[float, str]] = []
    for i, text in enumerate(texts):
        text = text.strip()
        if not text:
            continue
        if i:
            time.sleep(_QPS_DELAY)
        val = _score_text(text, api_key, timeout)
        if val is not None:
            scores.append((val, text))

    if not scores:
        raise ToxicityError("no scorable messages")

    avg = sum(v for v, _ in scores) / len(scores)
    worst_val, worst_text = max(scores, key=lambda s: s[0])
    excerpt = worst_text if len(worst_text) <= 80 else worst_text[:77] + "..."
    to100 = lambda v: max(1, min(100, round(v * 100)))
    return ToxicityReport(
        analyzed=len(scores),
        score=to100(avg),
        worst_score=to100(worst_val),
        worst_excerpt=excerpt,
    )


if __name__ == "__main__":
    import os
    import sys

    key = os.environ.get("PERSPECTIVE_API_KEY", "")
    samples = sys.argv[1:] or ["you are wonderful", "this is a neutral sentence"]
    try:
        r = analyze(samples, key)
        print(f"analyzed {r.analyzed} · score {r.score}/100 · worst {r.worst_score}/100")
        print(f"worst: {r.worst_excerpt}")
    except ToxicityError as e:
        print(f"error: {e}")
