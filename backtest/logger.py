"""Record the top-N picks at scan time — the raw material for calibration.

We snapshot the entry price and every sub-score so that, once the horizon
elapses, we can correlate what we *predicted* with what actually moved.
"""
from __future__ import annotations

import datetime as dt
import logging
import uuid

import config
from backtest import store
from scanner.scoring import Candidate

log = logging.getLogger("backtest.logger")


def log_picks(top: list[Candidate], scan_id: str | None = None) -> str:
    """Append each pick as a pending record. Returns the scan_id."""
    scan_id = scan_id or dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    for rank, c in enumerate(top, 1):
        if not c.market:
            continue
        store.append({
            "pick_id": uuid.uuid4().hex[:12],
            "scan_id": scan_id,
            "logged_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "symbol": c.symbol,
            "rank": rank,
            "entry_price": round(c.market.price, 4),
            "score": c.score,
            "sub": c.sub,
            "target_move_pct": config.MISSION.target_move_pct,
            "horizon_max": config.MISSION.horizon_days_max,
            "evaluated": False,
            "outcome": None,
        })
    log.info("logged %d picks (scan_id=%s)", len(top), scan_id)
    return scan_id
