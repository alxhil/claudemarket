"""Top daily gainers and losers via Yahoo Finance's predefined screeners.

No API key required. Uses the same minimal-UA + host-fallback approach as
market.py.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List, Optional

import requests

_HEADERS = {"User-Agent": "Mozilla/5.0"}
_HOSTS = ("query2.finance.yahoo.com", "query1.finance.yahoo.com")
_PATH = "/v1/finance/screener/predefined/saved"


class MoversUnavailable(Exception):
    pass


@dataclass
class Mover:
    symbol: str
    name: Optional[str]
    price: Optional[float]
    change_percent: Optional[float]


def _screener(scr_id: str, count: int, timeout: float) -> List[Mover]:
    params = {"count": count, "scrIds": scr_id}
    last_exc: Optional[Exception] = None
    for attempt in range(3):
        for host in _HOSTS:
            try:
                resp = requests.get(
                    f"https://{host}{_PATH}",
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
            result = (resp.json().get("finance", {}).get("result") or [{}])[0]
            quotes = result.get("quotes") or []
            return [
                Mover(
                    symbol=q.get("symbol"),
                    name=q.get("shortName") or q.get("longName"),
                    price=q.get("regularMarketPrice"),
                    change_percent=q.get("regularMarketChangePercent"),
                )
                for q in quotes
                if q.get("symbol")
            ][:count]
        time.sleep(0.5 * (attempt + 1))
    raise MoversUnavailable(f"screener {scr_id} unavailable") from last_exc


def get_movers(*, count: int = 5, timeout: float = 12.0):
    """Return (gainers, losers) — each a list of up to ``count`` Movers."""
    gainers = _screener("day_gainers", count, timeout)
    losers = _screener("day_losers", count, timeout)
    return gainers, losers


if __name__ == "__main__":
    g, l = get_movers()
    for title, rows in (("GAINERS", g), ("LOSERS", l)):
        print(f"=== {title} ===")
        for m in rows:
            print(
                f"  {m.change_percent:+.2f}%  {m.symbol:<6} "
                f"${m.price:,.2f}  {m.name}"
            )
