"""Standalone JSON protocol helpers for ``modelable.plan/v0`` documents."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

PLAN_SCHEMA = "modelable.plan/v0"
type PlanDocument = dict[str, object]


class PlanProtocolError(ValueError):
    """Raised when a plan does not satisfy the modelable.plan/v0 boundary."""


def validate_plan(document: object) -> PlanDocument:
    """Validate and return a JSON object that conforms to the v0 envelope."""
    if not isinstance(document, dict):
        raise PlanProtocolError("Plan document must be a JSON object")

    _require_string(document, "$schema", expected=PLAN_SCHEMA)
    _require_string(document, "domain")
    _require_string(document, "projection")
    _require_integer(document, "version")
    _require_boolean(document, "auto_generated")
    _require_boolean(document, "requires_revalidation")
    revalidation_reasons = _require_string_list(document, "revalidation_reasons")
    _validate_relation(_require_mapping(document, "source"), "source", on_required=False)
    joins = _require_list(document, "joins")
    for index, join in enumerate(joins):
        _validate_relation(join, f"joins[{index}]", on_required=True)
    _require_string_list(document, "group_by")

    fields = _require_list(document, "fields")
    field_names: set[str] = set()
    for index, field in enumerate(fields):
        field_name = _validate_field(field, f"fields[{index}]")
        if field_name in field_names:
            raise PlanProtocolError(f"fields contains duplicate name {field_name!r}")
        field_names.add(field_name)

    metadata = _require_mapping(document, "planner_metadata")
    _require_string(metadata, "modelable_schema")
    _require_exact_keys(metadata, {"modelable_schema"}, "planner_metadata")
    _require_exact_keys(
        document,
        {
            "$schema",
            "domain",
            "projection",
            "version",
            "auto_generated",
            "requires_revalidation",
            "revalidation_reasons",
            "governance_findings",
            "source",
            "joins",
            "group_by",
            "fields",
            "planner_metadata",
        },
        "plan",
    )
    findings = _require_list(document, "governance_findings")
    for index, finding in enumerate(findings):
        _validate_governance_finding(finding, f"governance_findings[{index}]")
    if document["requires_revalidation"] != bool(revalidation_reasons):
        raise PlanProtocolError("requires_revalidation must match revalidation_reasons")
    return cast(PlanDocument, document)


def serialize_plan(document: object) -> str:
    """Return the deterministic canonical JSON representation of a plan."""
    validated = validate_plan(document)
    try:
        return (
            json.dumps(
                validated,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        )
    except (TypeError, ValueError) as error:
        raise PlanProtocolError(f"Plan document is not JSON-compatible: {error}") from error


def load_plan(path: Path) -> PlanDocument:
    """Load and validate a plan without importing parser or semantic IR classes."""
    try:
        document = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite,
        )
    except PlanProtocolError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise PlanProtocolError(f"Could not read plan {path}: {error}") from error
    return validate_plan(document)


def _require_mapping(mapping: dict[str, object], name: str) -> dict[str, object]:
    if not isinstance(mapping, dict):
        raise PlanProtocolError(f"{name} must be a JSON object")
    candidate = mapping.get(name)
    if not isinstance(candidate, dict):
        raise PlanProtocolError(f"{name} must be a JSON object")
    return cast(dict[str, object], candidate)


def _require_list(mapping: dict[str, object], name: str) -> list[object]:
    value = mapping.get(name)
    if not isinstance(value, list):
        raise PlanProtocolError(f"{name} must be a JSON array")
    return value


def _require_string(mapping: dict[str, object], name: str, *, expected: str | None = None) -> str:
    value = mapping.get(name)
    if not isinstance(value, str) or not value:
        raise PlanProtocolError(f"{name} must be a non-empty string")
    if expected is not None and value != expected:
        raise PlanProtocolError(f"{name} must be {expected!r}")
    return value


def _require_integer(mapping: dict[str, object], name: str) -> int:
    value = mapping.get(name)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise PlanProtocolError(f"{name} must be a positive integer")
    return value


def _require_boolean(mapping: dict[str, object], name: str) -> bool:
    value = mapping.get(name)
    if not isinstance(value, bool):
        raise PlanProtocolError(f"{name} must be a boolean")
    return value


def _require_string_list(mapping: dict[str, object], name: str) -> list[object]:
    values = _require_list(mapping, name)
    if any(not isinstance(value, str) for value in values):
        raise PlanProtocolError(f"{name} must contain only strings")
    return values


def _validate_relation(value: object, name: str, *, on_required: bool) -> None:
    if not isinstance(value, dict):
        raise PlanProtocolError(f"{name} must be a JSON object")
    relation = cast(dict[str, object], value)
    _require_string(relation, "model")
    resolved_version = relation.get("resolved_version")
    if resolved_version is not None and (
        not isinstance(resolved_version, int) or isinstance(resolved_version, bool) or resolved_version < 1
    ):
        raise PlanProtocolError(f"{name}.resolved_version must be an integer or null")
    _require_string(relation, "alias")
    change_kind = relation.get("change_kind")
    if change_kind is not None and not isinstance(change_kind, str):
        raise PlanProtocolError(f"{name}.change_kind must be a string or null")
    if on_required:
        _require_string(relation, "on")
    resolved = relation.get("resolved")
    if resolved is not None:
        _validate_resolved_declaration(resolved, f"{name}.resolved")
    _require_exact_keys(
        relation,
        {"model", "resolved_version", "alias", "change_kind", "resolved", "on"}
        if on_required
        else {"model", "resolved_version", "alias", "change_kind", "resolved"},
        name,
    )
    if resolved is not None:
        declaration = cast(dict[str, object], resolved)
        expected_ref = f"{declaration['domain']}.{declaration['name']}"
        if relation.get("model") != expected_ref:
            raise PlanProtocolError(f"{name}.resolved identity does not match model")
        if relation.get("resolved_version") != declaration["version"]:
            raise PlanProtocolError(f"{name}.resolved version does not match resolved_version")


def _validate_resolved_declaration(value: object, name: str) -> None:
    if not isinstance(value, dict):
        raise PlanProtocolError(f"{name} must be a JSON object or null")
    declaration = cast(dict[str, object], value)
    _require_string(declaration, "domain")
    _require_string(declaration, "name")
    _require_integer(declaration, "version")
    kind = _require_string(declaration, "kind")
    model_kind = declaration.get("model_kind")
    if model_kind is not None and not isinstance(model_kind, str):
        raise PlanProtocolError(f"{name}.model_kind must be a string or null")
    if kind not in {"model", "projection"}:
        raise PlanProtocolError(f"{name}.kind must be 'model' or 'projection'")
    if kind == "model" and model_kind not in {"entity", "aggregate", "event", "value"}:
        raise PlanProtocolError(f"{name}.model_kind must identify a model kind")
    if kind == "projection" and model_kind is not None:
        raise PlanProtocolError(f"{name}.model_kind must be null for projections")
    fields = _require_list(declaration, "fields")
    field_names: set[str] = set()
    for index, field in enumerate(fields):
        _validate_declaration_field(field, f"{name}.fields[{index}]")
        field_name = cast(dict[str, object], field)["name"]
        if field_name in field_names:
            raise PlanProtocolError(f"{name}.fields contains duplicate name {field_name!r}")
        field_names.add(cast(str, field_name))
    _require_exact_keys(declaration, {"domain", "name", "version", "kind", "model_kind", "fields"}, name)


def _validate_declaration_field(value: object, name: str) -> None:
    if not isinstance(value, dict):
        raise PlanProtocolError(f"{name} must be a JSON object")
    field = cast(dict[str, object], value)
    _require_string(field, "name")
    field_type = field.get("type")
    if field_type is not None and not isinstance(field_type, dict):
        raise PlanProtocolError(f"{name}.type must be a JSON object or null")
    optional = field.get("optional")
    if optional is not None and not isinstance(optional, bool):
        raise PlanProtocolError(f"{name}.optional must be a boolean or null")
    nullable = field.get("nullable")
    if nullable is not None and not isinstance(nullable, bool):
        raise PlanProtocolError(f"{name}.nullable must be a boolean or null")
    _require_exact_keys(field, {"name", "type", "optional", "nullable"}, name)


def _validate_field(value: object, name: str) -> str:
    if not isinstance(value, dict):
        raise PlanProtocolError(f"{name} must be a JSON object")
    field = cast(dict[str, object], value)
    _require_string(field, "name")
    kind = _require_string(field, "kind")
    field_type = field.get("type")
    if field_type is not None and not isinstance(field_type, dict):
        raise PlanProtocolError(f"{name}.type must be a JSON object or null")
    optional = field.get("optional")
    if optional is not None and not isinstance(optional, bool):
        raise PlanProtocolError(f"{name}.optional must be a boolean or null")
    _require_string_list(field, "lineage")
    if kind == "direct":
        _require_string(field, "source_alias")
        _require_string(field, "source_field")
        _require_exact_keys(
            field, {"name", "kind", "source_alias", "source_field", "type", "optional", "lineage"}, name
        )
    elif kind == "computed":
        _require_string(field, "expression")
        _require_exact_keys(field, {"name", "kind", "expression", "type", "optional", "lineage"}, name)
    else:
        raise PlanProtocolError(f"{name}.kind must be 'direct' or 'computed'")
    return cast(str, field["name"])


def _validate_governance_finding(value: object, name: str) -> None:
    if not isinstance(value, dict):
        raise PlanProtocolError(f"{name} must be a JSON object")
    finding = cast(dict[str, object], value)
    for key in ("code", "subject", "message"):
        _require_string(finding, key)
    _require_exact_keys(finding, {"code", "subject", "message"}, name)


def _require_exact_keys(mapping: dict[str, object], expected: set[str], name: str) -> None:
    actual = set(mapping)
    missing = expected - actual
    extra = actual - expected
    if missing or extra:
        details = []
        if missing:
            details.append(f"missing {sorted(missing)!r}")
        if extra:
            details.append(f"unknown {sorted(extra)!r}")
        raise PlanProtocolError(f"{name} has invalid keys ({'; '.join(details)})")


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise PlanProtocolError(f"Duplicate JSON key {key!r}")
        result[key] = value
    return result


def _reject_non_finite(value: str) -> object:
    raise PlanProtocolError(f"Non-finite JSON number {value!r} is not allowed")
