"""Run one fault through the orchestrator and print the verifier result.

The scenario is latency_spike, seed 1, 24 requests, 8 of them warmup.
That is the same case as examples/latency_spike/.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAULT = "latency_spike"
SEED = "1"
OUT = Path("runs/demo")


def main() -> int:
    out = ROOT / OUT
    ran = subprocess.run(
        [
            sys.executable,
            "-m",
            "orchestrator",
            "--fault",
            FAULT,
            "--seed",
            SEED,
            "--out",
            str(out),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if ran.returncode != 0:
        sys.stderr.write(ran.stderr)
        if ran.stdout:
            sys.stderr.write(ran.stdout)
        return ran.returncode

    report_md = out / "rca.md"
    summary = _summary(report_md.read_text(encoding="utf-8"))
    verify = subprocess.run(
        [
            sys.executable,
            "-m",
            "orchestrator.verify",
            str(out / "rca.json"),
            "--run",
            str(out),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    print(f"fault {FAULT}")
    print(f"seed {SEED}")
    if summary:
        print()
        print(summary)
        print()
    print(f"report {OUT / 'rca.md'}")
    if verify.returncode == 0:
        print("verify ok")
        return 0
    print("verify failed")
    sys.stderr.write(verify.stderr)
    if verify.stdout:
        sys.stderr.write(verify.stdout)
    return verify.returncode


def _summary(text: str) -> str:
    lines = []
    in_summary = False
    for line in text.splitlines():
        if line.startswith("## Summary"):
            in_summary = True
            continue
        if in_summary and line.startswith("## "):
            break
        if in_summary:
            lines.append(line)
    return "\n".join(lines).strip()


if __name__ == "__main__":
    raise SystemExit(main())
