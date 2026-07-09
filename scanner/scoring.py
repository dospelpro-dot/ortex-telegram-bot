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
    # Acceleration from a low base is the fingerprint; scale by absolute recent.
    accel = _sat(max(s.acceleration, 0.0), k=1.5)
    volume = _sat(s.mentions_recent, k=25)
    breadth = _sat(s.unique_authors_recent, k=15)
    score = 0.55 * accel + 0.25 * volume + 0.20 * breadth
    reason = (
        f"social vel {s.velocity:+.0%}, {s.mentions_recent} mentions/{s.unique_authors_recent} "
        f"authors (recent {config_recent()}h)"
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
    squeeze, r_squeeze = _squeeze_score(o)
    early, r_early = _early_stage_score(m)
    retail, r_retail = _retail_score(m)

    composite = (
        w.social_velocity * social
        + w.squeeze_fuel * squeeze
        + w.early_stage * early
        + w.retail_owned * retail
    )
    return Candidate(
        symbol=symbol,
        score=round(composite, 4),
        sub={"social": round(social, 3), "squeeze": round(squeeze, 3),
             "early": round(early, 3), "retail": round(retail, 3)},
        reasons=[r_social, r_squeeze, r_early, r_retail],
        market=m,
        ortex=o,
        social=s,
    )
