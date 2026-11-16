"""Optional summary rewrite. Parsing and detection never call this.

LOG_FORENSICS_LLM selects the provider. `off` (the default) keeps the
deterministic summary and records zero tokens. `openai` posts the evidence
digest to an OpenAI-compatible chat endpoint. OPENAI_API_KEY is required.
OPENAI_BASE_URL and OPENAI_MODEL override the endpoint and the model.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

_OFF = {"", "off", "none", "deterministic"}
_SYSTEM = (
    "You write a short incident summary for an on-call engineer. "
    "Use only the facts in the JSON digest. Do not invent services, times, "
    "ids, or causes. Two or three sentences."
)


def apply_summary(report: dict) -> dict:
    provider = os.environ.get("LOG_FORENSICS_LLM", "off").strip().lower()
    if provider in _OFF:
        report["tokens"] = {"input": 0, "output": 0}
        return report
    if provider != "openai":
        raise ValueError(f"unknown LOG_FORENSICS_LLM provider: {provider}")
    summary, usage = _openai_summary(evidence_digest(report))
    report["summary"] = summary
    report["tokens"] = usage
    return report


def evidence_digest(report: dict) -> dict:
    """Facts the summary is allowed to use. This is not the raw telemetry."""
    return {
        "claims": report["claims"],
        "incident": report["incident"],
        "kind": report["kind"],
        "service": report["service"],
        "started_at_unix_nano": report["started_at_unix_nano"],
        "stats": report["stats"],
    }


def _openai_summary(digest: dict) -> tuple[str, dict]:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise ValueError("LOG_FORENSICS_LLM=openai requires OPENAI_API_KEY")
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
        text = payload["choices"][0]["message"]["content"].strip()
        usage = payload["usage"]
        input_tokens = int(usage["prompt_tokens"])
        output_tokens = int(usage["completion_tokens"])
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ValueError("openai response did not include a summary and token usage") from exc
    if not text:
        raise ValueError("openai response did not include a summary and token usage")
    return text, {"input": input_tokens, "output": output_tokens}
