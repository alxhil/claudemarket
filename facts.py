"""Random-fact lookup using keyless public APIs.

Primary source is uselessfacts (general trivia); if it's unreachable we
fall back to catfact.ninja so the command still returns something.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List

import requests

_HEADERS = {"User-Agent": "Mozilla/5.0"}


@dataclass
class Fact:
    text: str
    source: str


def _uselessfacts(timeout: float) -> Fact:
    resp = requests.get(
        "https://uselessfacts.jsph.pl/api/v2/facts/random",
        params={"language": "en"},
        headers=_HEADERS,
        timeout=timeout,
    )
    resp.raise_for_status()
    text = (resp.json().get("text") or "").strip()
    if not text:
        raise ValueError("empty fact")
    return Fact(text=text, source="uselessfacts.jsph.pl")


def _catfacts(timeout: float) -> Fact:
    resp = requests.get(
        "https://catfact.ninja/fact", headers=_HEADERS, timeout=timeout
    )
    resp.raise_for_status()
    text = (resp.json().get("fact") or "").strip()
    if not text:
        raise ValueError("empty fact")
    return Fact(text=text, source="catfact.ninja")


_SOURCES: List[Callable[[float], Fact]] = [_uselessfacts, _catfacts]


class NoFactAvailable(Exception):
    """Raised when every fact source failed."""


def get_random_fact(*, timeout: float = 10.0) -> Fact:
    """Return a random fact, trying each source until one succeeds."""
    last_exc: Exception | None = None
    for source in _SOURCES:
        try:
            return source(timeout)
        except Exception as exc:  # network / bad payload — try the next source
            last_exc = exc
    raise NoFactAvailable("all fact sources failed") from last_exc


if __name__ == "__main__":
    try:
        f = get_random_fact()
        print(f"{f.text}\n  — via {f.source}")
    except NoFactAvailable as e:
        print(f"Could not fetch a fact: {e}")
