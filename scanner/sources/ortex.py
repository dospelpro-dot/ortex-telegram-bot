"""ORTEX adapter: short-interest / borrow / options signals — the fuel that
makes retail attention reflexive (short covering amplifies the up-move).

The exact ORTEX endpoint paths vary by plan; they are read from config so
you can point them at your entitlement without editing code. Missing key or
any error -> None, and squeeze-fuel simply contributes nothing to the score.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import requests

import config

log = logging.getLogger("scanner.ortex")


@dataclass
class OrtexSnapshot:
    symbol: str
    short_interest_pct_float: float | None   # SI as % of free float (fuel)
    cost_to_borrow: float | None             # CTB %, rising = tightening
    ctb_change_pct: float | None             # CTB delta vs prior (tightening speed)
    utilization: float | None                # % of lendable on loan
    days_to_cover: float | None              # short covering pressure
    call_put_ratio: float | None             # options positioning (gamma fuel)


class Ortex:
    def __init__(self) -> None:
        self.key = config.ORTEX_API_KEY
        self.base = (config.ORTEX_BASE_URL or "").rstrip("/")

    @property
    def active(self) -> bool:
        return bool(self.key and self.base)

    def _get(self, path: str) -> dict | None:
        url = f"{self.base}{path}"
        try:
            r = requests.get(
                url,
                headers={"Ortex-Api-Key": self.key, "Accept": "application/json"},
                timeout=15,
            )
            r.raise_for_status()
            return r.json()
        except Exception as exc:  # noqa: BLE001
            log.debug("ortex GET %s failed: %s", path, exc)
            return None

    def snapshot(self, symbol: str) -> OrtexSnapshot | None:
        if not self.active:
            return None
        # Endpoint templates are configurable; default to ORTEX's documented
        # short-interest and CTB shapes. Adjust ORTEX_BASE_URL / paths per plan.
        si = self._get(f"/api/v1/stock/us/{symbol}/short_interest") or {}
        ctb = self._get(f"/api/v1/stock/us/{symbol}/ctb/new") or {}
        opts = self._get(f"/api/v1/stock/us/{symbol}/options/summary") or {}

        if not (si or ctb or opts):
            return None

        return OrtexSnapshot(
            symbol=symbol,
            short_interest_pct_float=_num(si, "shortInterestPcFreeFloat", "siPcFreeFloat"),
            cost_to_borrow=_num(ctb, "costToBorrow", "ctb", "value"),
            ctb_change_pct=_num(ctb, "change", "ctbChange"),
            utilization=_num(si, "utilization"),
            days_to_cover=_num(si, "daysToCover", "dtc"),
            call_put_ratio=_num(opts, "callPutRatio", "cpr"),
        )


def _num(d: dict, *keys: str) -> float | None:
    """Pull the first present numeric value across candidate key spellings.
    Tolerates {'rows':[{...}]} and {'data':{...}} envelope shapes."""
    if isinstance(d.get("rows"), list) and d["rows"]:
        d = {**d, **d["rows"][0]}
    if isinstance(d.get("data"), dict):
        d = {**d, **d["data"]}
    for k in keys:
        v = d.get(k)
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            try:
                return float(v.replace("%", "").replace(",", ""))
            except ValueError:
                continue
    return None
