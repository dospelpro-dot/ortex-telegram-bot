"""Orchestration: universe -> signals -> filter -> score -> top-N names.

This is the single entry point the bot and CLI both call: `run_scan()`.
It is source-tolerant — any dead provider just lowers that sub-score.
"""
from __future__ import annotations

import logging

import config
from scanner.scoring import Candidate, passes_filters, score_candidate
from scanner.sources.market import MarketData
from scanner.sources.ortex import Ortex
from scanner.sources.social import Social
from scanner.universe import build_universe

log = logging.getLogger("scanner.pipeline")


def run_scan(universe_limit: int = 40, log_picks: bool = False) -> list[Candidate]:
    market, ortex, social = MarketData(), Ortex(), Social()
    universe = build_universe(limit=universe_limit)

    scored: list[Candidate] = []
    for sym in universe:
        m = market.snapshot(sym)
        if m is None:
            log.debug("skip %s: no market data", sym)
            continue
        o = ortex.snapshot(sym)
        ok, why = passes_filters(m, o)
        if not ok:
            log.debug("filter %s: %s", sym, why)
            continue
        s = social.snapshot(sym)
        scored.append(score_candidate(sym, m, o, s))

    scored.sort(key=lambda c: c.score, reverse=True)
    top = scored[: config.MISSION.n_names]
    log.info("scan complete: %d scored, top %d selected", len(scored), len(top))
    if log_picks and top:
        # Import lazily so the scanner has no hard dependency on the backtester.
        from backtest.logger import log_picks as _log
        _log(top)
    return top


def format_report(top: list[Candidate]) -> str:
    """Telegram-ready (HTML) report of the top names."""
    mis = config.MISSION
    if not top:
        return (
            "🔍 <b>Скан завершён</b> — ни одного имени не прошло фильтры.\n"
            "Рынок тихий или источники данных недоступны. Проверь ключи в .env."
        )
    lines = [
        f"🎯 <b>Рефлексивные петли внимания</b> — топ-{len(top)}",
        f"<i>Цель: +{mis.target_move_pct:.0f}% за {mis.horizon_days_min}–{mis.horizon_days_max} дня, "
        f"приоритет social velocity</i>",
        "",
    ]
    for i, c in enumerate(top, 1):
        px = f"${c.market.price:.2f}" if c.market else "?"
        flag = ("  " + " ".join(c.flags)) if c.flags else ""
        lines.append(f"<b>{i}. ${c.symbol}</b>  {px}  ·  score <b>{c.score:.2f}</b>{flag}")
        lines.append(
            f"   social {c.sub['social']:.2f} · spark {c.sub['spark']:.2f} · "
            f"squeeze {c.sub['squeeze']:.2f} · early {c.sub['early']:.2f} · "
            f"retail {c.sub['retail']:.2f}"
        )
        for r in c.reasons:
            lines.append(f"   • {r}")
        lines.append("")
    lines.append(
        "⚠️ <i>Не инвестсовет. Сигнал носит вероятностный характер; "
        "короткий горизонт = высокий риск. Управляй позицией и стопами сам.</i>"
    )
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    import re

    parser = argparse.ArgumentParser(description="Reflexive-attention equity scan")
    parser.add_argument("--log", action="store_true", help="log top picks for backtesting")
    parser.add_argument("--limit", type=int, default=40, help="universe size to scan")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    inactive = config.missing_keys()
    if inactive:
        log.warning("Inactive integrations:\n  - %s", "\n  - ".join(inactive))
    report = format_report(run_scan(universe_limit=args.limit, log_picks=args.log))
    print(re.sub(r"<[^>]+>", "", report))  # strip HTML for terminal readability
