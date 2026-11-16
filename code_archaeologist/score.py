"""Score one parent/child pair of a service file against a forensics profile.

The commit message is not an input. A latency or timeout score is how closely
a changed `*_MS` constant matches the before/after durations. An error-rate
score is either an inverted check that guards the new log message, or a
changed multiplier that makes the reported number newly fail the range check.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass

from code_archaeologist.load import Profile

CONSTANT_SCORE = 0.95
PREDICATE_SCORE = 0.9
NEARBY_SCORE = 0.2
OTHER_SCORE = 0.05

_PLACEHOLDER = re.compile(r"^([^{]*)\{([A-Za-z_][A-Za-z0-9_]*)\}([^{]*)$")
_FSTRING = re.compile(r"""f(['"])(.+?)\1""")
_CALL = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")


@dataclass(frozen=True)
class Explanation:
    score: float
    line: int
    line_text: str
    parent_line: int | None
    parent_text: str | None
    label: str
    detail: str
    extra: tuple[tuple[int, str], ...] = ()


@dataclass(frozen=True)
class _Anchor:
    line: int
    name: str
    value: str


def score_pair(profile: Profile, old: str, new: str) -> Explanation | None:
    if _code_lines(old) == _code_lines(new):
        return None
    if profile.kind in {"latency", "timeout"}:
        return _score_duration(profile, old, new) or _score_other(old, new)
    if profile.kind == "error_rate":
        return _score_error(profile, old, new) or _score_other(old, new)
    return _score_other(old, new)


def _score_duration(profile: Profile, old: str, new: str) -> Explanation | None:
    old_values = _int_constants(old)
    new_values = _int_constants(new)
    best: tuple[float, str, Explanation] | None = None
    for name in new_values:
        if not name.endswith("_MS") or name not in old_values:
            continue
        old_value, old_line = old_values[name]
        new_value, new_line = new_values[name]
        if old_value == new_value:
            continue
        fit = _duration_fit(old_value, new_value, profile.baseline_ms or 0, profile.incident_ms or 0)
        detail = ""
        if (
            profile.kind == "timeout"
            and profile.timeout_ms is not None
            and old_value <= profile.timeout_ms < new_value
        ):
            detail = f"The new value is past the {profile.timeout_ms}ms timeout in the forensics log."
        candidate = Explanation(
            score=fit,
            line=new_line,
            line_text=_line(new, new_line),
            parent_line=old_line,
            parent_text=_line(old, old_line),
            label="duration",
            detail=detail,
        )
        key = (fit, name)
        if best is None or key > (best[0], best[1]):
            best = (fit, name, candidate)
    if best is None:
        return None
    return best[2]


def _duration_fit(old_value: int, new_value: int, baseline: float, incident: float) -> float:
    scale = max(float(incident), float(baseline), 1.0)
    new_fit = 1.0 - min(1.0, abs(float(new_value) - float(incident)) / scale)
    old_fit = 1.0 - min(1.0, abs(float(old_value) - float(baseline)) / scale)
    fit = 0.75 * new_fit + 0.25 * old_fit
    if new_fit < 0.9 and abs(new_value - old_value) < 100:
        fit *= 0.25
    return round(fit, 3)


def _score_error(profile: Profile, old: str, new: str) -> Explanation | None:
    signature = profile.signature or ""
    anchor = _match_template(new, signature) or _match_template(old, signature)
    if anchor is None:
        return None
    function = _function_at(new, anchor.line) or _function_at(old, anchor.line)
    if function is None:
        return None
    explained = _explain_constant(old, new, function.name, anchor, signature)
    if explained is not None:
        return explained
    flipped = _explain_predicate(old, new, signature)
    if flipped is not None:
        return flipped
    return _explain_nearby(old, new, function.name)


def _explain_constant(old: str, new: str, function: str, anchor: _Anchor, signature: str) -> Explanation | None:
    """A changed multiplier that newly fails the range check for the reported number."""
    observed = _as_int(anchor.value)
    if observed is None or observed <= 0:
        return None
    expr = _assigned_expr(new, function, anchor.name)
    if not isinstance(expr, ast.BinOp) or not isinstance(expr.op, ast.Mult):
        return None
    if not isinstance(expr.left, ast.Name) or not isinstance(expr.right, ast.Name):
        return None
    old_values = _int_constants(old)
    new_values = _int_constants(new)
    names = (expr.left.id, expr.right.id)
    changed = [
        name
        for name in names
        if name in old_values and name in new_values and old_values[name][0] != new_values[name][0]
    ]
    if len(changed) != 1:
        return None
    const_name = changed[0]
    other = names[1] if names[0] == const_name else names[0]
    if other in new_values:
        return None
    new_c = new_values[const_name][0]
    old_c = old_values[const_name][0]
    if new_c <= 0 or old_c <= 0 or observed % new_c != 0:
        return None
    unknown = observed // new_c
    if unknown <= 0:
        return None
    guard = _guard(new, anchor.line)
    old_anchor = _match_template(old, signature)
    old_guard = _guard(old, old_anchor.line) if old_anchor is not None else None
    if guard is None or old_guard is None or guard.text != old_guard.text:
        return None
    condition = guard.condition
    old_bad = _fails(condition, old_values, anchor.name, unknown * old_c)
    new_bad = _fails(condition, new_values, anchor.name, unknown * new_c)
    if old_bad is not False or new_bad is not True:
        return None
    detail = (
        f"Dividing {observed} by the new {const_name} of {new_c} leaves {unknown}. "
        "The range check accepts that amount at the old scale and rejects it at the new scale."
    )
    return Explanation(
        score=CONSTANT_SCORE,
        line=new_values[const_name][1],
        line_text=_line(new, new_values[const_name][1]),
        parent_line=old_values[const_name][1],
        parent_text=_line(old, old_values[const_name][1]),
        label="constant",
        detail=detail,
        extra=((guard.line, guard.text),),
    )


def _explain_predicate(old: str, new: str, signature: str) -> Explanation | None:
    anchor = _match_template(new, signature)
    if anchor is None:
        return None
    guard = _guard(new, anchor.line)
    if guard is None:
        return None
    for callee in _CALL.findall(guard.text):
        found = _inversion_in(old, new, callee)
        if found is None:
            continue
        new_line, old_line, new_text, old_text = found
        return Explanation(
            score=PREDICATE_SCORE,
            line=new_line,
            line_text=new_text,
            parent_line=old_line,
            parent_text=old_text,
            label="predicate",
            detail="",
        )
    old_anchor = _match_template(old, signature)
    old_guard = _guard(old, old_anchor.line) if old_anchor is not None else None
    if old_guard is not None and _is_inversion(old_guard.text, guard.text):
        return Explanation(
            score=PREDICATE_SCORE,
            line=guard.line,
            line_text=guard.text,
            parent_line=old_guard.line,
            parent_text=old_guard.text,
            label="predicate",
            detail="",
        )
    return None


def _explain_nearby(old: str, new: str, function: str) -> Explanation | None:
    old_values = _int_constants(old)
    new_values = _int_constants(new)
    used = _names_in_function(old, function) | _names_in_function(new, function)
    for name in sorted(used):
        if name not in old_values or name not in new_values:
            continue
        if old_values[name][0] == new_values[name][0]:
            continue
        new_line = new_values[name][1]
        old_line = old_values[name][1]
        return Explanation(
            score=NEARBY_SCORE,
            line=new_line,
            line_text=_line(new, new_line),
            parent_line=old_line,
            parent_text=_line(old, old_line),
            label="nearby",
            detail="",
        )
    if _function_code(old, function) == _function_code(new, function):
        return None
    added = _added_in_function(old, new, function)
    if not added:
        return None
    line, text = added[0]
    return Explanation(
        score=NEARBY_SCORE,
        line=line,
        line_text=text,
        parent_line=None,
        parent_text=None,
        label="nearby",
        detail="",
    )


def _score_other(old: str, new: str) -> Explanation | None:
    added = _added_lines(old, new)
    if not added:
        return None
    line, text = added[0]
    return Explanation(
        score=OTHER_SCORE,
        line=line,
        line_text=text,
        parent_line=None,
        parent_text=None,
        label="other",
        detail="",
    )


def _inversion_in(old: str, new: str, function: str):
    old_ifs = _if_lines(old, function)
    new_ifs = _if_lines(new, function)
    old_text = {text for _, text in old_ifs}
    new_text = {text for _, text in new_ifs}
    removed = [item for item in old_ifs if item[1] not in new_text]
    added = [item for item in new_ifs if item[1] not in old_text]
    for old_line, old_line_text in removed:
        for new_line, new_line_text in added:
            if _is_inversion(old_line_text, new_line_text):
                return new_line, old_line, new_line_text, old_line_text
    return None


def _is_inversion(old: str, new: str) -> bool:
    old_n = " ".join(old.split())
    new_n = " ".join(new.split())
    if old_n == new_n:
        return False
    return _fold_not(old_n) == _fold_not(new_n)


def _fold_not(text: str) -> str:
    return text.replace(" not in ", " in ").replace(" not ", " ")


def _match_template(source: str, signature: str) -> _Anchor | None:
    if not signature:
        return None
    best: tuple[int, _Anchor] | None = None
    for line_number, line in enumerate(source.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        for match in _FSTRING.finditer(line):
            body = match.group(2)
            holder = _PLACEHOLDER.fullmatch(body)
            if holder is None:
                continue
            pre, name, post = holder.group(1), holder.group(2), holder.group(3)
            if not pre and not post:
                continue
            start = signature.find(pre) if pre else 0
            if pre and start < 0:
                continue
            rest = signature[start + len(pre) :]
            if post:
                end = rest.find(post)
                if end <= 0:
                    continue
                value = rest[:end].strip()
            else:
                tokens = rest.strip().split()
                if not tokens:
                    continue
                value = tokens[0]
            if not value:
                continue
            weight = len(pre) + len(post)
            if best is None or weight > best[0]:
                best = (weight, _Anchor(line_number, name, value))
    if best is None:
        return None
    return best[1]


@dataclass(frozen=True)
class _Guard:
    line: int
    text: str

    @property
    def condition(self) -> str:
        return self.text[3:-1].strip()


def _guard(source: str, anchor: int) -> _Guard | None:
    """The `if` that controls the raise at `anchor`."""
    lines = source.splitlines()
    if anchor < 1 or anchor > len(lines):
        return None
    raw = lines[anchor - 1]
    anchor_indent = len(raw) - len(raw.lstrip(" "))
    for number in range(anchor - 1, 0, -1):
        line = lines[number - 1]
        stripped = line.strip()
        if not stripped:
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent < anchor_indent:
            if stripped.startswith("if ") and stripped.endswith(":"):
                return _Guard(number, stripped)
            return None
    return None


def _fails(condition: str, constants: dict[str, tuple[int, int]], placeholder: str, value: int) -> bool | None:
    bindings = {name: pair[0] for name, pair in constants.items()}
    bindings[placeholder] = value
    try:
        tree = ast.parse(condition, mode="eval")
        return bool(_eval(tree.body, bindings))
    except (SyntaxError, KeyError, TypeError, ValueError):
        return None


def _eval(node, bindings: dict):
    if isinstance(node, ast.BoolOp):
        values = [_eval(item, bindings) for item in node.values]
        if isinstance(node.op, ast.And):
            return all(values)
        if isinstance(node.op, ast.Or):
            return any(values)
        raise ValueError("unsupported boolean")
    if isinstance(node, ast.Compare):
        left = _eval(node.left, bindings)
        for op, comparator in zip(node.ops, node.comparators):
            right = _eval(comparator, bindings)
            if not _compare(op, left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.Name):
        if node.id not in bindings:
            raise KeyError(node.id)
        return bindings[node.id]
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_eval(node.operand, bindings)
    raise ValueError(f"unsupported expression {type(node).__name__}")


def _compare(op, left, right) -> bool:
    if isinstance(op, ast.Lt):
        return left < right
    if isinstance(op, ast.LtE):
        return left <= right
    if isinstance(op, ast.Gt):
        return left > right
    if isinstance(op, ast.GtE):
        return left >= right
    if isinstance(op, ast.Eq):
        return left == right
    if isinstance(op, ast.NotEq):
        return left != right
    raise ValueError("unsupported comparison")


def _assigned_expr(source: str, function: str, target: str):
    node = _function(source, function)
    if node is None:
        return None
    for stmt in node.body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
            name = stmt.targets[0]
            if isinstance(name, ast.Name) and name.id == target:
                return stmt.value
    return None


def _int_constants(source: str) -> dict[str, tuple[int, int]]:
    tree = ast.parse(source)
    found = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, int) and not isinstance(value.value, bool):
            found[target.id] = (value.value, node.lineno)
    return found


def _function(source: str, name: str) -> ast.FunctionDef | None:
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _function_at(source: str, line: int) -> ast.FunctionDef | None:
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.end_lineno is not None:
            if node.lineno <= line <= node.end_lineno:
                return node
    return None


def _function_code(source: str, name: str) -> tuple[str, ...] | None:
    node = _function(source, name)
    if node is None or node.end_lineno is None:
        return None
    lines = source.splitlines()[node.lineno - 1 : node.end_lineno]
    return tuple(line.strip() for line in lines if line.strip() and not line.strip().startswith("#"))


def _names_in_function(source: str, name: str) -> set[str]:
    node = _function(source, name)
    if node is None:
        return set()
    return {item.id for item in ast.walk(node) if isinstance(item, ast.Name)}


def _if_lines(source: str, name: str) -> list[tuple[int, str]]:
    node = _function(source, name)
    if node is None or node.end_lineno is None:
        return []
    lines = source.splitlines()
    found = []
    for number in range(node.lineno, node.end_lineno + 1):
        stripped = lines[number - 1].strip()
        if stripped.startswith("if "):
            found.append((number, stripped))
    return found


def _added_in_function(old: str, new: str, name: str) -> list[tuple[int, str]]:
    node = _function(new, name)
    if node is None or node.end_lineno is None:
        return []
    old_lines = set(_code_lines(old))
    lines = new.splitlines()
    added = []
    for number in range(node.lineno, node.end_lineno + 1):
        stripped = lines[number - 1].strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped not in old_lines:
            added.append((number, stripped))
    return added


def _added_lines(old: str, new: str) -> list[tuple[int, str]]:
    old_lines = set(_code_lines(old))
    added = []
    for number, line in enumerate(new.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped not in old_lines:
            added.append((number, stripped))
    return added


def _code_lines(source: str) -> list[str]:
    lines = []
    for line in source.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(stripped)
    return lines


def _line(source: str, number: int) -> str:
    return source.splitlines()[number - 1].strip()


def _as_int(value: str) -> int | None:
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    return None
