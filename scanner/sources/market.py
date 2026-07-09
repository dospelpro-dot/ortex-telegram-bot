"""Market data: price, recent move, relative volume, RSI, liquidity, cap.

Prefers Polygon when POLYGON_API_KEY is set, otherwise falls back to
yfinance (no key required). All methods are defensive: on any failure
they return None so the pipeline can skip the name rather than crash.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import requests

import config

log = logging.getLogger("scanner.market")


@dataclass
class MarketSnapshot:
    symbol: str
    price: float
    prior_move_pct: float          # % change over the lookback window (recent run-up)
    rel_volume: float              # today's volume / avg volume
    rsi14: float                   # 14-period RSI (overbought detector)
    avg_dollar_volume: float       # liquidity gate
    market_cap: float | None       # size gate (None if unknown)


def _rsi(closes: list[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    gains, losses = 0.0, 0.0
    for i in range(-period, 0):
        chg = closes[i] - closes[i - 1]
        if chg >= 0:
            gains += chg
        else:
            losses -= chg
    if losses == 0:
        return 100.0
    rs = (gains / period) / (losses / period)
    return 100.0 - (100.0 / (1.0 + rs))


class MarketData:
    def __init__(self) -> None:
        self.polygon_key = config.POLYGON_API_KEY
        self._yf = None
        if not self.polygon_key:
            try:
                import yfinance  # noqa: F401
                self._yf = yfinance
            except ImportError:
                log.warning("yfinance not installed and no POLYGON_API_KEY; market data disabled")

    def snapshot(self, symbol: str, lookback: int = 5) -> MarketSnapshot | None:
        try:
            if self.polygon_key:
                return self._polygon(symbol, lookback)
            if self._yf:
                return self._yfinance(symbol, lookback)
        except Exception as exc:  # noqa: BLE001 - source must never break the pipeline
            log.warning("market snapshot failed for %s: %s", symbol, exc)
        return None

    # --- Polygon -----------------------------------------------------------
    def _polygon(self, symbol: str, lookback: int) -> MarketSnapshot | None:
        base = "https://api.polygon.io"
        agg = requests.get(
            f"{base}/v2/aggs/ticker/{symbol}/range/1/day/2000-01-01/2100-01-01",
            params={"adjusted": "true", "sort": "desc", "limit": 60, "apiKey": self.polygon_key},
            timeout=15,
        )
        agg.raise_for_status()
        bars = list(reversed(agg.json().get("results", [])))
        if len(bars) < lookback + 2:
            return None
        closes = [b["c"] for b in bars]
        vols = [b["v"] for b in bars]
        price = closes[-1]
        prior_move = (closes[-1] / closes[-1 - lookback] - 1.0) * 100.0
        avg_vol = sum(vols[-21:-1]) / max(len(vols[-21:-1]), 1)
        rel_vol = vols[-1] / avg_vol if avg_vol else 1.0
        cap = self._polygon_cap(symbol, base)
        return MarketSnapshot(
            symbol=symbol,
            price=price,
            prior_move_pct=prior_move,
            rel_volume=rel_vol,
            rsi14=_rsi(closes),
            avg_dollar_volume=avg_vol * price,
            market_cap=cap,
        )

    def _polygon_cap(self, symbol: str, base: str) -> float | None:
        try:
            r = requests.get(
                f"{base}/v3/reference/tickers/{symbol}",
                params={"apiKey": self.polygon_key},
                timeout=10,
            )
            r.raise_for_status()
            return r.json().get("results", {}).get("market_cap")
        except Exception:  # noqa: BLE001
            return None

    # --- yfinance fallback -------------------------------------------------
    def _yfinance(self, symbol: str, lookback: int) -> MarketSnapshot | None:
        tkr = self._yf.Ticker(symbol)
        hist = tkr.history(period="3mo")
        if hist is None or len(hist) < lookback + 2:
            return None
        closes = hist["Close"].tolist()
        vols = hist["Volume"].tolist()
        price = closes[-1]
        prior_move = (closes[-1] / closes[-1 - lookback] - 1.0) * 100.0
        avg_vol = sum(vols[-21:-1]) / max(len(vols[-21:-1]), 1)
        rel_vol = vols[-1] / avg_vol if avg_vol else 1.0
        cap = tkr.fast_info.get("market_cap") if hasattr(tkr, "fast_info") else None
        return MarketSnapshot(
            symbol=symbol,
            price=price,
            prior_move_pct=prior_move,
            rel_volume=rel_vol,
            rsi14=_rsi(closes),
            avg_dollar_volume=avg_vol * price,
            market_cap=cap,
        )
