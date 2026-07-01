"""Pre-match stats preview for an upcoming game.

For a team query, finds that team's next fixture (MLS or World Cup) and
builds a preview:
  - passing + possession, averaged over each team's last N games
  - corners per game, averaged over each team's last N games
  - the result of the two teams' most recent prior meeting (H2H)

All data is from ESPN's public JSON API (fixtures, match summaries, and
per-match boxscores). No key required. Season corner totals aren't
tracked for MLS, so we average recent per-match boxscores instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import requests

from soccer import Match, get_upcoming_matches

_HEADERS = {"User-Agent": "Mozilla/5.0"}
_SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/summary"

# Competitions to search for the team's next match (active first).
_SEARCH = [("fifa.world", "FIFA World Cup"), ("usa.1", "MLS")]
_RECENT_N = 3


class StatsUnavailable(Exception):
    pass


@dataclass
class TeamForm:
    name: str
    pass_pct: Optional[float]
    possession: Optional[float]
    corners: Optional[float]
    games: int


@dataclass
class LastMeeting:
    date: datetime
    summary: str  # e.g. "CF Montréal 1-1 Toronto FC"
    competition: str


@dataclass
class StatsPreview:
    match: Match
    league_label: str
    home_form: TeamForm
    away_form: TeamForm
    last_meeting: Optional[LastMeeting]


def _num(stat: dict) -> Optional[float]:
    if stat is None:
        return None
    v = stat.get("value")
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(stat.get("displayValue", "")).replace("%", ""))
    except (TypeError, ValueError):
        return None


def _summary(league: str, event_id: str, timeout: float) -> dict:
    resp = requests.get(
        _SUMMARY.format(league=league),
        params={"event": event_id},
        headers=_HEADERS,
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()


def _team_box_stats(summary: dict, team_id: str) -> Optional[Dict[str, float]]:
    for t in summary.get("boxscore", {}).get("teams", []):
        if str((t.get("team") or {}).get("id")) != str(team_id):
            continue
        by_name = {s.get("name"): s for s in t.get("statistics", [])}
        return {
            "pass_pct": _num(by_name.get("passPct")),
            "possession": _num(by_name.get("possessionPct")),
            "corners": _num(by_name.get("wonCorners")),
        }
    return None


def _recent_event_ids(last_five: list, team_id: str, n: int) -> List[str]:
    for entry in last_five:
        if str((entry.get("team") or {}).get("id")) == str(team_id):
            return [str(e.get("id")) for e in entry.get("events", []) if e.get("id")][:n]
    return []


def _team_form(
    league: str, team_id: str, name: str, event_ids: List[str], timeout: float
) -> TeamForm:
    passes, poss, corners = [], [], []
    used = 0
    for eid in event_ids:
        if used >= _RECENT_N:
            break
        try:
            box = _team_box_stats(_summary(league, eid, timeout), team_id)
        except requests.RequestException:
            continue
        # A valid boxscore always has real possession; 0/None means the game
        # has no stats recorded (common for some internationals) — skip it.
        if not box or not box["possession"]:
            continue
        used += 1
        poss.append(box["possession"])
        if box["pass_pct"]:
            # passPct comes as a 0-1 fraction in match boxscores.
            passes.append(box["pass_pct"] * 100 if box["pass_pct"] <= 1 else box["pass_pct"])
        if box["corners"] is not None:
            corners.append(box["corners"])

    def avg(xs):
        return round(sum(xs) / len(xs), 1) if xs else None

    return TeamForm(
        name=name,
        pass_pct=avg(passes),
        possession=avg(poss),
        corners=avg(corners),
        games=used,
    )


def _last_meeting(summary: dict) -> Optional[LastMeeting]:
    h2h = summary.get("headToHeadGames") or []
    if not h2h:
        return None
    events = h2h[0].get("events") or []
    best = None
    for ev in events:
        try:
            d = datetime.fromisoformat(ev["gameDate"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        if best is None or d > best[0]:
            best = (d, ev)
    if not best:
        return None
    d, ev = best
    home = h2h[0]["team"]
    opp = ev.get("opponent", {})
    # Determine home/away display for the meeting.
    if str(ev.get("homeTeamId")) == str(home.get("id")):
        left, right = home.get("displayName"), opp.get("displayName")
    else:
        left, right = opp.get("displayName"), home.get("displayName")
    line = f"{left} {ev.get('homeTeamScore')}-{ev.get('awayTeamScore')} {right}"
    return LastMeeting(date=d, summary=line, competition=ev.get("competitionName", ""))


def _find_next_match(query: str, timeout: float) -> Optional[Tuple[Match, str, str]]:
    best = None
    for slug, label in _SEARCH:
        try:
            ms = get_upcoming_matches(team=query, league=slug, limit=1, timeout=timeout)
        except Exception:
            ms = []
        if ms and (best is None or ms[0].kickoff < best[0].kickoff):
            best = (ms[0], slug, label)
    return best


def get_stats_preview(query: str, *, timeout: float = 12.0) -> StatsPreview:
    query = query.strip()
    if not query:
        raise StatsUnavailable("no team given")

    found = _find_next_match(query, timeout)
    if not found:
        raise StatsUnavailable(f"no upcoming match found for '{query}'")
    match, slug, label = found

    if not match.event_id:
        raise StatsUnavailable("match has no id for stats lookup")

    try:
        summary = _summary(slug, match.event_id, timeout)
    except requests.RequestException as exc:
        raise StatsUnavailable(str(exc)) from exc

    # Pull a wider pool (5) so we can skip games with no recorded stats and
    # still land on _RECENT_N valid ones.
    last_five = summary.get("lastFiveGames") or []
    home_ids = _recent_event_ids(last_five, match.home_id, 5)
    away_ids = _recent_event_ids(last_five, match.away_id, 5)

    home_form = _team_form(slug, match.home_id, match.home, home_ids, timeout)
    away_form = _team_form(slug, match.away_id, match.away, away_ids, timeout)
    last_meeting = _last_meeting(summary)

    return StatsPreview(match, label, home_form, away_form, last_meeting)


if __name__ == "__main__":
    import sys

    q = " ".join(sys.argv[1:]) or "seattle"
    try:
        p = get_stats_preview(q)
        m = p.match
        print(f"{m.home} vs {m.away}  ({p.league_label})  {m.when_str()}")
        for f in (p.home_form, p.away_form):
            print(
                f"  {f.name}: pass {f.pass_pct}% · poss {f.possession}% · "
                f"corners {f.corners}/g  (last {f.games})"
            )
        if p.last_meeting:
            lm = p.last_meeting
            print(f"  Last meeting: {lm.date:%b %d, %Y} — {lm.summary} ({lm.competition})")
        else:
            print("  Last meeting: none on record")
    except StatsUnavailable as e:
        print(f"stats unavailable: {e}")
