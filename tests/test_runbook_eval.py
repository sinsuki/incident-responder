"""Mitigation scores 1 only when the re-run is clean and the citations resolve."""

from runbook.eval import score_case


def test_cleared_incident_scores_one():
    report = {"matched": True, "runbook": "rollback-latency", "tokens": {"input": 0, "output": 0}}
    scored = score_case(report, {"incident": False}, [])
    assert scored["matched"] is True
    assert scored["cleared"] is True
    assert scored["citation_ok"] is True
    assert scored["score"] == 1
    assert scored["passed"] is True
    assert scored["input_tokens"] == 0
    assert scored["output_tokens"] == 0


def test_remaining_incident_scores_zero():
    report = {"matched": True, "runbook": "raise-timeout", "tokens": {"input": 0, "output": 0}}
    scored = score_case(report, {"incident": True}, [])
    assert scored["cleared"] is False
    assert scored["score"] == 0
    assert scored["passed"] is False


def test_citation_failure_scores_zero_even_when_cleared():
    report = {"matched": True, "runbook": "revert-config", "tokens": {"input": 3, "output": 4}}
    scored = score_case(report, {"incident": False}, ["step 0 does not resolve"])
    assert scored["cleared"] is True
    assert scored["citation_ok"] is False
    assert scored["score"] == 0
    assert scored["passed"] is False
    assert scored["input_tokens"] == 3
    assert scored["output_tokens"] == 4


def test_unmatched_scores_zero():
    report = {"matched": False, "runbook": None, "tokens": {"input": 0, "output": 0}}
    scored = score_case(report, {"incident": False}, [])
    assert scored["cleared"] is False
    assert scored["passed"] is False
    assert scored["score"] == 0


def test_skipped_replay_scores_zero():
    report = {"matched": True, "runbook": "shed-load", "tokens": {"input": 0, "output": 0}}
    scored = score_case(report, None, [])
    assert scored["cleared"] is False
    assert scored["score"] == 0
