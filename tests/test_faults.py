"""The injected fault is the one the telemetry and ground truth describe."""

import random
import subprocess
from pathlib import Path

import pytest

from incident_sim.checkout import AMOUNT_CENTS, response_code
from incident_sim.clock import MS
from incident_sim.faults import FAULTS
from incident_sim.history import clone, load_revision
from incident_sim.scenario import run
from tests.helpers import load_run

FAULT_NAMES = sorted(FAULTS)


@pytest.mark.parametrize("fault", FAULT_NAMES)
def test_ground_truth_matches_the_telemetry(tmp_path, fault):
    seed = 11
    requests = 20
    warmup = 6
    out = tmp_path / fault
    run(fault, seed=seed, requests=requests, warmup=warmup, out=out)
    data = load_run(out)
    truth = data["ground_truth"]
    spec = FAULTS[fault]

    assert truth["fault"] == spec.name
    assert truth["service"] == spec.service
    assert truth["path"] == spec.path
    assert truth["marker"] == spec.marker
    assert truth["seed"] == seed
    assert truth["requests"] == requests
    assert truth["warmup_requests"] == warmup
    assert truth["summary"] == spec.summary

    first_fault = _span(data["traces"], "POST /checkout", f"ord-{warmup:04d}")
    last_healthy = _span(data["traces"], "POST /checkout", f"ord-{warmup - 1:04d}")
    assert truth["started_at_unix_nano"] == first_fault["start_time_unix_nano"]
    assert last_healthy["end_time_unix_nano"] < truth["started_at_unix_nano"]

    repo = tmp_path / "repo"
    clone(repo)
    parent = load_revision(repo, truth["parent_commit"])
    deployed = load_revision(repo, truth["deployed_commit"])
    _assert_revision_behavior(fault, parent, deployed, data, seed, requests, warmup)
    _assert_metrics(fault, parent, deployed, data, requests, warmup)

    blamed = _blame(repo, truth["deployed_commit"], spec.path, spec.marker)
    assert blamed == truth["deployed_commit"]
    parent_source = _show(repo, truth["parent_commit"], spec.path)
    assert not any(line.strip() == spec.marker for line in parent_source.splitlines())


def _assert_revision_behavior(fault, parent, deployed, data, seed, requests, warmup):
    traces = data["traces"]
    logs = data["logs"]
    if fault == "latency_spike":
        for span in traces:
            if span["name"] != "reserve":
                continue
            index = _index(span)
            expected = parent.inventory.WORK_MS if index < warmup else deployed.inventory.WORK_MS
            assert span["end_time_unix_nano"] - span["start_time_unix_nano"] == expected * MS
            assert span["status"] == "OK"
        assert deployed.inventory.WORK_MS > parent.inventory.WORK_MS
        return

    if fault == "dependency_timeout":
        assert deployed.payments.WORK_MS > deployed.orders.PAYMENTS_TIMEOUT_MS
        assert parent.payments.WORK_MS <= parent.orders.PAYMENTS_TIMEOUT_MS
        for span in traces:
            if span["name"] != "POST /charge":
                continue
            index = _index(span)
            active = deployed if index >= warmup else parent
            if span["kind"] == "SERVER":
                assert span["end_time_unix_nano"] - span["start_time_unix_nano"] == active.payments.WORK_MS * MS
            if span["kind"] == "CLIENT" and index >= warmup:
                duration = span["end_time_unix_nano"] - span["start_time_unix_nano"]
                assert duration == active.orders.PAYMENTS_TIMEOUT_MS * MS
                assert span["status"] == "ERROR"
                assert span["status_description"] == f"payments timed out after {active.orders.PAYMENTS_TIMEOUT_MS}ms"
        timeout_logs = [log for log in logs if "timed out" in log["body"]]
        assert timeout_logs
        assert all(_index_from_log(log, traces) >= warmup for log in timeout_logs)
        return

    _assert_charge_results(parent, deployed, traces, logs, seed, requests, warmup)


def _assert_metrics(fault, parent, deployed, data, requests, warmup):
    started = data["ground_truth"]["started_at_unix_nano"]
    window = requests - warmup
    if fault == "latency_spike":
        early, late = _split(data["metrics"], "inventory", "duration_ms", started)
        assert _highest(early) == parent.inventory.WORK_MS
        assert _highest(late) == deployed.inventory.WORK_MS
        return
    if fault == "dependency_timeout":
        early, late = _split(data["metrics"], "payments", "duration_ms", started)
        assert _highest(early) == parent.payments.WORK_MS
        assert _highest(late) == deployed.payments.WORK_MS
        return
    early, late = _split(data["metrics"], "payments", "requests", started)
    error_delta = _count(late, "error") - _count(early, "error")
    ok_delta = _count(late, "ok") - _count(early, "ok")
    if fault == "bad_deploy":
        assert ok_delta == 0
        assert error_delta == window
        return
    assert error_delta > ok_delta
    assert error_delta > window / 2


def _split(metrics, service, name, started_at):
    early = []
    late = []
    for point in metrics:
        if point["service"] != service or point["name"] != name:
            continue
        if point["time_unix_nano"] < started_at:
            early.append(point)
        else:
            late.append(point)
    assert early and late
    return early, late


def _count(points, status):
    return sum(point["value"] for point in points if point["type"] == "sum" and point["attributes"].get("status") == status)


def _highest(points):
    return max(point["max"] for point in points if point["type"] == "histogram")


def _assert_charge_results(parent, deployed, traces, logs, seed, requests, warmup):
    rng = random.Random(seed)
    for index in range(requests):
        code = response_code(rng)
        active = deployed if index >= warmup else parent
        server = _server(traces, index)
        assert server["attributes"]["response.code"] == code
        try:
            active.payments.charge(AMOUNT_CENTS, code)
        except (ValueError, RuntimeError) as exc:
            assert server["status"] == "ERROR"
            message = str(exc)
            assert any(message in log["body"] for log in _logs_for(logs, server))
        else:
            assert server["status"] == "OK"
            assert any(log["body"] == "charge approved" for log in _logs_for(logs, server))


def _span(traces, name, order_id):
    found = [
        span
        for span in traces
        if span["name"] == name and span["attributes"].get("order.id") == order_id
    ]
    assert len(found) == 1
    return found[0]


def _server(traces, index):
    order_id = f"ord-{index:04d}"
    found = [
        span
        for span in traces
        if span["name"] == "POST /charge"
        and span["kind"] == "SERVER"
        and span["attributes"]["order.id"] == order_id
    ]
    assert len(found) == 1
    return found[0]


def _logs_for(logs, span):
    return [log for log in logs if log["span_id"] == span["span_id"]]


def _index(span) -> int:
    return int(span["attributes"]["order.id"].split("-")[1])


def _index_from_log(log, traces) -> int:
    span = next(span for span in traces if span["span_id"] == log["span_id"])
    return _index(span)


def _show(repo: Path, commit: str, path: str) -> str:
    return subprocess.check_output(
        ["git", "show", f"{commit}:{path}"],
        cwd=repo,
        text=True,
    )


def _blame(repo: Path, commit: str, path: str, marker: str) -> str:
    source = _show(repo, commit, path)
    line_numbers = [index + 1 for index, line in enumerate(source.splitlines()) if line.strip() == marker]
    assert len(line_numbers) == 1
    line = line_numbers[0]
    porcelain = subprocess.check_output(
        ["git", "blame", "-L", f"{line},{line}", "--porcelain", commit, "--", path],
        cwd=repo,
        text=True,
    )
    return porcelain.splitlines()[0].split()[0]
