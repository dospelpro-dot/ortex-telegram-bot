"""Append-only JSONL store for logged picks.

One JSON object per pick per scan. Kept human-readable and git-ignored
(it's your trading log, not source). No DB dependency on purpose.
"""
from __future__ import annotations

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PICKS_FILE = DATA_DIR / "picks.jsonl"


def _ensure() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    PICKS_FILE.touch(exist_ok=True)


def append(record: dict) -> None:
    _ensure()
    with PICKS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_all() -> list[dict]:
    if not PICKS_FILE.exists():
        return []
    out = []
    for line in PICKS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def rewrite(records: list[dict]) -> None:
    """Overwrite the whole file (used after evaluation fills in outcomes)."""
    _ensure()
    tmp = PICKS_FILE.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(PICKS_FILE)
