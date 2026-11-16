"""Named faults. Each one is a commit in the sample service history."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Fault:
    name: str
    service: str
    path: str
    marker: str
    summary: str


FAULTS = {
    "latency_spike": Fault(
        name="latency_spike",
        service="inventory",
        path="inventory.py",
        marker="_rebuild_catalog_index()",
        summary="Reserve rebuilds the catalog index on every call, so inventory work jumps from 12ms to 750ms.",
    ),
    "error_rate_spike": Fault(
        name="error_rate_spike",
        service="payments",
        path="payments.py",
        marker="if response_code not in RETRYABLE:",
        summary="The processor check is inverted, so ordinary approval codes fail and retryable codes do not.",
    ),
    "dependency_timeout": Fault(
        name="dependency_timeout",
        service="payments",
        path="payments.py",
        marker="_wait_for_connection()",
        summary="Charge waits on a stuck pool socket for 2000ms, and orders stops at its 800ms deadline.",
    ),
    "bad_deploy": Fault(
        name="bad_deploy",
        service="payments",
        path="payments.py",
        marker="CURRENCY_SCALE = 100",
        summary="The deployed config scales cent amounts by 100, so an 8000 cent charge is rejected as 800000.",
    ),
}
