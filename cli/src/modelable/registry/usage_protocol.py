"""Standalone JSON protocol helpers for ``modelable.usage/v0`` manifests."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import cast

USAGE_SCHEMA = "modelable.usage/v0"
USAGE_MANIFEST_NAME = "modelable-usage-manifest.json"
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
    artifacts = document.get("artifacts")
    if artifacts is not None:
        if not isinstance(artifacts, list):
            raise UsageProtocolError("artifacts must be a JSON array")
        artifact_keys: set[tuple[str, str]] = set()
        for index, artifact in enumerate(artifacts):
            _validate_artifact(artifact, f"artifacts[{index}]", artifact_keys)
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
    surfaces = document.get("surfaces")
    if surfaces is not None:
        if not isinstance(surfaces, list):
            raise UsageProtocolError("surfaces must be a JSON array")
        surface_ids: set[str] = set()
        for index, surface in enumerate(surfaces):
            _validate_surface(surface, f"surfaces[{index}]", surface_ids)
    _require_exact_keys(
        document,
        {"$schema", "kind", "application", "references", "application_id", "packages", "artifacts", "surfaces"}
        & set(document),
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
                **({"package_id": reference["package_id"]} if "package_id" in reference else {}),
            }
        )
    normalized_artifacts = []
    for value in cast(list[object], validated.get("artifacts", [])):
        artifact = cast(dict[str, object], value)
        normalized_artifact = {
            "path": artifact["path"],
            "sha256": artifact["sha256"],
            "target": artifact["target"],
        }
        if "ref" in artifact:
            normalized_artifact["ref"] = artifact["ref"]
        normalized_artifacts.append(normalized_artifact)
    normalized_surfaces = []
    for value in cast(list[object], validated.get("surfaces", [])):
        surface = cast(dict[str, object], value)
        normalized_surface = {key: surface[key] for key in ("id", "kind", "ref") if key in surface}
        for key in ("name", "method", "path", "adapter", "table", "operations"):
            if key in surface:
                normalized_surface[key] = sorted(cast(list[str], surface[key])) if key == "operations" else surface[key]
        normalized_surfaces.append(normalized_surface)
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
    if "artifacts" in validated:
        normalized["artifacts"] = sorted(
            normalized_artifacts, key=lambda item: (cast(str, item["target"]), cast(str, item["path"]))
        )
    if "surfaces" in validated:
        normalized["surfaces"] = sorted(normalized_surfaces, key=lambda item: cast(str, item["id"]))
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


def write_usage_manifest(path: Path, document: object) -> None:
    """Write one validated usage manifest using its canonical JSON form."""
    path.write_text(serialize_usage_manifest(document), encoding="utf-8")


def _validate_reference(value: object, name: str, seen: set[str]) -> None:
    if not isinstance(value, dict):
        raise UsageProtocolError(f"{name} must be a JSON object")
    reference = cast(dict[str, object], value)
    _require_exact_keys(reference, {"ref", "signature", "fields", "package_id"} & set(reference), name)
    ref = _require_string(reference, "ref")
    _require_string_if_present(reference, "package_id")
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


def _validate_artifact(value: object, name: str, seen: set[tuple[str, str]]) -> None:
    if not isinstance(value, dict):
        raise UsageProtocolError(f"{name} must be a JSON object")
    artifact = cast(dict[str, object], value)
    _require_exact_keys(artifact, {"path", "ref", "sha256", "target"} & set(artifact), name)
    path = _require_string(artifact, "path")
    target = _require_string(artifact, "target")
    key = (target, path)
    if key in seen:
        raise UsageProtocolError(f"duplicate artifact {target!r}/{path!r}")
    seen.add(key)
    _require_string(artifact, "sha256")
    if _SHA256.fullmatch(cast(str, artifact["sha256"])) is None:
        raise UsageProtocolError(f"{name}.sha256 must be a lowercase SHA-256 hex string")
    if "ref" in artifact:
        ref = _require_string(artifact, "ref")
        if _DECLARATION_REF.fullmatch(ref) is None:
            raise UsageProtocolError(f"{name}.ref must be a canonical declaration reference")


def _validate_surface(value: object, name: str, seen: set[str]) -> None:
    if not isinstance(value, dict):
        raise UsageProtocolError(f"{name} must be a JSON object")
    surface = cast(dict[str, object], value)
    kind = _require_string(surface, "kind")
    surface_id = _require_string(surface, "id")
    if surface_id in seen:
        raise UsageProtocolError(f"duplicate surface {surface_id!r}")
    seen.add(surface_id)
    ref = _require_string(surface, "ref")
    if _DECLARATION_REF.fullmatch(ref) is None:
        raise UsageProtocolError(f"{name}.ref must be a canonical declaration reference")
    if kind == "api_operation":
        _require_exact_keys(surface, {"id", "kind", "ref", "name", "method", "path"}, name)
        _require_string(surface, "name")
        method = _require_string(surface, "method")
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            raise UsageProtocolError(f"{name}.method must be a supported HTTP method")
        _require_string(surface, "path")
    elif kind == "event":
        _require_exact_keys(surface, {"id", "kind", "ref", "operations"} & set(surface), name)
        if "operations" in surface:
            operations = surface["operations"]
            if (
                not isinstance(operations, list)
                or not operations
                or not all(isinstance(operation, str) and operation for operation in operations)
            ):
                raise UsageProtocolError(f"{name}.operations must be a non-empty string array")
    elif kind == "storage":
        _require_exact_keys(surface, {"id", "kind", "ref", "adapter", "table"} & set(surface), name)
        _require_string(surface, "adapter")
        _require_string_if_present(surface, "table")
    else:
        raise UsageProtocolError(f"{name}.kind must be api_operation, event, or storage")


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
