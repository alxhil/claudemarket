"""MLS betting odds via The Odds API (https://the-odds-api.com).

Requires a free API key (env ODDS_API_KEY). Free tier = 500 requests/mo.
Returns 3-way moneyline (home / draw / away) in American format.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

import requests

_HEADERS = {"User-Agent": "Mozilla/5.0"}
_SPORT = "soccer_usa_mls"
_URL = f"https://api.the-odds-api.com/v4/sports/{_SPORT}/odds"


class OddsError(Exception):
    """Raised when the odds provider can't be reached or the key is bad."""


@dataclass
class MatchOdds:
    home: str
    away: str
    commence: datetime  # timezone-aware UTC
    home_ml: Optional[int]
    draw_ml: Optional[int]
    away_ml: Optional[int]
    book: str


def american(price: Optional[int]) -> str:
    if price is None:
        return "—"
    return f"+{price}" if price > 0 else str(price)


def get_mls_odds(api_key: str, *, timeout: float = 12.0) -> List[MatchOdds]:
    """Fetch current MLS moneyline odds for all events the books have posted."""
    params = {
        "apiKey": api_key,
        "regions": "us",
        "markets": "h2h",
        "oddsFormat": "american",
    }
    try:
        resp = requests.get(_URL, params=params, headers=_HEADERS, timeout=timeout)
    except requests.RequestException as exc:
        raise OddsError(str(exc)) from exc

    if resp.status_code == 401:
        raise OddsError("invalid ODDS_API_KEY")
    if resp.status_code == 429:
        raise OddsError("odds quota exceeded")
    resp.raise_for_status()

    out: List[MatchOdds] = []
    for ev in resp.json():
        home = ev.get("home_team")
        away = ev.get("away_team")
        try:
            commence = datetime.fromisoformat(
                ev["commence_time"].replace("Z", "+00:00")
            ).astimezone(timezone.utc)
        except (KeyError, ValueError):
            continue

        book, hml, dml, aml = "", None, None, None
        for bk in ev.get("bookmakers", []):
            for mk in bk.get("markets", []):
                if mk.get("key") != "h2h":
                    continue
                prices = {o.get("name"): o.get("price") for o in mk.get("outcomes", [])}
                hml, aml, dml = prices.get(home), prices.get(away), prices.get("Draw")
                if hml is not None and aml is not None:
                    book = bk.get("title", "")
                    break
            if book:
                break

        out.append(MatchOdds(home, away, commence, hml, dml, aml, book))
    return out
