"""Render the root-cause report as Markdown.

The sentences are the claim texts. Citation anchors are already in those
sentences, so this module does not add a second copy of the ids.
"""

from __future__ import annotations

_TITLES = (
    ("summary", "Summary"),
    ("impact", "Impact"),
    ("timeline", "Timeline"),
    ("root_cause", "Root cause"),
    ("evidence", "Evidence"),
    ("mitigation", "Mitigation"),
)
_AGENTS = ("forensics", "archaeologist", "runbook", "orchestrator", "total")


def render(report: dict) -> str:
    lines = ["# Root cause analysis", ""]
    sections = report.get("sections") if isinstance(report.get("sections"), dict) else {}
    for key, title in _TITLES:
        lines.append(f"## {title}")
        lines.append("")
        claims = sections.get(key) or []
        if not claims:
            lines.append("None.")
            lines.append("")
            continue
        for claim in claims:
            text = claim.get("text", "").strip() if isinstance(claim, dict) else ""
            lines.append(text)
            lines.append("")
    lines.extend(_tokens(report.get("tokens") if isinstance(report.get("tokens"), dict) else {}))
    return "\n".join(lines)


def _tokens(tokens: dict) -> list[str]:
    rows = ["## Tokens", "", "| Agent | Input | Output |", "| --- | ---: | ---: |"]
    for name in _AGENTS:
        block = tokens.get(name) if isinstance(tokens.get(name), dict) else {}
        rows.append(f"| {name} | {_count(block.get('input'))} | {_count(block.get('output'))} |")
    rows.append("")
    return rows


def _count(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value
