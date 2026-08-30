"""Standalone JSON protocol helpers for ``modelable.usage/v0`` manifests."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import cast

USAGE_SCHEMA = "modelable.usage/v0"
type UsageManifest = dict[str, object]

_DECLARATION_REF = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*@[1-9][0-9]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class UsageProtocolError(ValueError):
    """Raised when a usage manifest does not satisfy the v0 boundary."""


def validate_usage_manifest(document: object) -> UsageManifest:
    """Validate and return a JSON object conforming to the usage v0 envelope."""
    if not isinstance(document, dict):
        raise UsageProtocolError("Usage manifest must be a JSON object")
    _require_string(document, "$schema", expected=USAGE_SCHEMA)
    _require_string(document, "kind", expected="usage_manifest")
    _require_string(document, "application")
    references = document.get("references")
    if not isinstance(references, list):
        raise UsageProtocolError("references must be a JSON array")

    seen: set[str] = set()
    for index, value in enumerate(references):
        _validate_reference(value, f"references[{index}]", seen)
    _require_string_if_present(document, "application_id")
    packages = document.get("packages")
    if packages is not None:
        if not isinstance(packages, list):
            raise UsageProtocolError("packages must be a JSON array")
        for index, package in enumerate(packages):
            if not isinstance(package, dict):
                raise UsageProtocolError(f"packages[{index}] must be a JSON object")
            _require_exact_keys(package, {"id", "name"}, f"packages[{index}]")
            _require_string(package, "id")
            _require_string(package, "name")
    _require_exact_keys(
        document,
        {"$schema", "kind", "application", "references", "application_id", "packages"} & set(document),
        "usage manifest",
    )
    return cast(UsageManifest, document)


def serialize_usage_manifest(document: object) -> str:
    """Return the deterministic canonical JSON representation of a manifest."""
    validated = validate_usage_manifest(document)
    references = cast(list[object], validated["references"])
    normalized_references = []
    for value in references:
        reference = cast(dict[str, object], value)
        normalized_references.append(
            {
                "ref": reference["ref"],
                "signature": reference["signature"],
                "fields": sorted(cast(list[str], reference["fields"])),
            }
        )
    normalized = {
        "$schema": validated["$schema"],
        "kind": validated["kind"],
        "application": validated["application"],
        "references": sorted(normalized_references, key=lambda item: cast(str, item["ref"])),
    }
    if "application_id" in validated:
        normalized["application_id"] = validated["application_id"]
    if "packages" in validated:
        normalized["packages"] = sorted(cast(list[dict[str, str]], validated["packages"]), key=lambda item: item["id"])
    try:
        return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    except (TypeError, ValueError) as error:
        raise UsageProtocolError(f"Usage manifest is not JSON-compatible: {error}") from error


def load_usage_manifest(path: Path) -> UsageManifest:
    """Load and validate a manifest without importing parser or semantic IR classes."""
    try:
        document = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite,
        )
    except UsageProtocolError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise UsageProtocolError(f"Could not read usage manifest {path}: {error}") from error
    return validate_usage_manifest(document)


def _validate_reference(value: object, name: str, seen: set[str]) -> None:
    if not isinstance(value, dict):
        raise UsageProtocolError(f"{name} must be a JSON object")
    reference = cast(dict[str, object], value)
    _require_exact_keys(reference, {"ref", "signature", "fields"}, name)
    ref = _require_string(reference, "ref")
    if _DECLARATION_REF.fullmatch(ref) is None:
        raise UsageProtocolError(f"{name}.ref must be a canonical declaration reference")
    if ref in seen:
        raise UsageProtocolError(f"duplicate reference {ref!r}")
    seen.add(ref)
    signature = _require_string(reference, "signature")
    if _SHA256.fullmatch(signature) is None:
        raise UsageProtocolError(f"{name}.signature must be a lowercase SHA-256 hex string")
    fields = reference["fields"]
    if not isinstance(fields, list):
        raise UsageProtocolError(f"{name}.fields must be a JSON array")
    field_names: set[str] = set()
    for index, field in enumerate(fields):
        if not isinstance(field, str) or not field:
            raise UsageProtocolError(f"{name}.fields[{index}] must be a non-empty string")
        if not field.startswith(ref + "#") or len(field) == len(ref) + 1:
            raise UsageProtocolError(f"{name}.fields[{index}] must belong to reference {ref!r}")
        if field in field_names:
            raise UsageProtocolError(f"{name}.fields contains duplicate field {field!r}")
        field_names.add(field)


def _require_string(mapping: dict[str, object], name: str, *, expected: str | None = None) -> str:
    value = mapping.get(name)
    if not isinstance(value, str) or not value:
        raise UsageProtocolError(f"{name} must be a non-empty string")
    if expected is not None and value != expected:
        raise UsageProtocolError(f"{name} must be {expected!r}")
    return value


def _require_string_if_present(mapping: dict[str, object], name: str) -> None:
    if name in mapping:
        _require_string(mapping, name)


def _require_exact_keys(mapping: Mapping[str, object], expected: set[str], name: str) -> None:
    actual = set(mapping)
    unknown = sorted(actual - expected)
    missing = sorted(expected - actual)
    if unknown:
        raise UsageProtocolError(f"{name} has unknown key(s): {', '.join(unknown)}")
    if missing:
        raise UsageProtocolError(f"{name} is missing key(s): {', '.join(missing)}")


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise UsageProtocolError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _reject_non_finite(value: str) -> object:
    raise UsageProtocolError(f"non-finite JSON number {value!r} is not allowed")
