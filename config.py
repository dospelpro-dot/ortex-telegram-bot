"""Central configuration for the reflexive-attention equity scanner.

All secrets come from environment variables (see .env.example). Nothing
sensitive is hard-coded. Weights and thresholds live here so the mission
can be tuned without touching the pipeline logic.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _env(name: str, default: str | None = None) -> str | None:
    val = os.getenv(name, default)
    return val.strip() if isinstance(val, str) else val


def _envf(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _envi(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


# --- Credentials -----------------------------------------------------------
TELEGRAM_BOT_TOKEN = _env("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = _env("TELEGRAM_CHAT_ID")  # optional: where to push alerts

ORTEX_API_KEY = _env("ORTEX_API_KEY")
ORTEX_BASE_URL = _env("ORTEX_BASE_URL", "https://api.ortex.com")

POLYGON_API_KEY = _env("POLYGON_API_KEY")  # market data (optional; yfinance fallback)

X_BEARER_TOKEN = _env("X_BEARER_TOKEN")  # X / Twitter API v2
REDDIT_CLIENT_ID = _env("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = _env("REDDIT_CLIENT_SECRET")
REDDIT_USER_AGENT = _env("REDDIT_USER_AGENT", "ortex-attention-scanner/0.1")
# StockTwits public endpoints need no key (rate-limited).


@dataclass(frozen=True)
class Mission:
    """The scanner's north star — mirrors CLAUDE.md.

    Find early reflexive loops of retail attention in US equities BEFORE
    momentum quants and ETF flows arrive. Deliver a small number of names
    with an asymmetric short-horizon move, prioritising social velocity.
    """

    n_names: int = _envi("MISSION_N_NAMES", 3)
    target_move_pct: float = _envf("MISSION_TARGET_MOVE_PCT", 15.0)
    horizon_days_min: int = _envi("MISSION_HORIZON_MIN", 1)
    horizon_days_max: int = _envi("MISSION_HORIZON_MAX", 3)


@dataclass(frozen=True)
class Weights:
    """Composite score weights. Social velocity dominates by design.

    The thesis: retail attention is reflexive (mentions -> buyers -> price
    -> more mentions). We want the ACCELERATION phase, before realised
    momentum draws quants and before index/AUM mechanics draw ETF flows.
    """

    social_velocity: float = _envf("W_SOCIAL", 0.40)
    squeeze_fuel: float = _envf("W_SQUEEZE", 0.30)
    early_stage: float = _envf("W_EARLY", 0.20)
    retail_owned: float = _envf("W_RETAIL", 0.10)

    def normalised(self) -> "Weights":
        total = self.social_velocity + self.squeeze_fuel + self.early_stage + self.retail_owned
        if total <= 0:
            return Weights()
        return Weights(
            social_velocity=self.social_velocity / total,
            squeeze_fuel=self.squeeze_fuel / total,
            early_stage=self.early_stage / total,
            retail_owned=self.retail_owned / total,
        )


@dataclass(frozen=True)
class Filters:
    """Hard gates. A name failing any of these is dropped before scoring."""

    min_price: float = _envf("FILTER_MIN_PRICE", 1.0)
    max_price: float = _envf("FILTER_MAX_PRICE", 500.0)
    # Tradeable but still retail-driven — avoid mega-cap and illiquid microcaps.
    min_avg_dollar_vol: float = _envf("FILTER_MIN_DOLLAR_VOL", 3_000_000.0)
    max_market_cap: float = _envf("FILTER_MAX_MARKET_CAP", 20_000_000_000.0)
    # "Before momentum": reject names that already ran too far.
    max_prior_move_pct: float = _envf("FILTER_MAX_PRIOR_MOVE", 30.0)
    # "Before ETF flows": reject names already dominated by institutions.
    max_institutional_pct: float = _envf("FILTER_MAX_INST_PCT", 70.0)


MISSION = Mission()
WEIGHTS = Weights().normalised()
FILTERS = Filters()


def missing_keys() -> list[str]:
    """Report which optional integrations are inactive (for diagnostics)."""
    inactive = []
    if not ORTEX_API_KEY:
        inactive.append("ORTEX_API_KEY (squeeze-fuel signal disabled)")
    if not (X_BEARER_TOKEN or REDDIT_CLIENT_ID):
        inactive.append("X/Reddit keys (social breadth reduced; StockTwits still active)")
    if not POLYGON_API_KEY:
        inactive.append("POLYGON_API_KEY (using yfinance fallback for market data)")
    if not TELEGRAM_BOT_TOKEN:
        inactive.append("TELEGRAM_BOT_TOKEN (bot cannot start)")
    return inactive
