"""Persistent signal tracker.

Stores which tickers are being watched, which channel alerts go to, and
the last timing call seen for each — so the background loop can post an
alert only when a call CHANGES (e.g. BUY THE DIP -> TAKE PROFITS).

State lives in tracker_state.json next to this file (git-ignored).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

STATE_PATH = Path(__file__).resolve().parent / "tracker_state.json"
MAX_TRACKED = 12  # keeps the 10-minute loop light on Yahoo


def load_state() -> Dict:
    try:
        state = json.loads(STATE_PATH.read_text())
    except (OSError, ValueError):
        state = {}
    state.setdefault("tickers", {})
    return state


def save_state(state: Dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2) + "\n")


def add(state: Dict, symbol: str, channel_id: int, call: str) -> None:
    state["tickers"][symbol.upper()] = {
        "channel_id": channel_id,
        "last_call": call,
        "added": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    save_state(state)


def remove(state: Dict, symbol: str) -> bool:
    entry = state["tickers"].pop(symbol.upper(), None)
    if entry is not None:
        save_state(state)
        return True
    return False


def update_call(state: Dict, symbol: str, call: str) -> Optional[str]:
    """Record the latest call; return the previous one if it changed."""
    entry = state["tickers"].get(symbol.upper())
    if entry is None:
        return None
    previous = entry.get("last_call")
    if previous != call:
        entry["last_call"] = call
        save_state(state)
        return previous
    return None
