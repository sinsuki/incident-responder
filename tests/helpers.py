"""Shared readers for scenario output."""

from __future__ import annotations

import json
from pathlib import Path


def load_jsonl(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    if not text:
        return []
    return [json.loads(line) for line in text.splitlines()]


def load_run(out: Path) -> dict:
    return {
        "traces": load_jsonl(out / "traces.jsonl"),
        "logs": load_jsonl(out / "logs.jsonl"),
        "metrics": load_jsonl(out / "metrics.jsonl"),
        "ground_truth": json.loads((out / "ground_truth.json").read_text(encoding="utf-8")),
    }
