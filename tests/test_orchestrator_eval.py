"""A case passes only when the cause, the mitigation, and the citations all hold."""

from orchestrator.eval import score_case

COMMIT = "a" * 40


def test_all_three_score_one():
    scored = score_case(_report(COMMIT), _truth(COMMIT), {"incident": False}, [])
    assert scored["root_cause_ok"] is True
    assert scored["cleared"] is True
    assert scored["citation_ok"] is True
    assert scored["score"] == 1
    assert scored["passed"] is True
    assert scored["input_tokens"] == 0
    assert scored["output_tokens"] == 0


def test_wrong_commit_scores_zero():
    scored = score_case(_report("b" * 40), _truth(COMMIT), {"incident": False}, [])
    assert scored["root_cause_ok"] is False
    assert scored["cleared"] is True
    assert scored["citation_ok"] is True
    assert scored["score"] == 0
    assert scored["passed"] is False


def test_wrong_service_scores_zero():
    report = _report(COMMIT)
    report["service"] = "gateway"
    scored = score_case(report, _truth(COMMIT), {"incident": False}, [])
    assert scored["root_cause_ok"] is False
    assert scored["score"] == 0


def test_remaining_incident_scores_zero():
    scored = score_case(_report(COMMIT), _truth(COMMIT), {"incident": True}, [])
    assert scored["cleared"] is False
    assert scored["root_cause_ok"] is True
    assert scored["score"] == 0
    assert scored["passed"] is False


def test_citation_failure_scores_zero_even_when_cleared():
    report = _report(COMMIT)
    report["tokens"]["total"] = {"input": 3, "output": 4}
    report["tokens"]["orchestrator"] = {"input": 3, "output": 4}
    scored = score_case(report, _truth(COMMIT), {"incident": False}, ["summary claim 0 does not resolve"])
    assert scored["cleared"] is True
    assert scored["citation_ok"] is False
    assert scored["score"] == 0
    assert scored["passed"] is False
    assert scored["input_tokens"] == 3
    assert scored["output_tokens"] == 4
    assert scored["parts"]["orchestrator"] == {"input": 3, "output": 4}


def test_skipped_replay_scores_zero():
    scored = score_case(_report(COMMIT), _truth(COMMIT), None, [])
    assert scored["cleared"] is False
    assert scored["score"] == 0


def _report(commit: str) -> dict:
    zeros = {"input": 0, "output": 0}
    return {
        "incident": True,
        "matched": True,
        "service": "inventory",
        "commit": commit,
        "runbook": "rollback-latency",
        "tokens": {
            "forensics": dict(zeros),
            "archaeologist": dict(zeros),
            "runbook": dict(zeros),
            "orchestrator": dict(zeros),
            "total": dict(zeros),
        },
    }


def _truth(commit: str) -> dict:
    return {"service": "inventory", "deployed_commit": commit}
