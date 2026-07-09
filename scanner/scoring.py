"""Scoring — turn raw signals into a ranked reflexive-loop conviction score.

Design intent (matches CLAUDE.md):
  * SOCIAL VELOCITY dominates — we are hunting acceleration, not popularity.
  * SQUEEZE FUEL (ORTEX) amplifies: short covering makes attention reflexive.
  * EARLY STAGE gates for timing — we want it BEFORE momentum quants, so a
    name that already exploded scores LOW even if it's loud.
  * RETAIL-OWNED gates for the "before ETF flows" edge — small, un-indexed,
    low-institutional names have room before the mechanical bid arrives.

Every sub-score is squashed to [0, 1]; the composite is a weighted sum.
Hard filters run first and can reject a name outright.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import config
from scanner.sources.market import MarketSnapshot
from scanner.sources.ortex import OrtexSnapshot
from scanner.sources.social import SocialSnapshot


def _sat(x: float, k: float) -> float:
    """Saturating map [0, inf) -> [0, 1); k is the half-saturation point."""
    if x <= 0:
        return 0.0
    return x / (x + k)


def _bell(x: float, center: float, width: float) -> float:
    """Reward proximity to a sweet spot (used for 'early but igniting')."""
    return math.exp(-((x - center) ** 2) / (2 * width ** 2))


@dataclass
class Candidate:
    symbol: str
    score: float
    sub: dict = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    market: MarketSnapshot | None = None
    ortex: OrtexSnapshot | None = None
    social: SocialSnapshot | None = None


def passes_filters(m: MarketSnapshot, o: OrtexSnapshot | None) -> tuple[bool, str]:
    f = config.FILTERS
    if not (f.min_price <= m.price <= f.max_price):
        return False, f"price {m.price:.2f} outside [{f.min_price}, {f.max_price}]"
    if m.avg_dollar_volume < f.min_avg_dollar_vol:
        return False, f"illiquid (${m.avg_dollar_volume:,.0f}/day)"
    if m.market_cap and m.market_cap > f.max_market_cap:
        return False, f"cap ${m.market_cap/1e9:.1f}B > max (too institutional)"
    if m.prior_move_pct > f.max_prior_move_pct:
        return False, f"already ran +{m.prior_move_pct:.0f}% (past the early edge)"
    return True, "ok"


def _social_score(s: SocialSnapshot | None) -> tuple[float, str]:
    if not s or s.sources_live == 0:
        return 0.0, "no social data"
    # Bullish acceleration from a low base is the fingerprint. Volume counts
    # only BULLISH mentions; a sentiment tilt term rewards net-bullish attention
    # and pulls down names where the chatter is dominated by bears/puts/rug.
    accel = _sat(max(s.acceleration, 0.0), k=1.5)
    bull_vol = _sat(s.bull_recent, k=25)
    breadth = _sat(s.unique_authors_recent, k=15)
    tilt = s.bull_ratio  # 0..1
    score = 0.45 * accel + 0.20 * bull_vol + 0.15 * breadth + 0.20 * tilt
    reason = (
        f"social: {s.bull_ratio:.0%} bull ({s.bull_recent}▲/{s.bear_recent}▼), "
        f"bull-vel {s.bull_velocity:+.0%}, {s.unique_authors_recent} authors ({config_recent()}h)"
    )
    return score, reason


def config_recent() -> int:
    from scanner.sources.social import RECENT_HOURS
    return RECENT_HOURS


def _squeeze_score(o: OrtexSnapshot | None) -> tuple[float, str]:
    if not o:
        return 0.0, "no ORTEX data"
    si = _sat((o.short_interest_pct_float or 0.0), k=15)         # SI% of float
    ctb = _sat((o.cost_to_borrow or 0.0), k=30)                  # borrow cost
    tightening = _sat(max(o.ctb_change_pct or 0.0, 0.0), k=10)   # rising CTB
    util = _sat((o.utilization or 0.0), k=60)                    # utilization
    dtc = _sat((o.days_to_cover or 0.0), k=3)                    # days to cover
    score = 0.30 * si + 0.20 * ctb + 0.20 * tightening + 0.15 * util + 0.15 * dtc
    bits = []
    if o.short_interest_pct_float:
        bits.append(f"SI {o.short_interest_pct_float:.0f}% float")
    if o.cost_to_borrow:
        bits.append(f"CTB {o.cost_to_borrow:.0f}%")
    if o.days_to_cover:
        bits.append(f"DTC {o.days_to_cover:.1f}")
    return score, "squeeze fuel: " + (", ".join(bits) if bits else "thin")


def _early_stage_score(m: MarketSnapshot) -> tuple[float, str]:
    # Relative volume sweet spot: igniting (2-4x) beats climax (>10x) or dead (<1x).
    rvol = _bell(m.rel_volume, center=3.0, width=2.2)
    # RSI sweet spot: waking up (55-68), penalise overbought (>75) and dead (<45).
    rsi = _bell(m.rsi14, center=62.0, width=12.0)
    # Prior move: reward modest early move, penalise big prior run-up.
    move = _bell(m.prior_move_pct, center=6.0, width=10.0)
    score = 0.40 * rvol + 0.30 * rsi + 0.30 * move
    return score, f"early: rVol {m.rel_volume:.1f}x, RSI {m.rsi14:.0f}, prior {m.prior_move_pct:+.0f}%"


def _spark_score(m: MarketSnapshot, s: SocialSnapshot | None) -> tuple[float, str]:
    """FIRST SPARK — the earliest edge of the reflexive loop.

    Detects a DIVERGENCE: bullish attention already accelerating while the tape
    is still asleep (price barely moved, volume not yet elevated). This is the
    point *before* momentum quants — they trade realised price/volume, which
    hasn't printed yet. Once the tape confirms, the spark has already caught.

        spark = social_heat × price_quiet × volume_quiet   (each in [0, 1])
    """
    if not s or s.sources_live == 0:
        return 0.0, "spark: no social data"
    # Heat: bullish acceleration from a low base, but require a real handful of
    # bullish posts so 1->2 mentions doesn't read as a spark.
    heat = _sat(max(s.bull_velocity, 0.0), k=1.0) * _sat(s.bull_recent, k=6) * s.bull_ratio
    # Quiet tape: reward price that hasn't run UP yet (down/flat is fine).
    price_quiet = math.exp(-((max(m.prior_move_pct, 0.0) / 6.0) ** 2))
    # Quiet volume: reward relative volume still near baseline (~1x).
    volume_quiet = math.exp(-((max(m.rel_volume - 1.0, 0.0) / 1.5) ** 2))
    score = heat * price_quiet * volume_quiet
    reason = (
        f"spark: attention {s.bull_velocity:+.0%} vs price {m.prior_move_pct:+.0f}% / "
        f"rVol {m.rel_volume:.1f}x (divergence {score:.2f})"
    )
    return score, reason


def _retail_score(m: MarketSnapshot) -> tuple[float, str]:
    if not m.market_cap:
        return 0.5, "cap unknown"
    # Smaller cap => more room before ETF/index mechanics engage. Peak ~ $500M.
    b = math.log10(max(m.market_cap, 1e6))
    score = _bell(b, center=8.7, width=1.1)  # 10^8.7 ≈ $500M
    return score, f"size ${m.market_cap/1e9:.2f}B"


def score_candidate(
    symbol: str,
    m: MarketSnapshot,
    o: OrtexSnapshot | None,
    s: SocialSnapshot | None,
) -> Candidate:
    w = config.WEIGHTS
    social, r_social = _social_score(s)
    spark, r_spark = _spark_score(m, s)
    squeeze, r_squeeze = _squeeze_score(o)
    early, r_early = _early_stage_score(m)
    retail, r_retail = _retail_score(m)

    composite = (
        w.social_velocity * social
        + w.first_spark * spark
        + w.squeeze_fuel * squeeze
        + w.early_stage * early
        + w.retail_owned * retail
    )
    flags = ["🔥 FIRST SPARK"] if spark >= config.SPARK_FLAG_THRESHOLD else []
    return Candidate(
        symbol=symbol,
        score=round(composite, 4),
        sub={"social": round(social, 3), "spark": round(spark, 3),
             "squeeze": round(squeeze, 3), "early": round(early, 3),
             "retail": round(retail, 3)},
        reasons=[r_social, r_spark, r_squeeze, r_early, r_retail],
        flags=flags,
        market=m,
        ortex=o,
        social=s,
    )
