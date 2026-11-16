"""Optional sentence rewrite. The report is built before this runs.

ORCHESTRATOR_LLM selects the provider. `off` (the default) keeps the
deterministic sentences and records zero tokens. `openai` posts the
sentences, not the telemetry and not the service source, to an
OpenAI-compatible chat endpoint. OPENAI_API_KEY is required.
OPENAI_BASE_URL and OPENAI_MODEL override the endpoint and the model.

An extra sentence is kept, with no citation, so the verifier can reject
it. Token counts come from the response usage field.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from orchestrator.tokens import retotal

_OFF = {"", "off", "none", "deterministic"}
_SECTIONS = ("summary", "impact", "timeline", "root_cause", "evidence", "mitigation")
_SYSTEM = (
    "You polish root-cause sentences for an on-call engineer. "
    "Return JSON with the same section keys and the same sentences. "
    "Keep every trace id, span id, timestamp, commit, file:line, and runbook "
    "section exactly as written. Do not add sentences, ids, times, commits, "
    "files, or causes."
)


def apply_prose(report: dict) -> dict:
    provider = os.environ.get("ORCHESTRATOR_LLM", "off").strip().lower()
    if provider in _OFF:
        report["tokens"]["orchestrator"] = {"input": 0, "output": 0}
        retotal(report["tokens"])
        return report
    if provider != "openai":
        raise ValueError(f"unknown ORCHESTRATOR_LLM provider: {provider}")
    rewritten, usage = _openai(evidence_digest(report))
    _replace(report, rewritten)
    report["tokens"]["orchestrator"] = usage
    retotal(report["tokens"])
    return report


def evidence_digest(report: dict) -> dict:
    """The sentences the model may reword. This is not the telemetry."""
    sections = {}
    source = report.get("sections") if isinstance(report.get("sections"), dict) else {}
    for name in _SECTIONS:
        claims = source.get(name) or []
        sections[name] = [claim.get("text") for claim in claims if isinstance(claim, dict)]
    return {"sections": sections}


def _replace(report: dict, payload: dict) -> None:
    if not isinstance(payload, dict):
        raise ValueError("openai response did not include the report sections")
    sections = payload.get("sections")
    if not isinstance(sections, dict):
        raise ValueError("openai response did not include the report sections")
    for name in _SECTIONS:
        texts = sections.get(name)
        old = report["sections"][name]
        if not isinstance(texts, list) or not isinstance(old, list):
            raise ValueError(f"openai response is missing {name}")
        if len(texts) < len(old):
            raise ValueError("openai response dropped a report sentence")
        rebuilt = []
        for index, text in enumerate(texts):
            if not isinstance(text, str) or not text.strip():
                raise ValueError("openai response included an empty sentence")
            citations = old[index]["citations"] if index < len(old) else []
            rebuilt.append({"text": text.strip(), "citations": list(citations)})
        report["sections"][name] = rebuilt


def _openai(digest: dict) -> tuple[dict, dict]:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise ValueError("ORCHESTRATOR_LLM=openai requires OPENAI_API_KEY")
    base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    body = {
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": json.dumps(digest, sort_keys=True)},
        ],
        "model": model,
        "temperature": 0,
    }
    request = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise ValueError(f"openai request failed with HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ValueError(f"openai request failed: {exc.reason}") from exc

    try:
        content = payload["choices"][0]["message"]["content"].strip()
        usage = payload["usage"]
        counted = {"input": int(usage["prompt_tokens"]), "output": int(usage["completion_tokens"])}
        parsed = json.loads(content)
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("openai response did not include a summary and token usage") from exc
    if counted["input"] < 0 or counted["output"] < 0:
        raise ValueError("openai response did not include a summary and token usage")
    return parsed, counted
