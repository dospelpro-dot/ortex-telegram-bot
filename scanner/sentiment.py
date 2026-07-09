"""Lightweight finance-social sentiment classifier.

Purpose: separate the *bullish* reflexive loop ("squeeze", "🚀", "loading calls")
from bearish attention ("puts", "rug", "shorting this"). Raw mention volume
treats both the same; the up-loop we hunt is driven by bullish acceleration.

No ML dependency: a curated cashtag-culture lexicon + emoji + a short negation
window ("not going up" -> bearish). StockTwits' own Bullish/Bearish tag is used
first when present (see social.py); this is the fallback for untagged text.

classify(text) -> +1 bullish | -1 bearish | 0 neutral/unknown
"""
from __future__ import annotations

import re

BULL = {
    "moon", "mooning", "squeeze", "squeezing", "calls", "call", "buy", "buying",
    "long", "longs", "bull", "bullish", "breakout", "breaking", "ripping", "rip",
    "rocket", "rockets", "tendies", "yolo", "undervalued", "pump", "pumping",
    "run", "running", "runner", "green", "up", "higher", "gap", "gapping",
    "load", "loading", "accumulate", "hold", "holding", "hodl", "diamond",
    "explode", "exploding", "parabolic", "float", "gamma", "fomo", "send", "sending",
}
BEAR = {
    "puts", "put", "short", "shorts", "shorting", "sell", "selling", "sold",
    "dump", "dumping", "crash", "crashing", "bear", "bearish", "bagholder",
    "bagholders", "scam", "dead", "overvalued", "drop", "dropping", "tank",
    "tanking", "rug", "rugged", "rugpull", "fraud", "dilution", "diluting",
    "down", "lower", "red", "falling", "fall", "collapse", "avoid", "trap",
    "worthless", "bankrupt", "bankruptcy", "offering", "halt", "halted",
}
BULL_EMOJI = ["🚀", "🌙", "💎", "🙌", "📈", "🐂", "🔥", "🤑", "💰"]
BEAR_EMOJI = ["📉", "🐻", "💩", "⚰️", "🩸", "🧸"]
NEGATORS = {"not", "no", "never", "dont", "isnt", "aint", "cant", "without", "wont"}

_TOKEN = re.compile(r"[a-z']+")


def classify(text: str | None) -> int:
    if not text:
        return 0
    low = text.lower()

    score = 0
    for e in BULL_EMOJI:
        score += low.count(e)
    for e in BEAR_EMOJI:
        score -= low.count(e)

    toks = _TOKEN.findall(low)
    for i, w in enumerate(toks):
        val = 1 if w in BULL else (-1 if w in BEAR else 0)
        if val and any(toks[j].strip("'") in NEGATORS for j in range(max(0, i - 3), i)):
            val = -val  # "not going up" -> flip
        score += val

    if score > 0:
        return 1
    if score < 0:
        return -1
    return 0
