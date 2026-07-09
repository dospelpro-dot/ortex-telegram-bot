"""Calibration: what actually predicted the move?

Aggregates evaluated picks into performance stats, then correlates each
sub-score (social / squeeze / early / retail) with the realised best-case
return. Signals that correlate more with real moves get more weight.

The suggested weights are a heuristic starting point — treat them as a
data-informed nudge, not gospel, especially below ~30 samples.

Run:  python -m backtest.analyze
"""
from __future__ import annotations

import logging
import math
from statistics import mean, median

import config
from backtest import store

log = logging.getLogger("backtest.analyze")

SUB_KEYS = ["social", "squeeze", "early", "retail"]
WEIGHT_ENV = {"social": "W_SOCIAL", "squeeze": "W_SQUEEZE",
              "early": "W_EARLY", "retail": "W_RETAIL"}
MIN_SAMPLES = 30


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 3:
        return 0.0
    mx, my = mean(xs), mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return 0.0
    return num / (dx * dy)


def analyze() -> dict:
    records = [r for r in store.load_all() if r.get("evaluated") and r.get("outcome")]
    n = len(records)
    result: dict = {"n": n}
    if n == 0:
        return result

    max_rets = [r["outcome"]["max_ret"] for r in records]
    final_rets = [r["outcome"]["final_ret"] for r in records]
    hits = [1 for r in records if r["outcome"]["hit"]]

    result.update({
        "hit_rate": len(hits) / n,
        "avg_max_ret": mean(max_rets),
        "median_max_ret": median(max_rets),
        "avg_final_ret": mean(final_rets),
        "correlations": {},
        "suggested_weights": {},
    })

    # Correlate each sub-score with best-case return.
    corrs = {}
    for key in SUB_KEYS:
        xs = [r["sub"].get(key, 0.0) for r in records]
        corrs[key] = round(_pearson(xs, max_rets), 3)
    result["correlations"] = corrs

    # Suggested weights ∝ positive correlation. If nothing is positive, keep current.
    positive = {k: max(v, 0.0) for k, v in corrs.items()}
    total = sum(positive.values())
    if total > 0:
        result["suggested_weights"] = {k: round(v / total, 3) for k, v in positive.items()}
    return result


def format_report(a: dict) -> str:
    n = a.get("n", 0)
    if n == 0:
        return ("Пока нет оценённых пиков. Запусти сканы (пики логируются), подожди "
                "горизонт и выполни `python -m backtest.evaluate`, затем повтори анализ.")
    lines = [
        f"КАЛИБРОВКА — {n} оценённых пиков",
        f"  hit-rate (достигли +{config.MISSION.target_move_pct:.0f}%): {a['hit_rate']:.0%}",
        f"  средний max +%:   {a['avg_max_ret']:+.1f}%   (медиана {a['median_max_ret']:+.1f}%)",
        f"  средний close +%: {a['avg_final_ret']:+.1f}%",
        "",
        "  Корреляция суб-скора с реальным max +% (выше = сигнал лучше предсказывает):",
    ]
    cur = config.WEIGHTS
    cur_map = {"social": cur.social_velocity, "squeeze": cur.squeeze_fuel,
               "early": cur.early_stage, "retail": cur.retail_owned}
    for k in SUB_KEYS:
        lines.append(f"    {k:<8} corr {a['correlations'][k]:+.2f}   вес сейчас {cur_map[k]:.2f}")

    if a.get("suggested_weights"):
        lines += ["", "  Предлагаемые веса (∝ положительной корреляции):"]
        for k in SUB_KEYS:
            sw = a["suggested_weights"].get(k, 0.0)
            lines.append(f"    {WEIGHT_ENV[k]}={sw:.2f}")
        if n < MIN_SAMPLES:
            lines += ["", f"  ⚠️ Выборка мала (<{MIN_SAMPLES}). Копи данные перед сменой весов."]
        else:
            lines += ["", "  Вставь строки выше в .env, чтобы применить калибровку."]
    else:
        lines += ["", "  Ни один сигнал пока не коррелирует положительно — веса не трогаем."]
    return "\n".join(lines)


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    print(format_report(analyze()))
