"""Keep runbook tests on the deterministic summary."""

import pytest


@pytest.fixture(autouse=True)
def _runbook_llm_off(monkeypatch):
    monkeypatch.delenv("RUNBOOK_LLM", raising=False)
