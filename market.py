"""Market-data lookup using Yahoo Finance's public chart endpoint.

No API key required. Yahoo aggregates quotes across exchanges
(NASDAQ, NYSE, AMEX, etc.), so a plain ticker like ``NVDA`` resolves
to its listing automatically.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import requests

# Yahoo will 429 / 403 requests that look like bots. Oddly, a *minimal* UA is
# accepted while some full desktop-browser UA strings get throttled.
_HEADERS = {"User-Agent": "Mozilla/5.0"}

# Yahoo load-balances across these hosts; one may 429 while the other is fine,
# so we try them in turn.
_HOSTS = ("query2.finance.yahoo.com", "query1.finance.yahoo.com")
_CHART_PATH = "/v8/finance/chart/{symbol}"


class TickerNotFound(Exception):
    """Raised when Yahoo has no data for the requested symbol."""


@dataclass
class Quote:
    symbol: str
    name: Optional[str]
    exchange: Optional[str]
    currency: str
    price: float
    previous_close: float

    @property
    def change(self) -> float:
        return self.price - self.previous_close

    @property
    def change_percent(self) -> float:
        if not self.previous_close:
            return 0.0
        return (self.change / self.previous_close) * 100


def _fetch(symbol: str, timeout: float) -> dict:
    """GET the chart payload, trying each host and retrying on rate limits."""
    path = _CHART_PATH.format(symbol=requests.utils.quote(symbol))
    params = {"range": "1d", "interval": "1d"}
    last_exc: Optional[Exception] = None

    for attempt in range(3):
        for host in _HOSTS:
            try:
                resp = requests.get(
                    f"https://{host}{path}",
                    params=params,
                    headers=_HEADERS,
                    timeout=timeout,
                )
            except requests.RequestException as exc:
                last_exc = exc
                continue

            # 404 = genuinely unknown symbol; don't bother retrying other hosts.
            if resp.status_code == 404:
                raise TickerNotFound(symbol)
            # 429/5xx = transient; fall through to the next host/attempt.
            if resp.status_code in (429, 500, 502, 503):
                last_exc = requests.HTTPError(f"{resp.status_code} from {host}")
                continue
            resp.raise_for_status()
            return resp.json()

        time.sleep(0.5 * (attempt + 1))  # brief backoff before retrying

    raise requests.HTTPError(
        f"market data unavailable for {symbol}"
    ) from last_exc


def get_quote(symbol: str, *, timeout: float = 10.0) -> Quote:
    """Fetch a single quote. Raises ``TickerNotFound`` for unknown symbols."""
    symbol = symbol.strip().upper()
    if not symbol:
        raise TickerNotFound("(empty)")

    payload = _fetch(symbol, timeout)
    chart = payload.get("chart") or {}
    if chart.get("error"):
        raise TickerNotFound(symbol)

    results = chart.get("result") or []
    if not results:
        raise TickerNotFound(symbol)

    meta = results[0].get("meta") or {}

    price = meta.get("regularMarketPrice")
    prev_close = meta.get("chartPreviousClose", meta.get("previousClose"))
    if price is None or prev_close is None:
        raise TickerNotFound(symbol)

    return Quote(
        symbol=meta.get("symbol", symbol),
        name=meta.get("longName") or meta.get("shortName"),
        exchange=meta.get("fullExchangeName") or meta.get("exchangeName"),
        currency=meta.get("currency", "USD"),
        price=float(price),
        previous_close=float(prev_close),
    )


if __name__ == "__main__":
    import sys

    sym = sys.argv[1] if len(sys.argv) > 1 else "NVDA"
    try:
        q = get_quote(sym)
        sign = "+" if q.change >= 0 else ""
        print(
            f"{q.symbol} ({q.exchange}): {q.price:.2f} {q.currency}  "
            f"{sign}{q.change:.2f} ({sign}{q.change_percent:.2f}%)"
        )
    except TickerNotFound as e:
        print(f"Ticker not found: {e}")
