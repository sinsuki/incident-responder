"""Load the shop's markdown runbooks.

Each file has a short front matter (id, title, kind, line shape) and one
or more `##` steps. A step's `action:` line is what the applier runs.
The prose under it is the step text, with `{placeholders}` filled later.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_KINDS = {"latency", "timeout", "error_rate"}
_LINES = {"duration", "timeout_constant", "constant", "predicate", "none"}
_ACTIONS = {"rollback", "revert_config", "raise_timeout", "shed_load"}
_FILES = {"gateway.py", "orders.py", "inventory.py", "payments.py"}
_SLUG = re.compile(r"[a-z][a-z0-9-]*")
_NAME = re.compile(r"[A-Z][A-Z0-9_]*")
_PAIR = re.compile(r"([a-z_]+): (.+)")


@dataclass(frozen=True)
class StepTemplate:
    section: str
    action: str
    text: str
    params: tuple[tuple[str, str], ...]

    def param(self, key: str) -> str | None:
        for name, value in self.params:
            if name == key:
                return value
        return None


@dataclass(frozen=True)
class Runbook:
    id: str
    title: str
    kind: str
    line: str
    path: Path
    steps: tuple[StepTemplate, ...]


def default_directory() -> Path:
    return Path(__file__).resolve().parents[1] / "runbooks"


def load_runbooks(directory: Path | str) -> list[Runbook]:
    directory = Path(directory)
    if not directory.is_dir():
        raise FileNotFoundError(f"runbook directory not found: {directory}")
    paths = sorted(path for path in directory.glob("*.md") if path.is_file())
    if not paths:
        raise FileNotFoundError(f"no runbooks in {directory}")
    books = [_parse(path) for path in paths]
    ids = [book.id for book in books]
    if len(ids) != len(set(ids)):
        raise ValueError("runbook ids are not unique")
    return books


def _parse(path: Path) -> Runbook:
    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("---\n"):
        raise ValueError(f"{path.name} is missing front matter")
    end = raw.find("\n---\n", 4)
    if end < 0:
        raise ValueError(f"{path.name} front matter does not close")
    meta = _front(raw[4:end], path)
    steps = _sections(raw[end + 5 :], path)
    return Runbook(
        id=meta["id"],
        title=meta["title"],
        kind=meta["kind"],
        line=meta["line"],
        path=path,
        steps=steps,
    )


def _front(block: str, path: Path) -> dict[str, str]:
    meta = _pairs(block, path, path.name)
    if set(meta) != {"id", "title", "kind", "line"}:
        raise ValueError(f"{path.name} front matter must be id, title, kind, and line")
    if not _SLUG.fullmatch(meta["id"]):
        raise ValueError(f"{path.name} id is not a slug")
    if meta["kind"] not in _KINDS:
        raise ValueError(f"{path.name} kind is not latency, timeout, or error_rate")
    if meta["line"] not in _LINES:
        raise ValueError(f"{path.name} line shape is unknown")
    return meta


def _sections(body: str, path: Path) -> tuple[StepTemplate, ...]:
    parts = re.split(r"(?m)^## ", body)
    if len(parts) < 2:
        raise ValueError(f"{path.name} has no steps")
    steps = []
    seen = set()
    for part in parts[1:]:
        lines = part.splitlines()
        section = lines[0].strip()
        if not section:
            raise ValueError(f"{path.name} has an empty section")
        if section in seen:
            raise ValueError(f"{path.name} repeats section {section!r}")
        seen.add(section)
        meta, text = _section_body(lines[1:], path, section)
        steps.append(_step(path, section, meta, text))
    return tuple(steps)


def _section_body(lines: list[str], path: Path, section: str) -> tuple[dict[str, str], str]:
    index = 0
    while index < len(lines) and not lines[index].strip():
        index += 1
    meta: dict[str, str] = {}
    while index < len(lines):
        match = _PAIR.fullmatch(lines[index].strip())
        if match is None:
            break
        key, value = match.group(1), match.group(2).strip()
        if key in meta:
            raise ValueError(f"{path.name} section {section!r} repeats {key}")
        meta[key] = value
        index += 1
    if "action" not in meta:
        raise ValueError(f"{path.name} section {section!r} has no action")
    text = "\n".join(lines[index:]).strip()
    return meta, text


def _step(path: Path, section: str, meta: dict[str, str], text: str) -> StepTemplate:
    action = meta["action"]
    if action not in _ACTIONS:
        raise ValueError(f"{path.name} section {section!r} has unknown action {action}")
    extra = set(meta) - {"action", "file", "constant"}
    if extra:
        raise ValueError(f"{path.name} section {section!r} has unknown keys {sorted(extra)}")
    if not text:
        raise ValueError(f"{path.name} section {section!r} has no text")
    params = {}
    if "file" in meta:
        if meta["file"] not in _FILES:
            raise ValueError(f"{path.name} section {section!r} file is not a service module")
        params["file"] = meta["file"]
    if "constant" in meta:
        if not _NAME.fullmatch(meta["constant"]):
            raise ValueError(f"{path.name} section {section!r} constant is not a name")
        params["constant"] = meta["constant"]
    return StepTemplate(section, action, text, tuple(params.items()))


def _pairs(block: str, path: Path, where: str) -> dict[str, str]:
    found = {}
    for line in block.splitlines():
        if not line.strip():
            continue
        match = _PAIR.fullmatch(line.strip())
        if match is None:
            raise ValueError(f"{where} has a bad line: {line}")
        key, value = match.group(1), match.group(2).strip()
        if key in found:
            raise ValueError(f"{where} repeats {key}")
        found[key] = value
    if not found:
        raise ValueError(f"{path.name} has empty front matter")
    return found
