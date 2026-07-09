"""Candidate universe — where we look for reflexive loops.

Scanning every US ticker is wasteful; retail attention concentrates. We seed
the universe from live retail-attention surfaces (StockTwits trending) plus an
optional manual watchlist (WATCHLIST env, comma-separated, or watchlist.txt).
This keeps the scan pointed exactly where reflexive loops actually ignite.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import requests

import config

log = logging.getLogger("scanner.universe")

_WATCHLIST_FILE = Path(__file__).resolve().parent.parent / "watchlist.txt"


def _stocktwits_trending() -> list[str]:
    try:
        r = requests.get(
            "https://api.stocktwits.com/api/2/trending/symbols.json",
            timeout=15,
            headers={"User-Agent": config.REDDIT_USER_AGENT},
        )
        if r.status_code != 200:
            return []
        return [s["symbol"] for s in r.json().get("symbols", []) if _looks_us_equity(s)]
    except Exception as exc:  # noqa: BLE001
        log.warning("stocktwits trending failed: %s", exc)
        return []


def _looks_us_equity(entry: dict) -> bool:
    sym = entry.get("symbol", "")
    # Skip crypto/forex/indices (StockTwits marks these), keep plain tickers.
    if entry.get("instrument_class") in {"Cryptocurrency", "Forex"}:
        return False
    return sym.isalpha() and 1 <= len(sym) <= 5


def _manual_watchlist() -> list[str]:
    syms: list[str] = []
    env = os.getenv("WATCHLIST", "")
    if env:
        syms += [s.strip().upper() for s in env.split(",") if s.strip()]
    if _WATCHLIST_FILE.exists():
        for line in _WATCHLIST_FILE.read_text().splitlines():
            line = line.split("#", 1)[0].strip().upper()
            if line:
                syms.append(line)
    return syms


def build_universe(limit: int = 40) -> list[str]:
    """Deduplicated candidate tickers, manual watchlist first (priority)."""
    seen: dict[str, None] = {}
    for sym in _manual_watchlist() + _stocktwits_trending():
        seen.setdefault(sym.upper(), None)
    universe = list(seen.keys())[:limit]
    log.info("universe: %d candidates", len(universe))
    return universe
