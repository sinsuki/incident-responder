"""Optional summary rewrite. Ranking never calls this.

CODE_ARCHAEOLOGIST_LLM selects the provider. `off` (the default) keeps the
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
    "You write a short explanation of which commit most likely caused an incident. "
    "Use only the facts in the JSON digest. Do not invent commits, files, lines, "
    "or causes. Two or three sentences."
)


def apply_summary(report: dict) -> dict:
    provider = os.environ.get("CODE_ARCHAEOLOGIST_LLM", "off").strip().lower()
    if provider in _OFF:
        report["tokens"] = {"input": 0, "output": 0}
        return report
    if provider != "openai":
        raise ValueError(f"unknown CODE_ARCHAEOLOGIST_LLM provider: {provider}")
    summary, usage = _openai_summary(evidence_digest(report))
    report["summary"] = summary
    report["tokens"] = usage
    return report


def evidence_digest(report: dict) -> dict:
    """Facts the summary is allowed to use. This is not the service source."""
    ranked = []
    for row in report.get("ranked") or []:
        ranked.append(
            {
                "commit": row.get("commit"),
                "file": row.get("file"),
                "line": row.get("line"),
                "score": row.get("score"),
            }
        )
    return {
        "claims": report.get("claims"),
        "commit": report.get("commit"),
        "incident": report.get("incident"),
        "kind": report.get("kind"),
        "ranked": ranked,
        "score": report.get("score"),
        "service": report.get("service"),
    }


def _openai_summary(digest: dict) -> tuple[str, dict]:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise ValueError("CODE_ARCHAEOLOGIST_LLM=openai requires OPENAI_API_KEY")
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
