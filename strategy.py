"""QQQ trend-following strategy signal.

Rules (evaluated weekly, at Friday's close):

- Hold QQQ while it closes at least 1% ABOVE its 200-day simple moving
  average.
- When QQQ closes more than 1% BELOW the 200-day SMA, move to the
  defensive asset with the best 3/6/12-month blended momentum out of
  GLD / IEF / SHY — or BIL as the cash fallback when none of them has
  positive momentum.
- Inside the +/-1% band, keep the current position (hysteresis — this
  prevents whipsaw churn when price hugs the average). With no prior
  position, the band resolves defensively: QQQ requires a close at
  least 1% above the SMA.

This module only produces a SIGNAL for Discord. It does not (and must
not) place trades.

Position state persists in strategy_state.json next to this file; only
commit() writes the position — compute_signal() is always read-only.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import requests

RISK_ASSET = "QQQ"
DEFENSIVE_ASSETS = ["GLD", "IEF", "SHY"]
CASH_ASSET = "BIL"
BAND = 0.01  # 1% hysteresis around the SMA
SMA_DAYS = 200
MOMENTUM_DAYS = (63, 126, 252)  # ~3, 6, 12 months of trading days

_HEADERS = {"User-Agent": "Mozilla/5.0"}
_HOSTS = ("query2.finance.yahoo.com", "query1.finance.yahoo.com")
_CHART = "/v8/finance/chart/{symbol}"

STATE_PATH = Path(__file__).resolve().parent / "strategy_state.json"


class StrategyError(Exception):
    pass


# --------------------------------------------------------------------------
# Data


def get_closes(symbol: str, *, range_: str = "2y", timeout: float = 12.0):
    """Daily closes as (as_of_date_str, [floats]) with host fallback."""
    params = {"range": range_, "interval": "1d"}
    last_exc: Optional[Exception] = None
    for attempt in range(3):
        for host in _HOSTS:
            try:
                resp = requests.get(
                    f"https://{host}{_CHART.format(symbol=symbol)}",
                    params=params,
                    headers=_HEADERS,
                    timeout=timeout,
                )
            except requests.RequestException as exc:
                last_exc = exc
                continue
            if resp.status_code in (429, 500, 502, 503):
                last_exc = requests.HTTPError(f"{resp.status_code} from {host}")
                continue
            resp.raise_for_status()
            result = (resp.json().get("chart", {}).get("result") or [None])[0]
            if not result:
                raise StrategyError(f"no chart data for {symbol}")
            ts = result.get("timestamp") or []
            raw = (result.get("indicators", {}).get("quote") or [{}])[0].get(
                "close"
            ) or []
            closes = [c for c in raw if c is not None]
            if not closes:
                raise StrategyError(f"no closes for {symbol}")
            as_of = datetime.fromtimestamp(ts[-1], tz=timezone.utc).date().isoformat()
            return as_of, closes
        time.sleep(0.5 * (attempt + 1))
    raise StrategyError(f"market data unavailable for {symbol}") from last_exc


def blended_momentum(closes: List[float]) -> Optional[float]:
    """Average of 3/6/12-month returns (whatever windows the data allows)."""
    rets = []
    for d in MOMENTUM_DAYS:
        if len(closes) > d and closes[-1 - d] > 0:
            rets.append(closes[-1] / closes[-1 - d] - 1)
    return sum(rets) / len(rets) if rets else None


# --------------------------------------------------------------------------
# State


def load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2) + "\n")


# --------------------------------------------------------------------------
# Signal


@dataclass
class Signal:
    as_of: str
    close: float
    sma200: float
    distance_pct: float  # close vs SMA, in percent
    target: str
    previous: Optional[str]
    action: str  # "HOLD" | "ENTER" | "SWITCH"
    in_band: bool
    defensive_scores: Dict[str, float] = field(default_factory=dict)

    def headline(self) -> str:
        if self.action == "HOLD":
            return f"SIGNAL: HOLD {self.target}"
        if self.action == "ENTER":
            return f"SIGNAL: BUY {self.target}"
        return f"SIGNAL: SELL {self.previous} BUY {self.target}"


def _pick_defensive(timeout: float) -> tuple[str, Dict[str, float]]:
    scores: Dict[str, float] = {}
    for sym in DEFENSIVE_ASSETS:
        try:
            _, closes = get_closes(sym, timeout=timeout)
        except (StrategyError, requests.RequestException):
            continue
        mom = blended_momentum(closes)
        if mom is not None:
            scores[sym] = mom
    if scores:
        best = max(scores, key=scores.get)
        if scores[best] > 0:
            return best, scores
    return CASH_ASSET, scores


def compute_signal(state: dict, *, timeout: float = 12.0) -> Signal:
    """Evaluate the rules. Read-only — never writes state."""
    as_of, closes = get_closes(RISK_ASSET, timeout=timeout)
    if len(closes) < SMA_DAYS:
        raise StrategyError(
            f"only {len(closes)} closes for {RISK_ASSET}; need {SMA_DAYS}"
        )
    sma = sum(closes[-SMA_DAYS:]) / SMA_DAYS
    close = closes[-1]
    dist = close / sma - 1
    previous = state.get("last_target")

    in_band = -BAND < dist < BAND
    scores: Dict[str, float] = {}

    if dist >= BAND:
        target = RISK_ASSET
    elif dist <= -BAND:
        target, scores = _pick_defensive(timeout)
    elif previous:
        target = previous  # hysteresis: no change inside the band
        if previous != RISK_ASSET:
            _, scores = _pick_defensive(timeout)
            # Keep holding the previously chosen defensive asset; scores are
            # informational only inside the band.
            target = previous
    else:
        # No prior position and inside the band: entering QQQ requires the
        # full +1% margin, so start defensive.
        target, scores = _pick_defensive(timeout)

    if previous is None:
        action = "ENTER"
    elif target == previous:
        action = "HOLD"
    else:
        action = "SWITCH"

    return Signal(
        as_of=as_of,
        close=close,
        sma200=sma,
        distance_pct=dist * 100,
        target=target,
        previous=previous,
        action=action,
        in_band=in_band,
        defensive_scores=scores,
    )


def commit(state: dict, sig: Signal) -> None:
    """Persist the position after a real (non-preview) run."""
    state["last_target"] = sig.target
    state["last_run"] = sig.as_of
    save_state(state)


if __name__ == "__main__":
    sig = compute_signal(load_state())
    print(f"as of close {sig.as_of}")
    print(
        f"{RISK_ASSET} {sig.close:,.2f} vs 200d SMA {sig.sma200:,.2f} "
        f"({sig.distance_pct:+.1f}%){' [in band]' if sig.in_band else ''}"
    )
    if sig.defensive_scores:
        for s, v in sorted(sig.defensive_scores.items(), key=lambda kv: -kv[1]):
            print(f"  {s} blended momentum {v:+.2%}")
    print(f"{sig.headline()} (dry run — state unchanged)")
