"""Read a log forensics report into the fields the ranker is allowed to use.

ground_truth.json is not a field here. Extra keys on the report are ignored,
including a deployed commit or a fault marker if one was copied in.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SERVICES = ("gateway", "orders", "inventory", "payments")
KINDS = ("latency", "timeout", "error_rate")
_TIMEOUT = re.compile(r"timed out after (\d+)ms")


@dataclass(frozen=True)
class Profile:
    incident: bool
    service: str | None
    kind: str | None
    started_at_unix_nano: int | None
    baseline_ms: float | None
    incident_ms: float | None
    signature: str | None
    timeout_ms: int | None


def read_profile(report: dict) -> Profile:
    if not isinstance(report, dict):
        raise ValueError("forensics report is not an object")
    if "incident" not in report:
        raise ValueError("forensics report is missing incident")
    incident = report.get("incident")
    if not isinstance(incident, bool):
        raise ValueError("forensics report incident is not a boolean")
    if not incident:
        return Profile(False, None, None, None, None, None, None, None)

    service = report.get("service")
    if service not in SERVICES:
        raise ValueError(f"forensics report service is not one of {', '.join(SERVICES)}")
    kind = report.get("kind")
    if kind not in KINDS:
        raise ValueError(f"forensics report kind is not one of {', '.join(KINDS)}")
    started = _int(report.get("started_at_unix_nano"), "started_at_unix_nano")
    stats = report.get("stats")
    if not isinstance(stats, dict):
        raise ValueError("forensics report is missing stats")
    baseline = _number(stats.get("baseline_duration_ms"), "baseline_duration_ms")
    incident_ms = _number(stats.get("incident_duration_ms"), "incident_duration_ms")
    signature = stats.get("signature")
    if signature is not None and not isinstance(signature, str):
        raise ValueError("forensics report signature is not a string")
    timeout_ms = None
    if kind == "timeout" and signature:
        match = _TIMEOUT.search(signature)
        if match:
            timeout_ms = int(match.group(1))
    return Profile(
        incident=True,
        service=service,
        kind=kind,
        started_at_unix_nano=started,
        baseline_ms=baseline,
        incident_ms=incident_ms,
        signature=signature,
        timeout_ms=timeout_ms,
    )


def _int(value, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"forensics report {name} is not an integer")
    return value


def _number(value, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"forensics report {name} is not a number")
    return float(value)
