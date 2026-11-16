"""Matching uses the cited line, not the fault name. Some reports match nothing."""

import pytest

from runbook import recommend
from runbook.check import check_citations

COMMIT = "a" * 40
PARENT = "b" * 40


def test_no_matching_runbook():
    forensics = _forensics("inventory", "latency", "reserve walked the catalog")
    archaeology = _archaeology("inventory.py", 9, "index[sku] = count")
    report = recommend(forensics, archaeology)
    assert report["matched"] is False
    assert report["steps"] == []
    assert report["runbook"] is None
    assert "index[sku] = count" in report["summary"]
    assert "other" in report["summary"]
    assert check_citations(report, forensics, archaeology) == []


def test_latency_with_no_commit_matches_nothing():
    forensics = _forensics("inventory", "latency", None)
    report = recommend(forensics, _no_commit())
    assert report["matched"] is False
    assert report["steps"] == []
    assert "none" in report["summary"]


def test_shed_load_when_no_commit_explains_the_errors():
    forensics = _forensics("payments", "error_rate", "charge failed: processor code 00")
    report = recommend(forensics, _no_commit())
    assert report["matched"] is True
    assert report["runbook"] == "shed-load"
    assert [step["action"] for step in report["steps"]] == ["shed_load"]
    assert report["steps"][0]["target"] == {"service": "payments"}
    assert "111" in report["steps"][0]["text"]
    assert check_citations(report, forensics, _no_commit()) == []


def test_duration_timeout_rolls_back_before_raising_the_deadline():
    forensics = _forensics(
        "payments",
        "timeout",
        "payments timed out after 800ms",
        baseline=48,
        incident=2000,
        timeout_claim=True,
    )
    archaeology = _archaeology("payments.py", 4, "WORK_MS = 2000", parent_text="WORK_MS = 48")
    report = recommend(forensics, archaeology)
    assert report["runbook"] == "rollback-timeout"
    assert [step["action"] for step in report["steps"]] == ["rollback", "raise_timeout"]
    assert report["steps"][0]["target"]["file"] == "payments.py"
    assert report["steps"][0]["target"]["parent"] == PARENT
    raised = report["steps"][1]["target"]
    assert raised["file"] == "orders.py"
    assert raised["constant"] == "PAYMENTS_TIMEOUT_MS"
    assert raised["value"] == 2000
    assert check_citations(report, forensics, archaeology) == []


def test_caller_deadline_raises_the_timeout_instead_of_rolling_back():
    forensics = _forensics(
        "orders",
        "timeout",
        "payments timed out after 50ms",
        baseline=40,
        incident=400,
    )
    archaeology = _archaeology(
        "orders.py",
        7,
        "PAYMENTS_TIMEOUT_MS = 50",
        parent_text="PAYMENTS_TIMEOUT_MS = 800",
    )
    report = recommend(forensics, archaeology)
    assert report["runbook"] == "raise-timeout"
    assert [step["action"] for step in report["steps"]] == ["raise_timeout"]
    assert report["steps"][0]["target"]["value"] == 400
    assert report["steps"][0]["target"]["file"] == "orders.py"
    assert check_citations(report, forensics, archaeology) == []


def test_inverted_check_rolls_back():
    forensics = _forensics("payments", "error_rate", "charge failed: processor code 00")
    archaeology = _archaeology(
        "payments.py",
        24,
        "if response_code not in RETRYABLE:",
        parent_text="if response_code in RETRYABLE:",
    )
    report = recommend(forensics, archaeology)
    assert report["runbook"] == "rollback-check"
    assert report["steps"][0]["action"] == "rollback"
    assert PARENT in report["steps"][0]["text"]
    assert "111" in report["steps"][0]["text"]


def test_config_constant_reverts_in_place():
    forensics = _forensics("payments", "error_rate", "charge failed: amount out of range: 800000")
    archaeology = _archaeology(
        "payments.py",
        5,
        "CURRENCY_SCALE = 100",
        parent_text="CURRENCY_SCALE = 1",
    )
    report = recommend(forensics, archaeology)
    assert report["runbook"] == "revert-config"
    assert report["steps"][0]["action"] == "revert_config"
    assert report["steps"][0]["target"]["value"] == 1
    assert report["steps"][0]["target"]["constant"] == "CURRENCY_SCALE"
    assert "Leave every other line" in report["steps"][0]["text"]


def test_missing_parent_does_not_invent_a_step():
    forensics = _forensics("inventory", "latency", None, baseline=12, incident=750)
    archaeology = _archaeology("inventory.py", 3, "WORK_MS = 750", parent=False)
    report = recommend(forensics, archaeology)
    assert report["matched"] is False
    assert report["steps"] == []
    assert "do not cite enough evidence" in report["summary"]
    assert check_citations(report, forensics, archaeology) == []


def test_two_runbooks_for_one_shape_are_rejected(tmp_path):
    text = _duration_book("one")
    (tmp_path / "one.md").write_text(text, encoding="utf-8")
    (tmp_path / "two.md").write_text(_duration_book("two"), encoding="utf-8")
    forensics = _forensics("inventory", "latency", None, baseline=12, incident=750)
    archaeology = _archaeology("inventory.py", 3, "WORK_MS = 750", parent_text="WORK_MS = 12")
    with pytest.raises(ValueError, match="more than one runbook"):
        recommend(forensics, archaeology, runbooks=tmp_path)


def test_service_mismatch_is_rejected():
    forensics = _forensics("payments", "error_rate", "charge failed: processor code 00")
    archaeology = _archaeology("inventory.py", 3, "WORK_MS = 750", service="inventory", kind="latency")
    with pytest.raises(ValueError, match="service"):
        recommend(forensics, archaeology)


def test_short_hash_is_rejected():
    forensics = _forensics("payments", "latency", None, baseline=48, incident=750)
    archaeology = _archaeology("payments.py", 4, "WORK_MS = 750")
    archaeology["commit"] = "abc"
    archaeology["ranked"][0]["commit"] = "abc"
    with pytest.raises(ValueError, match="full hash"):
        recommend(forensics, archaeology)


def _forensics(service, kind, signature, baseline=48, incident=48, timeout_claim=False):
    claims = [
        {
            "text": "onset",
            "citations": [
                {"file": "logs.jsonl", "line": 1, "timestamp_unix_nano": 111, "trace_id": "trace"},
            ],
        }
    ]
    if timeout_claim:
        claims.append(
            {
                "text": "orders logged 'payments timed out after 800ms' at 222",
                "citations": [
                    {"file": "logs.jsonl", "line": 2, "timestamp_unix_nano": 222, "trace_id": "trace"},
                ],
            }
        )
    return {
        "incident": True,
        "service": service,
        "kind": kind,
        "started_at_unix_nano": 100,
        "stats": {
            "baseline_duration_ms": baseline,
            "incident_duration_ms": incident,
            "signature": signature,
        },
        "claims": claims,
    }


def _archaeology(path, line, text, parent_text="WORK_MS = 12", service=None, kind=None, parent=True):
    claims = [
        {
            "text": f"{path}:{line} at {COMMIT} is {text}",
            "citations": [{"commit": COMMIT, "file": path, "line": line, "text": text}],
        }
    ]
    if parent:
        claims.append(
            {
                "text": f"parent has {parent_text}",
                "citations": [{"commit": PARENT, "file": path, "line": line, "text": parent_text}],
            }
        )
    return {
        "incident": True,
        "service": service,
        "kind": kind,
        "commit": COMMIT,
        "score": 0.9,
        "ranked": [{"commit": COMMIT, "file": path, "line": line, "score": 0.9, "text": text}],
        "claims": claims,
    }


def _no_commit():
    return {
        "incident": False,
        "service": None,
        "kind": None,
        "commit": None,
        "ranked": [],
        "claims": [],
    }


def _duration_book(slug: str) -> str:
    return (
        "---\n"
        f"id: {slug}\n"
        f"title: {slug}\n"
        "kind: latency\n"
        "line: duration\n"
        "---\n"
        "\n"
        f"# {slug}\n"
        "\n"
        "## Do the thing\n"
        "\n"
        "action: rollback\n"
        "\n"
        "Deploy `{file}` from parent `{parent}` in place of `{commit}`. "
        "The line `{line_text}` moved `{service}` from `{baseline_ms}`ms to "
        "`{incident_ms}`ms. The parent line is `{parent_text}`. "
        "The onset log is at `{timestamp}`.\n"
    )
