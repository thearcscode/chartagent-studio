"""Structural JSON diff over two canonical documents (ADR-0007 D3 erratum).

Hunks are added, removed and changed paths — not a text diff of
pretty-printed JSON. Identical documents yield zero hunks. A diff whose
only change is `x_chartagent.source_schema` (and the `spec_version` that
rides with introducing that key) is labelled as such, because that is
the ordinary shape of a chart's first honest save.
"""

from __future__ import annotations

from typing import Any


def _pointer_escape(segment: str) -> str:
    return segment.replace("~", "~0").replace("/", "~1")


def _child(path: str, segment: str) -> str:
    return f"{path}/{_pointer_escape(segment)}"


def without_source_schema(doc: dict[str, Any]) -> dict[str, Any]:
    """Drop `x_chartagent.source_schema` and a lone `spec_version` that
    exists only as the validation floor that key materialises — the same
    comparison the cache-honesty exception uses (ADR-0007 D8 erratum)."""
    stripped = {key: value for key, value in doc.items() if key != "x_chartagent"}
    xc = doc.get("x_chartagent")
    if isinstance(xc, dict):
        rest = {key: value for key, value in xc.items() if key != "source_schema"}
        if rest and set(rest) != {"spec_version"}:
            stripped["x_chartagent"] = rest
    return stripped


def diff_documents(
    left: dict[str, Any], right: dict[str, Any]
) -> tuple[list[dict[str, Any]], bool]:
    """Return `(hunks, source_schema_only)` over two canonical documents."""
    hunks: list[dict[str, Any]] = []
    _walk(left, right, "", hunks)
    if not hunks:
        return hunks, False
    source_schema_only = without_source_schema(left) == without_source_schema(right)
    return hunks, source_schema_only


def _hunk(
    op: str, path: str, *, from_value: Any = None, to_value: Any = None
) -> dict[str, Any]:
    return {
        "op": op,
        "path": path,
        "from_value": from_value,
        "to_value": to_value,
    }


def _walk(left: Any, right: Any, path: str, hunks: list[dict[str, Any]]) -> None:
    if left == right:
        return
    if isinstance(left, dict) and isinstance(right, dict):
        for key in sorted(set(left) | set(right)):
            child = _child(path, key)
            if key not in left:
                hunks.append(_hunk("added", child, to_value=right[key]))
            elif key not in right:
                hunks.append(_hunk("removed", child, from_value=left[key]))
            else:
                _walk(left[key], right[key], child, hunks)
        return
    if isinstance(left, list) and isinstance(right, list):
        for index in range(max(len(left), len(right))):
            child = _child(path, str(index))
            if index >= len(left):
                hunks.append(_hunk("added", child, to_value=right[index]))
            elif index >= len(right):
                hunks.append(_hunk("removed", child, from_value=left[index]))
            else:
                _walk(left[index], right[index], child, hunks)
        return
    hunks.append(
        _hunk("changed", path or "/", from_value=left, to_value=right)
    )
