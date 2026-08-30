"""Standalone JSON protocol helpers for ``modelable.consequence/v0`` graphs."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

CONSEQUENCE_SCHEMA = "modelable.consequence/v0"
type ConsequenceGraph = dict[str, object]


class ConsequenceProtocolError(ValueError):
    """Raised when a consequence graph does not satisfy the v0 boundary."""


def validate_consequence_graph(document: object) -> ConsequenceGraph:
    """Validate and return a JSON object conforming to the consequence v0 envelope."""
    if not isinstance(document, dict):
        raise ConsequenceProtocolError("Consequence graph must be a JSON object")
    _require_string(document, "$schema", expected=CONSEQUENCE_SCHEMA)
    _require_string(document, "kind", expected="consequence_graph")
    nodes = document.get("nodes")
    if not isinstance(nodes, list):
        raise ConsequenceProtocolError("nodes must be a JSON array")
    node_ids: set[str] = set()
    for index, node in enumerate(nodes):
        _validate_node(node, f"nodes[{index}]", node_ids)

    edges = document.get("edges")
    if not isinstance(edges, list):
        raise ConsequenceProtocolError("edges must be a JSON array")
    edge_keys: set[tuple[str, str, str]] = set()
    for index, edge in enumerate(edges):
        _validate_edge(edge, f"edges[{index}]", node_ids, edge_keys)

    _require_exact_keys(document, {"$schema", "kind", "nodes", "edges"}, "consequence graph")
    return cast(ConsequenceGraph, document)


def serialize_consequence_graph(document: object) -> str:
    """Return the deterministic canonical JSON representation of a graph."""
    validated = validate_consequence_graph(document)
    nodes = cast(list[object], validated["nodes"])
    edges = cast(list[object], validated["edges"])
    normalized = {
        "$schema": validated["$schema"],
        "kind": validated["kind"],
        "nodes": sorted(cast(list[dict[str, Any]], nodes), key=lambda node: cast(str, node["id"])),
        "edges": sorted(
            cast(list[dict[str, Any]], edges),
            key=lambda edge: (cast(str, edge["kind"]), cast(str, edge["source"]), cast(str, edge["target"])),
        ),
    }
    try:
        return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    except (TypeError, ValueError) as error:
        raise ConsequenceProtocolError(f"Consequence graph is not JSON-compatible: {error}") from error


def load_consequence_graph(path: Path) -> ConsequenceGraph:
    """Load and validate a graph without importing compiler internals."""
    try:
        document = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite,
        )
    except ConsequenceProtocolError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ConsequenceProtocolError(f"Could not read consequence graph {path}: {error}") from error
    return validate_consequence_graph(document)


def _validate_node(value: object, name: str, seen: set[str]) -> None:
    if not isinstance(value, dict):
        raise ConsequenceProtocolError(f"{name} must be a JSON object")
    node = cast(dict[str, object], value)
    node_id = _require_string(node, "id")
    if node_id in seen:
        raise ConsequenceProtocolError(f"duplicate node {node_id!r}")
    seen.add(node_id)
    kind = _require_string(node, "kind")
    if kind == "reference":
        _require_string(node, "label")
        expected = {"id", "kind", "label"}
    elif kind == "change":
        _require_string(node, "change_kind")
        _require_string(node, "field")
        expected = {"id", "kind", "change_kind", "field"}
    elif kind == "action":
        for key in ("label", "action", "subject", "status"):
            _require_string(node, key)
        expected = {"id", "kind", "label", "action", "subject", "status"}
    else:
        raise ConsequenceProtocolError(f"{name}.kind is unsupported")
    _require_exact_keys(node, expected, name)


def _validate_edge(value: object, name: str, node_ids: set[str], seen: set[tuple[str, str, str]]) -> None:
    if not isinstance(value, dict):
        raise ConsequenceProtocolError(f"{name} must be a JSON object")
    edge = cast(dict[str, object], value)
    _require_exact_keys(edge, {"kind", "source", "target"}, name)
    kind = _require_string(edge, "kind")
    if kind not in {"causes", "requires"}:
        raise ConsequenceProtocolError(f"{name}.kind is unsupported")
    source = _require_string(edge, "source")
    target = _require_string(edge, "target")
    if source not in node_ids:
        raise ConsequenceProtocolError(f"{name} has unknown source {source!r}")
    if target not in node_ids:
        raise ConsequenceProtocolError(f"{name} has unknown target {target!r}")
    key = (kind, source, target)
    if key in seen:
        raise ConsequenceProtocolError(f"duplicate edge {key!r}")
    seen.add(key)


def _require_string(mapping: dict[str, object], name: str, *, expected: str | None = None) -> str:
    value = mapping.get(name)
    if not isinstance(value, str) or not value:
        raise ConsequenceProtocolError(f"{name} must be a non-empty string")
    if expected is not None and value != expected:
        raise ConsequenceProtocolError(f"{name} must be {expected!r}")
    return value


def _require_exact_keys(mapping: Mapping[str, object], expected: set[str], name: str) -> None:
    actual = set(mapping)
    unknown = sorted(actual - expected)
    missing = sorted(expected - actual)
    if unknown:
        raise ConsequenceProtocolError(f"{name} has unknown key(s): {', '.join(unknown)}")
    if missing:
        raise ConsequenceProtocolError(f"{name} is missing key(s): {', '.join(missing)}")


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ConsequenceProtocolError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _reject_non_finite(value: str) -> object:
    raise ConsequenceProtocolError(f"non-finite JSON number {value!r} is not allowed")
