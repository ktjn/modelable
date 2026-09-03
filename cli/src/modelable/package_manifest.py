"""External semantic package manifest parsing and normalization."""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from modelable.identity import parse_declaration_id

PACKAGE_MANIFEST_NAME = "modelable.package.toml"

_PACKAGE_NAME = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
_EXPORT_WILDCARD = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*\.\*$")
_SEMVER_IDENTIFIER = r"(?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)"
_SEMVER = (
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    rf"(?:-(?:{_SEMVER_IDENTIFIER})(?:\.(?:{_SEMVER_IDENTIFIER}))*)?"
    rf"(?:\+(?:{_SEMVER_IDENTIFIER})(?:\.(?:{_SEMVER_IDENTIFIER}))*)?"
)
_CONSTRAINT_VERSION = (
    r"(?:0|[1-9][0-9]*)"
    rf"(?:\.(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*))?)?"
    rf"(?:-(?:{_SEMVER_IDENTIFIER})(?:\.(?:{_SEMVER_IDENTIFIER}))*)?"
)
_VERSION = re.compile(rf"^{_SEMVER}$")
_CONSTRAINT_PART = re.compile(rf"^(?P<operator>\^|~|>=|>|<=|<)?(?P<version>{_CONSTRAINT_VERSION})$")


class PackageManifestError(ValueError):
    """Raised when a semantic package manifest is missing or invalid."""


@dataclass(frozen=True)
class PackageIdentity:
    name: str
    version: str


@dataclass(frozen=True)
class PackageDependency:
    name: str
    constraint: str


@dataclass(frozen=True)
class PackageManifest:
    identity: PackageIdentity
    description: str | None
    exports: tuple[str, ...]
    dependencies: tuple[PackageDependency, ...]


@dataclass(frozen=True)
class PackageResolution:
    manifests: tuple[PackageManifest, ...]
    dependencies: dict[str, tuple[str, ...]]


def load_package_manifest(path: Path) -> PackageManifest:
    """Load and validate one external semantic package manifest."""
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PackageManifestError(f"manifest not found: {path}") from exc
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise PackageManifestError(f"cannot parse package manifest {path}: {exc}") from exc
    return _parse_manifest(raw)


def parse_package_manifest(document: Mapping[str, Any]) -> PackageManifest:
    """Parse and validate an already decoded normalized package manifest."""
    return _parse_manifest(document)


def normalize_package_manifest(manifest: PackageManifest) -> dict[str, Any]:
    """Return the deterministic, transport-independent manifest shape."""
    package: dict[str, Any] = {
        "name": manifest.identity.name,
        "version": manifest.identity.version,
    }
    if manifest.description is not None:
        package["description"] = manifest.description
    return {
        "package": package,
        "exports": {"declarations": sorted(manifest.exports)},
        "dependencies": {
            dependency.name: dependency.constraint
            for dependency in sorted(manifest.dependencies, key=lambda item: item.name)
        },
    }


def serialize_package_manifest(manifest: PackageManifest) -> str:
    """Serialize a manifest as deterministic inspection JSON."""
    return json.dumps(normalize_package_manifest(manifest), indent=2, sort_keys=True) + "\n"


def package_content_hash(manifest: PackageManifest) -> str:
    """Hash canonical manifest content without source-path or formatting data."""
    canonical = json.dumps(normalize_package_manifest(manifest), separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def resolve_package_manifests(manifests: Sequence[PackageManifest]) -> PackageResolution:
    """Resolve explicit local package candidates into a deterministic closure."""
    candidates: dict[str, list[PackageManifest]] = {}
    for manifest in manifests:
        candidates.setdefault(manifest.identity.name, []).append(manifest)
    for name, values in candidates.items():
        values.sort(key=lambda item: _version_key(item.identity.version), reverse=True)
        identities = [item.identity.version for item in values]
        if len(identities) != len(set(identities)):
            raise PackageManifestError(f"duplicate package identity: {name}@{identities[0]}")

    selected: dict[str, PackageManifest] = {}
    dependency_map: dict[str, tuple[str, ...]] = {}
    visiting: set[str] = set()

    def visit(manifest: PackageManifest) -> None:
        identity = _package_identity(manifest)
        existing = selected.get(identity)
        if existing is not None:
            return
        if identity in visiting:
            raise PackageManifestError(f"package dependency cycle at {identity}")
        visiting.add(identity)
        resolved: list[str] = []
        for dependency in manifest.dependencies:
            options = candidates.get(dependency.name, [])
            match = next(
                (
                    candidate
                    for candidate in options
                    if package_version_satisfies(candidate.identity.version, dependency.constraint)
                ),
                None,
            )
            if match is None:
                raise PackageManifestError(
                    f"no local package satisfies {dependency.name!r} {dependency.constraint!r} required by {identity}"
                )
            visit(match)
            resolved.append(_package_identity(match))
        visiting.remove(identity)
        selected[identity] = manifest
        dependency_map[identity] = tuple(sorted(resolved))

    for values in candidates.values():
        manifest = values[0]
        visit(manifest)
    return PackageResolution(
        manifests=tuple(
            sorted(selected.values(), key=lambda item: (item.identity.name, _version_key(item.identity.version)))
        ),
        dependencies=dependency_map,
    )


def package_version_satisfies(version: str, constraint: str) -> bool:
    """Return whether a strict package version satisfies a validated constraint."""
    candidate = _version_key(version)
    if constraint == "*":
        return True
    for raw_part in constraint.split(","):
        match = _CONSTRAINT_PART.fullmatch(raw_part)
        if match is None:
            return False
        operator = match.group("operator") or "="
        version_text = match.group("version")
        bound_parts = tuple(int(part) for part in version_text.split("-", 1)[0].split("."))
        bound: tuple[int, int, int] = (
            bound_parts[0],
            bound_parts[1] if len(bound_parts) > 1 else 0,
            bound_parts[2] if len(bound_parts) > 2 else 0,
        )
        if operator == "=":
            if len(bound_parts) == 1:
                if candidate[0] != bound[0]:
                    return False
            elif len(bound_parts) == 2:
                if candidate[:2] != bound[:2]:
                    return False
            elif candidate[:3] != bound:
                return False
        elif operator in {">=", ">", "<", "<="}:
            if not _compare_bound(candidate, bound, operator):
                return False
        elif operator in {"^", "~"}:
            if not _compare_bound(candidate, bound, ">="):
                return False
            upper = (bound[0] + 1, 0, 0) if operator == "^" else (bound[0], bound[1] + 1, 0)
            if not _compare_bound(candidate, upper, "<"):
                return False
    return True


def _package_identity(manifest: PackageManifest) -> str:
    return f"{manifest.identity.name}@{manifest.identity.version}"


def _version_key(version: str) -> tuple[int, int, int, tuple[tuple[int, object], ...]]:
    core, _, prerelease = version.partition("-")
    numbers = [int(part) for part in core.split(".")]
    major, minor, patch = numbers
    identifiers: list[tuple[int, object]] = []
    for identifier in prerelease.split(".") if prerelease else []:
        identifiers.append((0, int(identifier)) if identifier.isdigit() else (1, identifier))
    return major, minor, patch, tuple(identifiers)


def _compare_bound(
    candidate: tuple[int, int, int, tuple[tuple[int, object], ...]], bound: tuple[int, int, int], operator: str
) -> bool:
    candidate_core = candidate[:3]
    if operator == ">=":
        return candidate_core >= bound
    if operator == ">":
        return candidate_core > bound
    if operator == "<":
        return candidate_core < bound
    return candidate_core <= bound


def _parse_manifest(raw: Mapping[str, Any]) -> PackageManifest:
    _require_mapping(raw, "manifest")
    _require_keys(raw, {"package", "exports", "dependencies"}, "manifest")

    package = _require_mapping(raw.get("package"), "package")
    _require_keys(package, {"name", "version", "description"}, "package")

    name = _require_string(package.get("name"), "package.name")
    if _PACKAGE_NAME.fullmatch(name) is None:
        raise PackageManifestError(f"invalid package name: {name!r}")
    version = _require_string(package.get("version"), "package.version")
    if _VERSION.fullmatch(version) is None:
        raise PackageManifestError(f"invalid package version: {version!r}")

    description = package.get("description")
    if description is not None and not isinstance(description, str):
        raise PackageManifestError("package.description must be a string")

    exports_table = _require_mapping(raw.get("exports", {}), "exports")
    _require_keys(exports_table, {"declarations"}, "exports")
    exports = exports_table.get("declarations", [])
    if not isinstance(exports, list) or not all(isinstance(export, str) for export in exports):
        raise PackageManifestError("package.exports must be an array of strings")
    if len(set(exports)) != len(exports):
        raise PackageManifestError("package.exports contains duplicate declarations")
    for export in exports:
        if _EXPORT_WILDCARD.fullmatch(export):
            continue
        try:
            parse_declaration_id(export)
        except ValueError as exc:
            raise PackageManifestError(f"invalid declaration identity in package.exports: {export!r}") from exc

    dependencies_raw = _require_mapping(raw.get("dependencies", {}), "dependencies")
    dependencies: list[PackageDependency] = []
    for dependency_name, constraint in dependencies_raw.items():
        if not isinstance(dependency_name, str) or _PACKAGE_NAME.fullmatch(dependency_name) is None:
            raise PackageManifestError(f"invalid dependency name: {dependency_name!r}")
        if not isinstance(constraint, str):
            raise PackageManifestError(f"invalid dependency constraint for {dependency_name!r}: {constraint!r}")
        _validate_constraint(dependency_name, constraint)
        dependencies.append(PackageDependency(dependency_name, constraint))

    return PackageManifest(
        identity=PackageIdentity(name, version),
        description=description,
        exports=tuple(sorted(exports)),
        dependencies=tuple(sorted(dependencies, key=lambda item: item.name)),
    )


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PackageManifestError(f"{label} must be a table")
    return value


def _require_keys(value: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise PackageManifestError(f"unknown key in {label}: {unknown[0]!r}")


def _require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise PackageManifestError(f"{label} must be a non-empty string")
    return value


def _validate_constraint(name: str, constraint: str) -> None:
    if constraint == "*":
        return
    lower: tuple[tuple[int, int, int], bool] | None = None
    upper: tuple[tuple[int, int, int], bool] | None = None
    for raw_part in constraint.split(","):
        match = _CONSTRAINT_PART.fullmatch(raw_part)
        if match is None:
            raise PackageManifestError(f"invalid dependency constraint for {name!r}: {constraint!r}")
        operator = match.group("operator") or "="
        version_parts = [int(part) for part in match.group("version").split("-", 1)[0].split(".")]
        padded = (
            version_parts[0],
            version_parts[1] if len(version_parts) > 1 else 0,
            version_parts[2] if len(version_parts) > 2 else 0,
        )
        if operator in {"^", "~"}:
            continue
        if operator in {">=", ">", "="}:
            candidate = (padded, operator != ">")
            if lower is None or candidate[0] > lower[0] or (candidate[0] == lower[0] and not candidate[1] and lower[1]):
                lower = candidate
        if operator in {"<", "<=", "="}:
            candidate = (padded, operator != "<")
            if upper is None or candidate[0] < upper[0] or (candidate[0] == upper[0] and not candidate[1] and upper[1]):
                upper = candidate
    if (
        lower is not None
        and upper is not None
        and (lower[0] > upper[0] or (lower[0] == upper[0] and not (lower[1] and upper[1])))
    ):
        raise PackageManifestError(f"contradictory dependency constraint for {name!r}: {constraint!r}")
