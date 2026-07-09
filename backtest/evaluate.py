"""Measure realised return for matured picks.

For each pending pick whose horizon has elapsed, fetch the daily bars AFTER
entry and compute:
  * max_ret     — best intraday high vs entry over the 1..horizon window
  * final_ret   — close return at the end of the window
  * hit          — did max_ret reach the +target%?
  * days_to_hit  — first session that touched the target (None if never)

Run:  python -m backtest.evaluate
"""
from __future__ import annotations

import datetime as dt
import logging

from backtest import store
from scanner.sources.market import MarketData

log = logging.getLogger("backtest.evaluate")

# Wait this many calendar days past the horizon before evaluating, so the
# trading sessions have actually printed (covers weekends/holidays).
MATURITY_BUFFER_DAYS = 2


def _mature(rec: dict, now: dt.datetime) -> bool:
    logged = dt.datetime.fromisoformat(rec["logged_at"])
    horizon = int(rec.get("horizon_max", 3))
    return now >= logged + dt.timedelta(days=horizon + MATURITY_BUFFER_DAYS)


def _evaluate_one(rec: dict, market: MarketData) -> dict | None:
    entry = rec["entry_price"]
    if not entry:
        return None
    logged = dt.datetime.fromisoformat(rec["logged_at"])
    entry_date = logged.date()
    horizon = int(rec.get("horizon_max", 3))
    target = float(rec.get("target_move_pct", 15.0))

    bars = market.daily_bars(
        rec["symbol"], entry_date, entry_date + dt.timedelta(days=horizon + 6)
    )
    future = [b for b in bars if b["date"] > entry_date.isoformat()][:horizon]
    if not future:
        return None  # data not available yet; leave pending

    max_ret = max((b["high"] / entry - 1.0) * 100.0 for b in future)
    final_ret = (future[-1]["close"] / entry - 1.0) * 100.0
    days_to_hit = None
    for i, b in enumerate(future, 1):
        if (b["high"] / entry - 1.0) * 100.0 >= target:
            days_to_hit = i
            break

    return {
        "evaluated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "sessions_used": len(future),
        "max_ret": round(max_ret, 2),
        "final_ret": round(final_ret, 2),
        "hit": days_to_hit is not None,
        "days_to_hit": days_to_hit,
    }


def evaluate_pending() -> tuple[int, int]:
    """Fill outcomes for matured picks. Returns (evaluated, still_pending)."""
    records = store.load_all()
    if not records:
        log.info("no picks logged yet")
        return 0, 0
    market = MarketData()
    now = dt.datetime.now(dt.timezone.utc)
    evaluated, pending = 0, 0
    for rec in records:
        if rec.get("evaluated"):
            continue
        if not _mature(rec, now):
            pending += 1
            continue
        outcome = _evaluate_one(rec, market)
        if outcome is None:
            pending += 1
            continue
        rec["evaluated"] = True
        rec["outcome"] = outcome
        evaluated += 1
        log.info("%s: max %+.1f%% final %+.1f%% hit=%s",
                 rec["symbol"], outcome["max_ret"], outcome["final_ret"], outcome["hit"])
    if evaluated:
        store.rewrite(records)
    return evaluated, pending


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    done, left = evaluate_pending()
    print(f"Evaluated {done} pick(s); {left} still pending (waiting for horizon).")
