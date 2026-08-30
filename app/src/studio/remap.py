"""Apply a dropped-column remap across a frame (#11).

The rewrite is a spec edit: every place the old name appears in the
transform, the encodings, the sort keys and `semantic_types` becomes the
new name. `source_schema` is left alone — the save path copies a fresh
baseline from the bind that succeeds. `spec_version` is never written.
"""

from __future__ import annotations

import copy
import json
from typing import Any

from chartagent import canonical_json


class RemapRefusedError(Exception):
    """The mapping is incomplete or tries to repair a retype."""


def validate_mapping(
    drifted: list[dict[str, Any]], mapping: dict[str, str]
) -> None:
    """Every dropped field must be mapped; a retype cannot be remapped."""
    dropped = [field["name"] for field in drifted if field.get("kind") == "dropped"]
    retyped = [field["name"] for field in drifted if field.get("kind") == "retyped"]
    if retyped and not dropped:
        raise RemapRefusedError(
            "a retype cannot be remapped; rewrite the transform as raw_sql, "
            "or fix the data"
        )
    mapped_retype = [name for name in retyped if mapping.get(name)]
    if mapped_retype:
        raise RemapRefusedError(
            "a retype cannot be remapped; rewrite the transform as raw_sql, "
            "or fix the data"
        )
    missing = [name for name in dropped if not mapping.get(name)]
    if missing:
        raise RemapRefusedError("every dropped field must be mapped")
    extra = set(mapping) - set(dropped)
    if extra:
        raise RemapRefusedError("mapping contains fields that are not dropped")


def apply_mapping(
    doc: dict[str, Any], mapping: dict[str, str]
) -> dict[str, Any]:
    """Rewrite `mapping`'s old names onto a canonical copy of `doc`."""
    if not mapping:
        empty: dict[str, Any] = json.loads(canonical_json(doc))
        return empty
    out: dict[str, Any] = copy.deepcopy(doc)
    chart_spec = out.get("chart_spec")
    if isinstance(chart_spec, dict):
        encodings = chart_spec.get("encodings")
        if isinstance(encodings, dict):
            for channel in encodings.values():
                if isinstance(channel, dict):
                    field = channel.get("field")
                    if isinstance(field, str) and field in mapping:
                        channel["field"] = mapping[field]
    types = out.get("semantic_types")
    if isinstance(types, dict):
        out["semantic_types"] = {
            mapping.get(key, key) if isinstance(key, str) else key: value
            for key, value in types.items()
        }
    xc = out.get("x_chartagent")
    if isinstance(xc, dict) and "transform" in xc:
        xc["transform"] = _rewrite_transform(xc["transform"], mapping)
    result: dict[str, Any] = json.loads(canonical_json(out))
    return result


def _rewrite_transform(node: Any, mapping: dict[str, str]) -> Any:
    if isinstance(node, list):
        return [_rewrite_transform(item, mapping) for item in node]
    if not isinstance(node, dict):
        return node
    rewritten: dict[str, Any] = {}
    for key, value in node.items():
        if key == "name" and node.get("kind") == "col" and value in mapping:
            rewritten[key] = mapping[value]
        elif key == "field" and isinstance(value, str) and value in mapping:
            rewritten[key] = mapping[value]
        elif key == "group_by" and isinstance(value, list):
            rewritten[key] = [
                mapping[item]
                if isinstance(item, str) and item in mapping
                else _rewrite_transform(item, mapping)
                for item in value
            ]
        else:
            rewritten[key] = _rewrite_transform(value, mapping)
    return rewritten
