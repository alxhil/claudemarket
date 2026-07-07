"""Technical-analysis review for a stock.

Computes standard indicators from Yahoo daily OHLCV data and rolls them
into a Buy / Hold / Sell verdict:

  - Trend: price vs 50-day and 200-day SMA, and SMA50 vs SMA200
    (golden/death cross)
  - Momentum: 1-month return, MACD(12,26,9) vs its signal line
  - RSI(14): overbought / oversold
  - 52-week range position
  - Volume: latest vs 20-day average

Each point votes +1 (bullish), -1 (bearish), or 0 (neutral); the blended
score maps to the verdict. This is an automated indicator summary, not
financial advice.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Tuple

import requests

_HEADERS = {"User-Agent": "Mozilla/5.0"}
_HOSTS = ("query2.finance.yahoo.com", "query1.finance.yahoo.com")
_CHART = "/v8/finance/chart/{symbol}"

BUY_THRESHOLD = 0.25   # score >= +0.25 -> Buy
SELL_THRESHOLD = -0.25  # score <= -0.25 -> Sell


class ReviewUnavailable(Exception):
    pass


class TickerNotFound(Exception):
    pass


@dataclass
class Point:
    label: str
    detail: str
    vote: int  # +1 bullish, 0 neutral, -1 bearish


@dataclass
class Review:
    symbol: str
    name: Optional[str]
    as_of: str
    price: float
    currency: str
    points: List[Point]
    score: float  # -1..+1
    verdict: str  # "Buy" | "Hold" | "Sell"


def _fetch(symbol: str, timeout: float):
    params = {"range": "2y", "interval": "1d"}
    last_exc: Optional[Exception] = None
    for attempt in range(3):
        for host in _HOSTS:
            try:
                resp = requests.get(
                    f"https://{host}{_CHART.format(symbol=requests.utils.quote(symbol))}",
                    params=params,
                    headers=_HEADERS,
                    timeout=timeout,
                )
            except requests.RequestException as exc:
                last_exc = exc
                continue
            if resp.status_code == 404:
                raise TickerNotFound(symbol)
            if resp.status_code in (429, 500, 502, 503):
                last_exc = requests.HTTPError(f"{resp.status_code} from {host}")
                continue
            resp.raise_for_status()
            chart = resp.json().get("chart") or {}
            if chart.get("error"):
                raise TickerNotFound(symbol)
            result = (chart.get("result") or [None])[0]
            if not result:
                raise TickerNotFound(symbol)
            return result
        time.sleep(0.5 * (attempt + 1))
    raise ReviewUnavailable(f"market data unavailable for {symbol}") from last_exc


def _sma(xs: List[float], n: int) -> Optional[float]:
    return sum(xs[-n:]) / n if len(xs) >= n else None


def _ema_series(xs: List[float], n: int) -> List[float]:
    k = 2 / (n + 1)
    out = [xs[0]]
    for x in xs[1:]:
        out.append(x * k + out[-1] * (1 - k))
    return out


def _rsi(closes: List[float], n: int = 14) -> Optional[float]:
    if len(closes) < n + 1:
        return None
    gains = losses = 0.0
    for i in range(1, n + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0)
        losses += max(-d, 0)
    avg_gain, avg_loss = gains / n, losses / n
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        avg_gain = (avg_gain * (n - 1) + max(d, 0)) / n
        avg_loss = (avg_loss * (n - 1) + max(-d, 0)) / n
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def _macd(closes: List[float]) -> Optional[Tuple[float, float]]:
    """Return (macd_line, signal_line) for MACD(12,26,9)."""
    if len(closes) < 35:
        return None
    macd_line = [
        f - s for f, s in zip(_ema_series(closes, 12), _ema_series(closes, 26))
    ]
    signal = _ema_series(macd_line[25:], 9)  # skip the EMA warm-up region
    return macd_line[-1], signal[-1]


def compute_review(symbol: str, *, timeout: float = 12.0) -> Review:
    symbol = symbol.strip().upper()
    if not symbol:
        raise TickerNotFound("(empty)")

    result = _fetch(symbol, timeout)
    meta = result.get("meta") or {}
    ts = result.get("timestamp") or []
    quote = (result.get("indicators", {}).get("quote") or [{}])[0]
    rows = [
        (c, h, l, v)
        for c, h, l, v in zip(
            quote.get("close") or [],
            quote.get("high") or [],
            quote.get("low") or [],
            quote.get("volume") or [],
        )
        if c is not None
    ]
    if len(rows) < 60:
        raise ReviewUnavailable(f"not enough history for {symbol}")

    closes = [r[0] for r in rows]
    highs = [r[1] for r in rows if r[1] is not None]
    lows = [r[2] for r in rows if r[2] is not None]
    volumes = [r[3] for r in rows if r[3] is not None]

    price = closes[-1]
    as_of = (
        datetime.fromtimestamp(ts[-1], tz=timezone.utc).date().isoformat()
        if ts
        else "latest"
    )
    points: List[Point] = []

    # --- Trend ---------------------------------------------------------
    sma50, sma200 = _sma(closes, 50), _sma(closes, 200)
    if sma50:
        d = price / sma50 - 1
        points.append(
            Point(
                "Price vs 50-day SMA",
                f"{d:+.1%} ({'above' if d >= 0 else 'below'} {sma50:,.2f})",
                1 if d > 0.01 else -1 if d < -0.01 else 0,
            )
        )
    if sma200:
        d = price / sma200 - 1
        points.append(
            Point(
                "Price vs 200-day SMA",
                f"{d:+.1%} ({'above' if d >= 0 else 'below'} {sma200:,.2f})",
                1 if d > 0.01 else -1 if d < -0.01 else 0,
            )
        )
    if sma50 and sma200:
        cross_up = sma50 > sma200
        points.append(
            Point(
                "50/200 cross",
                "golden cross (50d above 200d)" if cross_up else "death cross (50d below 200d)",
                1 if cross_up else -1,
            )
        )

    # --- Momentum ------------------------------------------------------
    if len(closes) > 21:
        m1 = price / closes[-22] - 1
        points.append(
            Point(
                "1-month momentum",
                f"{m1:+.1%}",
                1 if m1 > 0.02 else -1 if m1 < -0.02 else 0,
            )
        )
    macd = _macd(closes)
    if macd:
        line, sig = macd
        points.append(
            Point(
                "MACD (12,26,9)",
                f"{line:+.2f} vs signal {sig:+.2f} — "
                + ("bullish crossover" if line > sig else "bearish crossover"),
                1 if line > sig else -1,
            )
        )

    # --- RSI -----------------------------------------------------------
    rsi = _rsi(closes)
    if rsi is not None:
        if rsi >= 70:
            desc, vote = "overbought", -1
        elif rsi <= 30:
            desc, vote = "oversold", 1
        else:
            desc, vote = "neutral", 0
        points.append(Point("RSI (14)", f"{rsi:.0f} — {desc}", vote))

    # --- 52-week range ---------------------------------------------------
    if highs and lows:
        yr_high, yr_low = max(highs[-252:]), min(lows[-252:])
        if yr_high > yr_low:
            pos = (price - yr_low) / (yr_high - yr_low)
            points.append(
                Point(
                    "52-week range",
                    f"{pos:.0%} of range ({yr_low:,.2f} – {yr_high:,.2f})",
                    1 if pos > 0.7 else -1 if pos < 0.3 else 0,
                )
            )

    # --- Volume ----------------------------------------------------------
    if len(volumes) >= 21 and volumes[-1]:
        avg20 = sum(volumes[-21:-1]) / 20
        if avg20:
            ratio = volumes[-1] / avg20
            points.append(
                Point(
                    "Volume vs 20-day avg",
                    f"{ratio:.1f}x average",
                    0,  # informational — direction depends on price action
                )
            )

    votes = [p.vote for p in points]
    score = sum(votes) / max(1, len(votes))
    if score >= BUY_THRESHOLD:
        verdict = "Buy"
    elif score <= SELL_THRESHOLD:
        verdict = "Sell"
    else:
        verdict = "Hold"

    return Review(
        symbol=meta.get("symbol", symbol),
        name=meta.get("longName") or meta.get("shortName"),
        as_of=as_of,
        price=price,
        currency=meta.get("currency", "USD"),
        points=points,
        score=score,
        verdict=verdict,
    )


if __name__ == "__main__":
    import sys

    sym = sys.argv[1] if len(sys.argv) > 1 else "NVDA"
    try:
        r = compute_review(sym)
        print(f"{r.symbol} ({r.name})  {r.price:,.2f} {r.currency}  as of {r.as_of}")
        for p in r.points:
            mark = "+" if p.vote > 0 else "-" if p.vote < 0 else "."
            print(f"  [{mark}] {p.label}: {p.detail}")
        print(f"VERDICT: {r.verdict}  (score {r.score:+.2f})")
    except TickerNotFound as e:
        print(f"ticker not found: {e}")
