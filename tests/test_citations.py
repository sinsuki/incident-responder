"""Citations have to point at a real telemetry line."""

import json

from incident_sim.scenario import run
from log_forensics import investigate
from log_forensics.check import check_citations


def test_real_report_citations_resolve(tmp_path):
    out = tmp_path / "run"
    run("error_rate_spike", seed=2, requests=16, warmup=6, out=out)
    report = investigate(out)
    assert check_citations(report, out) == []
    onset = report["started_at_unix_nano"]
    cited_starts = [
        citation["timestamp_unix_nano"]
        for claim in report["claims"]
        for citation in claim["citations"]
        if citation["file"] == "traces.jsonl"
    ]
    assert onset in cited_starts


def test_wrong_trace_id_does_not_resolve(tmp_path):
    out, report = _report(tmp_path)
    report["claims"][0]["citations"][0]["trace_id"] = "0" * 32
    problems = check_citations(report, out)
    assert problems
    assert any("does not resolve" in problem for problem in problems)
    assert any("trace_id" in problem for problem in problems)


def test_wrong_line_does_not_resolve(tmp_path):
    out, report = _report(tmp_path)
    report["claims"][0]["citations"][0]["line"] = 10_000
    problems = check_citations(report, out)
    assert any("past the end" in problem for problem in problems)


def test_timestamp_mismatch_does_not_resolve(tmp_path):
    out, report = _report(tmp_path)
    log_citation = next(
        citation
        for citation in report["claims"][0]["citations"]
        if citation["file"] == "logs.jsonl"
    )
    log_citation["timestamp_unix_nano"] += 1
    problems = check_citations(report, out)
    assert any("timestamp" in problem for problem in problems)


def test_claim_without_citations_does_not_resolve(tmp_path):
    out, report = _report(tmp_path)
    report["claims"][0]["citations"] = []
    problems = check_citations(report, out)
    assert any("no citations" in problem for problem in problems)


def test_incident_without_claims_does_not_resolve(tmp_path):
    out, report = _report(tmp_path)
    report["claims"] = []
    problems = check_citations(report, out)
    assert any("no claims" in problem for problem in problems)


def test_metric_file_is_not_a_citation(tmp_path):
    out, report = _report(tmp_path)
    report["claims"][0]["citations"][0]["file"] = "metrics.jsonl"
    problems = check_citations(report, out)
    assert any("not a trace or log" in problem for problem in problems)


def test_citation_without_an_id_does_not_resolve(tmp_path):
    out, report = _report(tmp_path)
    citation = report["claims"][0]["citations"][0]
    citation["trace_id"] = ""
    citation["span_id"] = ""
    problems = check_citations(report, out)
    assert any("neither trace_id nor span_id" in problem for problem in problems)


def test_synthetic_log_line_resolves(tmp_path):
    log = {
        "attributes": {"order.id": "ord-0000"},
        "body": "charge approved",
        "service": "payments",
        "severity": "INFO",
        "span_id": "abc123abc123abcd",
        "timestamp_unix_nano": 100,
        "trace_id": "1234" * 8,
    }
    (tmp_path / "logs.jsonl").write_text(json.dumps(log) + "\n", encoding="utf-8")
    (tmp_path / "traces.jsonl").write_text("", encoding="utf-8")
    report = {
        "incident": True,
        "claims": [
            {
                "text": "payments logged 'charge approved' at 100.",
                "citations": [
                    {
                        "file": "logs.jsonl",
                        "line": 1,
                        "span_id": log["span_id"],
                        "timestamp_unix_nano": 100,
                        "trace_id": log["trace_id"],
                    }
                ],
            }
        ],
    }
    assert check_citations(report, tmp_path) == []


def _report(tmp_path):
    out = tmp_path / "run"
    run("latency_spike", seed=1, requests=12, warmup=4, out=out)
    return out, investigate(out)
