"""Versioned, read-only query protocol envelopes."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

QUERY_SCHEMA = "modelable.query/v1"
QUERY_KINDS = frozenset(
    {
        "declaration",
        "referencesTo",
        "lineage",
        "consumersOf",
        "dependencies",
        "dependents",
        "changes",
        "consequences",
        "facets",
        "lifecycle",
    }
)
_REQUEST_KEYS = {"$schema", "kind", "query", "id", "from", "to", "limit", "cursor"}
_RESPONSE_KEYS = {"$schema", "kind", "query", "data", "next_cursor"}


class QueryProtocolError(ValueError):
    """Raised when a query/v1 envelope is invalid."""


def validate_query_request(document: object) -> dict[str, Any]:
    """Validate and normalize one read-only query request."""
    value = _require_object(document, "query request")
    _require_exact_keys(value, _REQUEST_KEYS, "query request")
    if value.get("$schema") != QUERY_SCHEMA:
        raise QueryProtocolError(f"query request $schema must be {QUERY_SCHEMA!r}")
    if value.get("kind") != "query":
        raise QueryProtocolError("query request kind must be 'query'")
    query = value.get("query")
    if query not in QUERY_KINDS:
        raise QueryProtocolError(f"unsupported query family: {query!r}")
    _require_request_value(value, query)
    limit = value.get("limit", 100)
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 1000:
        raise QueryProtocolError("query request limit must be an integer from 1 to 1000")
    cursor = value.get("cursor")
    if cursor is not None and (not isinstance(cursor, str) or not cursor):
        raise QueryProtocolError("query request cursor must be a non-empty string")
    normalized = dict(value)
    normalized["limit"] = limit
    return normalized


def validate_query_response(document: object) -> dict[str, Any]:
    """Validate one query/v1 response envelope."""
    value = _require_object(document, "query response")
    unknown = sorted(set(value) - _RESPONSE_KEYS)
    if unknown:
        # Response members are forward-compatible within v1; old clients must
        # ignore optional metadata added by newer servers.
        pass
    if value.get("$schema") != QUERY_SCHEMA:
        raise QueryProtocolError(f"query response $schema must be {QUERY_SCHEMA!r}")
    if value.get("kind") != "query_result":
        raise QueryProtocolError("query response kind must be 'query_result'")
    if value.get("query") not in QUERY_KINDS:
        raise QueryProtocolError(f"unsupported query family: {value.get('query')!r}")
    if "data" not in value:
        raise QueryProtocolError("query response requires data")
    next_cursor = value.get("next_cursor")
    if next_cursor is not None and (not isinstance(next_cursor, str) or not next_cursor):
        raise QueryProtocolError("query response next_cursor must be a non-empty string")
    return value


def serialize_query_response(document: object) -> str:
    """Validate and serialize a query/v1 response deterministically."""
    return json.dumps(validate_query_response(document), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _require_request_value(value: Mapping[str, Any], query: object) -> None:
    if query in {
        "declaration",
        "referencesTo",
        "lineage",
        "consumersOf",
        "dependencies",
        "dependents",
        "facets",
        "lifecycle",
    }:
        field = "id"
    elif query in {"changes", "consequences"}:
        for field in ("from", "to"):
            if not isinstance(value.get(field), str) or not value[field]:
                raise QueryProtocolError(f"query family {query!r} requires non-empty {field!r}")
        return
    else:
        raise QueryProtocolError(f"unsupported query family: {query!r}")
    if not isinstance(value.get(field), str) or not value[field]:
        raise QueryProtocolError(f"query family {query!r} requires a non-empty {field!r}")


def _require_object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise QueryProtocolError(f"{label} must be an object")
    return value


def _require_exact_keys(value: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise QueryProtocolError(f"unknown key in {label}: {unknown[0]!r}")
