"""The eval score is service match times how close the onset is."""

from log_forensics.eval import score_case


def test_exact_match_scores_one():
    report = _report("payments", 5_000_000_000)
    truth = {"service": "payments", "started_at_unix_nano": 5_000_000_000}
    scored = score_case(report, truth)
    assert scored["service_ok"] is True
    assert scored["onset_delta_ms"] == 0
    assert scored["score"] == 1
    assert scored["passed"] is True
    assert scored["input_tokens"] == 0
    assert scored["output_tokens"] == 0


def test_onset_error_reduces_the_score():
    report = _report("inventory", 5_500_000_000)
    truth = {"service": "inventory", "started_at_unix_nano": 5_000_000_000}
    scored = score_case(report, truth)
    assert scored["onset_delta_ms"] == 500
    assert scored["score"] == 0.5
    assert scored["passed"] is True


def test_wrong_service_scores_zero():
    report = _report("gateway", 5_000_000_000)
    truth = {"service": "payments", "started_at_unix_nano": 5_000_000_000}
    scored = score_case(report, truth)
    assert scored["service_ok"] is False
    assert scored["score"] == 0
    assert scored["passed"] is False


def test_no_incident_scores_zero():
    report = {
        "incident": False,
        "service": None,
        "started_at_unix_nano": None,
        "tokens": {"input": 0, "output": 0},
    }
    truth = {"service": "payments", "started_at_unix_nano": 5_000_000_000}
    scored = score_case(report, truth)
    assert scored["onset_delta_ms"] is None
    assert scored["score"] == 0
    assert scored["passed"] is False


def _report(service, started):
    return {
        "incident": True,
        "service": service,
        "started_at_unix_nano": started,
        "tokens": {"input": 0, "output": 0},
    }
