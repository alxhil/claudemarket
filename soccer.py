"""Upcoming US soccer (MLS) fixtures via ESPN's public JSON API.

No API key required. ESPN's scoreboard endpoint returns fixtures with
team names, kickoff time, and venue. We query a forward date range and
keep the matches that haven't kicked off yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import requests

_HEADERS = {"User-Agent": "Mozilla/5.0"}

# ESPN league slug: usa.1 = Major League Soccer.
_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/usa.1/scoreboard"

try:
    from zoneinfo import ZoneInfo

    _ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover - zoneinfo/tzdata unavailable
    _ET = None


@dataclass
class Match:
    name: str
    kickoff: datetime  # timezone-aware UTC
    venue: Optional[str]

    def local_str(self) -> str:
        dt = self.kickoff.astimezone(_ET) if _ET else self.kickoff
        tz = "ET" if _ET else "UTC"
        # Strip leading zero from the hour for readability.
        return dt.strftime(f"%a %b %d, %I:%M %p {tz}").replace(" 0", " ")


class NoMatchesAvailable(Exception):
    """Raised when the fixtures feed can't be reached."""


def _parse(events: list, now: datetime) -> List[Match]:
    out: List[Match] = []
    for e in events:
        try:
            kickoff = datetime.fromisoformat(e["date"].replace("Z", "+00:00"))
            comp = e["competitions"][0]
        except (KeyError, ValueError, IndexError):
            continue
        state = comp.get("status", {}).get("type", {}).get("state")
        if state != "pre" or kickoff < now:
            continue
        out.append(
            Match(
                name=e.get("name", "TBD"),
                kickoff=kickoff,
                venue=(comp.get("venue") or {}).get("fullName"),
            )
        )
    out.sort(key=lambda m: m.kickoff)
    return out


def get_upcoming_matches(
    *, limit: int = 6, days: int = 60, timeout: float = 12.0
) -> List[Match]:
    """Return up to ``limit`` upcoming MLS matches within ``days`` from now."""
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=days)
    params = {
        "dates": f"{now:%Y%m%d}-{end:%Y%m%d}",
        "limit": 200,
    }
    try:
        resp = requests.get(_URL, params=params, headers=_HEADERS, timeout=timeout)
        resp.raise_for_status()
        events = resp.json().get("events") or []
    except requests.RequestException as exc:
        raise NoMatchesAvailable(str(exc)) from exc

    return _parse(events, now)[:limit]


if __name__ == "__main__":
    try:
        matches = get_upcoming_matches()
        if not matches:
            print("No upcoming MLS matches found.")
        for m in matches:
            venue = f"  @ {m.venue}" if m.venue else ""
            print(f"{m.local_str()}  —  {m.name}{venue}")
    except NoMatchesAvailable as e:
        print(f"Could not fetch fixtures: {e}")
