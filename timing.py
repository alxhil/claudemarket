"""Timing signal for a stock: what to do NOW and at what levels.

Combines the long-term trend regime with the short-term state:

  Regime (200-day SMA + 50/200 cross): uptrend / downtrend / mixed
  State (RSI-14 + distance from the 50-day SMA): dip / neutral / extended

and maps the combination to an actionable call:

  Uptrend   + dip       -> BUY NOW (pullback in an uptrend)
  Uptrend   + neutral   -> BUY THE DIP (wait for the pullback zone)
  Uptrend   + extended  -> TAKE PROFITS (sell into strength near peak)
  Downtrend + extended  -> SELL NOW (rally in a downtrend)
  Downtrend + neutral   -> SELL / AVOID
  Downtrend + dip       -> WAIT (oversold, but the trend is down)
  Mixed     + any       -> HOLD / WAIT for confirmation

Also reports the levels the call is based on: the dip-buy zone (50-day
SMA and recent support), the profit zone (recent high), and the trend
line (200-day SMA). Automated indicator logic — not financial advice.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

from technicals import (
    ReviewUnavailable,
    TickerNotFound,
    _fetch,
    _macd,
    _rsi,
    _sma,
)

RSI_DIP = 40
RSI_EXTENDED = 70
RSI_BEAR_RALLY = 60
EXTENDED_ABOVE_50D = 0.10  # >10% above the 50-day SMA counts as extended


@dataclass
class TimingCall:
    symbol: str
    name: Optional[str]
    as_of: str
    price: float
    currency: str
    call: str          # short actionable headline
    detail: str        # one-sentence why
    regime: str        # "uptrend" | "downtrend" | "mixed"
    state: str         # "dip" | "neutral" | "extended"
    reasons: List[str]
    buy_zone: Optional[str]
    profit_zone: Optional[str]
    trend_line: Optional[str]


def compute_timing(symbol: str, *, timeout: float = 12.0) -> TimingCall:
    symbol = symbol.strip().upper()
    if not symbol:
        raise TickerNotFound("(empty)")

    result = _fetch(symbol, timeout)
    meta = result.get("meta") or {}
    ts = result.get("timestamp") or []
    quote = (result.get("indicators", {}).get("quote") or [{}])[0]
    closes = [c for c in (quote.get("close") or []) if c is not None]
    highs = [h for h in (quote.get("high") or []) if h is not None]
    lows = [l for l in (quote.get("low") or []) if l is not None]
    if len(closes) < 60:
        raise ReviewUnavailable(f"not enough history for {symbol}")

    price = closes[-1]
    as_of = (
        datetime.fromtimestamp(ts[-1], tz=timezone.utc).date().isoformat()
        if ts
        else "latest"
    )
    sma50 = _sma(closes, 50)
    sma200 = _sma(closes, 200)
    rsi = _rsi(closes)
    macd = _macd(closes)
    recent_high = max(highs[-20:]) if highs else None
    recent_low = min(lows[-20:]) if lows else None

    reasons: List[str] = []

    # ---- Regime ---------------------------------------------------------
    if sma200 and price > sma200 and (not sma50 or sma50 >= sma200):
        regime = "uptrend"
        reasons.append(f"Price is above the 200-day SMA ({sma200:,.2f})")
        if sma50 and sma50 >= sma200:
            reasons.append("50-day SMA is above the 200-day (golden cross)")
    elif sma200 and price < sma200 and (not sma50 or sma50 <= sma200):
        regime = "downtrend"
        reasons.append(f"Price is below the 200-day SMA ({sma200:,.2f})")
        if sma50 and sma50 <= sma200:
            reasons.append("50-day SMA is below the 200-day (death cross)")
    else:
        regime = "mixed"
        reasons.append("Trend signals disagree (price and 50/200 SMAs are crossed up)")

    # ---- Short-term state -------------------------------------------------
    dist50 = price / sma50 - 1 if sma50 else 0.0
    if (rsi is not None and rsi <= RSI_DIP) or dist50 < -0.03:
        state = "dip"
        if rsi is not None and rsi <= RSI_DIP:
            reasons.append(f"RSI {rsi:.0f} — pulled back")
        if dist50 < -0.03:
            reasons.append(f"{dist50:+.1%} vs the 50-day SMA")
    elif (rsi is not None and rsi >= RSI_EXTENDED) or dist50 > EXTENDED_ABOVE_50D:
        state = "extended"
        if rsi is not None and rsi >= RSI_EXTENDED:
            reasons.append(f"RSI {rsi:.0f} — overbought")
        if dist50 > EXTENDED_ABOVE_50D:
            reasons.append(f"{dist50:+.1%} above the 50-day SMA — stretched")
    else:
        state = "neutral"
        if rsi is not None:
            reasons.append(f"RSI {rsi:.0f} — neither stretched nor washed out")

    if macd:
        line, sig = macd
        reasons.append(
            "MACD is above its signal line (momentum improving)"
            if line > sig
            else "MACD is below its signal line (momentum fading)"
        )

    # ---- The call ---------------------------------------------------------
    if regime == "uptrend":
        if state == "dip":
            call = "BUY NOW"
            detail = "A pullback within an intact uptrend — historically the highest-odds entry."
        elif state == "extended":
            call = "TAKE PROFITS"
            detail = "Uptrend intact but stretched — selling into strength captures the peak zone."
        else:
            call = "BUY THE DIP"
            detail = "Uptrend is healthy but there's no discount — a better entry is the pullback zone below."
    elif regime == "downtrend":
        if state == "extended":
            call = "SELL NOW"
            detail = "A rally inside a downtrend — bounces like this tend to fade."
        elif state == "dip":
            call = "WAIT"
            detail = "Oversold, but the trend is still down — don't catch the falling knife."
        else:
            call = "SELL / AVOID"
            detail = "Downtrend with no washout — trend rules say stand aside or reduce."
    else:
        if state == "extended":
            call = "TAKE PROFITS"
            detail = "No clear trend and short-term stretched — risk/reward favors trimming."
        else:
            call = "HOLD / WAIT"
            detail = "Trend signals are mixed — wait for the 50/200 picture to resolve."

    fmt = lambda v: f"{v:,.2f}" if v is not None else None
    buy_zone = None
    if sma50 and recent_low is not None:
        lo, hi = sorted((recent_low, sma50))
        buy_zone = f"{fmt(lo)} – {fmt(hi)}  (recent support to 50-day SMA)"
    profit_zone = f"{fmt(recent_high)}  (20-day high)" if recent_high else None
    trend_line = f"{fmt(sma200)}  (200-day SMA)" if sma200 else None

    return TimingCall(
        symbol=meta.get("symbol", symbol),
        name=meta.get("longName") or meta.get("shortName"),
        as_of=as_of,
        price=price,
        currency=meta.get("currency", "USD"),
        call=call,
        detail=detail,
        regime=regime,
        state=state,
        reasons=reasons,
        buy_zone=buy_zone,
        profit_zone=profit_zone,
        trend_line=trend_line,
    )


if __name__ == "__main__":
    import sys

    sym = sys.argv[1] if len(sys.argv) > 1 else "NVDA"
    try:
        t = compute_timing(sym)
        print(f"{t.symbol} ({t.name})  {t.price:,.2f} {t.currency}  as of {t.as_of}")
        print(f"CALL: {t.call}  [{t.regime} / {t.state}]")
        print(f"  {t.detail}")
        for r in t.reasons:
            print(f"  - {r}")
        print(f"  buy zone:    {t.buy_zone}")
        print(f"  profit zone: {t.profit_zone}")
        print(f"  trend line:  {t.trend_line}")
    except TickerNotFound as e:
        print(f"ticker not found: {e}")
