"""Evaluation of Overture scoped rule lists."""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Iterable, Mapping
from typing import Any

from .defaults import MODE_FACTS

_ELEMENT_SEP = re.compile(r"([}\)\]])\s*\n\s*([{\(\[])")
_NUMPY_ARRAY = re.compile(r"array\((\[[^\[\]]*\])(?:\s*,\s*dtype=[^)]+)?\)")


def coerce_struct(value: Any) -> Any:
    """Best-effort recovery of nested Overture fields serialized as strings.

    GeoJSON round-trips (e.g. GDAL/pyogrio ``to_file``) flatten struct columns
    into strings — sometimes valid JSON, sometimes a NumPy object-array repr
    with single quotes, ``None``, and newline-separated elements. Returns the
    parsed container, or the input unchanged if it isn't parseable.
    """
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text or text[0] not in "[{":
        return value
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    normalized = _ELEMENT_SEP.sub(r"\1, \2", text)
    normalized = _NUMPY_ARRAY.sub(r"\1", normalized)
    try:
        return ast.literal_eval(normalized)
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        return value


def as_rule_list(value: Any) -> list[dict[str, Any]]:
    """Normalize Arrow, NumPy, pandas, JSON, or Python rule containers."""
    if value is None:
        return []
    value = coerce_struct(value)
    if hasattr(value, "as_py"):
        value = value.as_py()
    if hasattr(value, "tolist") and not isinstance(value, (str, bytes, Mapping)):
        value = value.tolist()
    if isinstance(value, Mapping):
        return [dict(value)]
    if isinstance(value, (list, tuple)):
        return [dict(item) for item in value if isinstance(item, Mapping)]
    return []


def geometric_match(rule: dict[str, Any], lr: float, tolerance: float = 1e-9) -> bool:
    if "between" in rule and rule["between"] is not None:
        between = rule["between"]
        if not isinstance(between, (list, tuple)) or len(between) != 2:
            return False
        return float(between[0]) - tolerance <= lr <= float(between[1]) + tolerance
    if "at" in rule and rule["at"] is not None:
        return abs(float(rule["at"]) - lr) <= tolerance
    return True


def _mode_match(scoped_modes: Any, mode: str) -> bool:
    if scoped_modes is None:
        return True
    if hasattr(scoped_modes, "as_py"):
        scoped_modes = scoped_modes.as_py()
    if hasattr(scoped_modes, "tolist") and not isinstance(scoped_modes, (str, bytes)):
        scoped_modes = scoped_modes.tolist()
    if not isinstance(scoped_modes, (list, tuple, set)):
        scoped_modes = [scoped_modes]
    facts = MODE_FACTS[mode]
    return any(str(value) in facts for value in scoped_modes)


CONDITIONAL_SCOPES = ("during", "using", "recognized", "vehicle")


def has_conditional_scope(when: Any) -> bool:
    """True if a 'when' clause carries scopes a static network can't resolve."""
    if not isinstance(when, Mapping):
        return False
    return any(when.get(key) is not None for key in CONDITIONAL_SCOPES)


def rule_matches(
    rule: dict[str, Any],
    *,
    lr: float,
    heading: str,
    mode: str,
    ignore_conditional: bool = True,
) -> bool:
    if not geometric_match(rule, lr):
        return False

    when = rule.get("when") or {}
    if not isinstance(when, Mapping):
        return False

    scoped_heading = when.get("heading")
    if scoped_heading is not None and str(scoped_heading) != heading:
        return False

    if not _mode_match(when.get("mode"), mode):
        return False

    # A static GMNS link cannot faithfully resolve these scopes without a
    # scenario timestamp, user status, purpose, or vehicle dimensions.
    # Overture data often materializes every 'when' key with an explicit
    # null, so only non-None values count as actual conditions.
    if ignore_conditional and has_conditional_scope(when):
        return False

    return True


def determining_rule(
    rules: Iterable[dict[str, Any]],
    *,
    lr: float,
    heading: str,
    mode: str,
) -> dict[str, Any] | None:
    """Return the last matching rule, per Overture's evaluation algorithm."""
    result = None
    for rule in rules:
        if rule_matches(rule, lr=lr, heading=heading, mode=mode):
            result = rule
    return result


def access_allowed(
    access_restrictions: Any,
    *,
    lr: float,
    heading: str,
    mode: str,
    default_allowed: bool,
) -> bool:
    rule = determining_rule(
        as_rule_list(access_restrictions),
        lr=lr,
        heading=heading,
        mode=mode,
    )
    if rule is None:
        return default_allowed
    access_type = str(rule.get("access_type", "")).lower()
    if access_type == "allowed":
        return True
    if access_type == "denied":
        return False
    return default_allowed


def speed_limit_mph(
    speed_limits: Any,
    *,
    lr: float,
    heading: str,
    mode: str,
) -> float | None:
    rule = determining_rule(as_rule_list(speed_limits), lr=lr, heading=heading, mode=mode)
    if rule is None:
        return None
    maximum = rule.get("max_speed")
    if not isinstance(maximum, dict):
        return None
    value = maximum.get("value")
    if value is None:
        return None
    unit = str(maximum.get("unit", "km/h")).lower()
    numeric = float(value)
    if unit in {"mph", "mi/h"}:
        return numeric
    if unit in {"km/h", "kph", "kmh"}:
        return numeric * 0.621371192237334
    return None
