"""Upcoming US soccer (MLS) fixtures via ESPN's public JSON API.

No API key required for fixtures. Betting odds (optional) come from
The Odds API via odds.py and are merged in by kickoff time.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import requests

from odds import MatchOdds, OddsError, get_mls_odds

_HEADERS = {"User-Agent": "Mozilla/5.0"}

# ESPN league slug: usa.1 = Major League Soccer.
_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/usa.1/scoreboard"

# Generic tokens to ignore when matching team names across providers.
_STOP = {"fc", "sc", "cf", "club", "the", "of"}

try:
    from zoneinfo import ZoneInfo

    _ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover - zoneinfo/tzdata unavailable
    _ET = None


@dataclass
class Match:
    home: str
    away: str
    kickoff: datetime  # timezone-aware UTC
    venue: Optional[str]
    odds: Optional[MatchOdds] = field(default=None)

    def when_str(self) -> str:
        dt = self.kickoff.astimezone(_ET) if _ET else self.kickoff
        tz = "ET" if _ET else "UTC"
        return dt.strftime(f"%a %b %d · %I:%M %p {tz}").replace("· 0", "· ")


class NoMatchesAvailable(Exception):
    """Raised when the fixtures feed can't be reached."""


def _tokens(name: str) -> set:
    ascii_name = (
        unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    )
    return {t for t in re.findall(r"[a-z]+", ascii_name.lower()) if t not in _STOP}


def _parse(events: list, now: datetime) -> List[Match]:
    out: List[Match] = []
    for e in events:
        try:
            kickoff = datetime.fromisoformat(e["date"].replace("Z", "+00:00"))
            comp = e["competitions"][0]
        except (KeyError, ValueError, IndexError):
            continue
        if comp.get("status", {}).get("type", {}).get("state") != "pre" or kickoff < now:
            continue

        home = away = None
        for c in comp.get("competitors", []):
            team = (c.get("team") or {}).get("displayName")
            if c.get("homeAway") == "home":
                home = team
            elif c.get("homeAway") == "away":
                away = team
        if not home or not away:
            continue

        out.append(
            Match(
                home=home,
                away=away,
                kickoff=kickoff,
                venue=(comp.get("venue") or {}).get("fullName"),
            )
        )
    out.sort(key=lambda m: m.kickoff)
    return out


def _attach_odds(matches: List[Match], odds_list: List[MatchOdds]) -> None:
    """Match odds to fixtures by kickoff time, disambiguating by team name."""
    for m in matches:
        cands = [
            o
            for o in odds_list
            if abs((o.commence - m.kickoff).total_seconds()) <= 3600
        ]
        if not cands:
            continue
        if len(cands) == 1:
            m.odds = cands[0]
            continue
        # Multiple kickoffs at the same time — pick best team-token overlap.
        mh, ma = _tokens(m.home), _tokens(m.away)
        m.odds = max(
            cands,
            key=lambda o: len(_tokens(o.home) & mh) + len(_tokens(o.away) & ma),
        )


def get_upcoming_matches(
    *,
    limit: int = 3,
    days: int = 60,
    timeout: float = 12.0,
    odds_api_key: Optional[str] = None,
) -> List[Match]:
    """Return up to ``limit`` upcoming MLS matches, with odds if a key is given."""
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=days)
    params = {"dates": f"{now:%Y%m%d}-{end:%Y%m%d}", "limit": 200}
    try:
        resp = requests.get(_URL, params=params, headers=_HEADERS, timeout=timeout)
        resp.raise_for_status()
        events = resp.json().get("events") or []
    except requests.RequestException as exc:
        raise NoMatchesAvailable(str(exc)) from exc

    matches = _parse(events, now)[:limit]

    if odds_api_key and matches:
        try:
            _attach_odds(matches, get_mls_odds(odds_api_key, timeout=timeout))
        except OddsError as exc:
            # Odds are a nice-to-have; never fail the fixtures list over them.
            print(f"odds fetch failed: {exc!r}")

    return matches


if __name__ == "__main__":
    import os

    try:
        for m in get_upcoming_matches(odds_api_key=os.environ.get("ODDS_API_KEY")):
            print(f"{m.when_str()}  —  {m.home} vs {m.away}")
            if m.venue:
                print(f"   @ {m.venue}")
            if m.odds:
                from odds import american

                print(
                    f"   odds: {m.home} {american(m.odds.home_ml)} · "
                    f"Draw {american(m.odds.draw_ml)} · "
                    f"{m.away} {american(m.odds.away_ml)}  ({m.odds.book})"
                )
    except NoMatchesAvailable as e:
        print(f"Could not fetch fixtures: {e}")
