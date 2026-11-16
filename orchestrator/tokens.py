"""Sum measured token usage across the pipeline.

Each block is copied from an agent report's usage field, or from the
orchestrator's own model response. A missing field is 0. This module does
not estimate tokens from text length.
"""

from __future__ import annotations

AGENTS = ("forensics", "archaeologist", "runbook", "orchestrator")


def account(forensics: dict, archaeology: dict, runbook: dict, orchestrator: dict) -> dict:
    """Return per-agent usage plus a total. `orchestrator` is a usage pair."""
    tokens = {
        "forensics": usage_of(forensics),
        "archaeologist": usage_of(archaeology),
        "runbook": usage_of(runbook),
        "orchestrator": pair(orchestrator),
    }
    return retotal(tokens)


def usage_of(report: dict) -> dict:
    if not isinstance(report, dict):
        return {"input": 0, "output": 0}
    return pair(report.get("tokens"))


def pair(tokens) -> dict:
    if not isinstance(tokens, dict):
        return {"input": 0, "output": 0}
    return {"input": _count(tokens.get("input")), "output": _count(tokens.get("output"))}


def retotal(tokens: dict) -> dict:
    total_in = 0
    total_out = 0
    for name in AGENTS:
        block = pair(tokens.get(name))
        tokens[name] = block
        total_in += block["input"]
        total_out += block["output"]
    tokens["total"] = {"input": total_in, "output": total_out}
    return tokens


def _count(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value
