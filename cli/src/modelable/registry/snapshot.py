from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from modelable.compiler.workspace import Workspace, WorkspaceSource
from modelable.parser.ir import (
    ArrayType,
    DomainDef,
    EnumProjectionDecl,
    EnumRefType,
    FieldType,
    MapType,
    MdlFile,
    ModelVersion,
    NamedType,
    ObjectType,
    ProjectionVersion,
    RefType,
    SemanticTypeDecl,
    UnionType,
    VersionExact,
    VersionMin,
    VersionPinned,
    VersionRange,
    VersionSpec,
)
from modelable.registry.resolver import resolve_enum_type_ref
from modelable.registry.signature import (
    compute_enum_projection_signature,
    compute_semantic_signature,
    compute_version_signature,
)

LOCK_FORMAT = "modelable.registry.lock.v1"
OBJECT_FORMAT = "modelable.registry.object.v1"


@dataclass(frozen=True)
class SnapshotPaths:
    root: Path

    @property
    def lock(self) -> Path:
        return self.root / "registry.lock"

    @property
    def objects(self) -> Path:
        return self.root / "registry" / "objects"


@dataclass(frozen=True)
class SnapshotResult:
    lock_path: Path
    object_count: int
    identities: tuple[str, ...]


@dataclass(frozen=True)
class SnapshotDiff:
    added: tuple[str, ...]
    removed: tuple[str, ...]
    changed: tuple[str, ...]

    @property
    def empty(self) -> bool:
        return not self.added and not self.removed and not self.changed

    def as_dict(self) -> dict[str, Any]:
        return {
            "added": list(self.added),
            "removed": list(self.removed),
            "changed": list(self.changed),
            "empty": self.empty,
        }


def resolve_workspace_snapshot(workspace: Workspace, output_dir: str | Path = ".modelable") -> SnapshotResult:
    """Write a deterministic, content-addressed snapshot of a validated workspace.

    The lock is the authoritative set of exact objects. Existing objects are retained
    because they are content-addressed and may still be referenced by another lock or
    historical checkout; ``prune_snapshot`` explicitly removes unreachable objects.
    """
    if workspace.errors:
        raise ValueError("Cannot snapshot a workspace with validation errors")

    paths = SnapshotPaths(Path(output_dir))
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.objects.mkdir(parents=True, exist_ok=True)

    source_paths = {id(domain): source.path for source in workspace.sources for domain in source.mdl.domains}
    entries: list[dict[str, Any]] = []

    for domain in workspace.mdl.domains:
        for name, model_versions in sorted(domain.models.items()):
            for model_version in sorted(model_versions, key=lambda item: item.version):
                entries.append(
                    _write_object(
                        paths,
                        domain.name,
                        name,
                        "model",
                        model_version,
                        source_paths.get(id(domain)),
                        workspace.mdl,
                    )
                )
        for name, projection_versions in sorted(domain.projections.items()):
            for projection_version in sorted(projection_versions, key=lambda item: item.version):
                entries.append(
                    _write_object(
                        paths,
                        domain.name,
                        name,
                        "projection",
                        projection_version,
                        source_paths.get(id(domain)),
                        workspace.mdl,
                    )
                )
        for decl in sorted(domain.semantic_types, key=lambda item: (item.name, item.version)):
            entries.append(_write_enum_object(paths, domain.name, decl.name, "semantic", decl))
        for projection in sorted(domain.enum_projections, key=lambda item: (item.name, item.version)):
            entries.append(_write_enum_object(paths, domain.name, projection.name, "enum_projection", projection))

    entries.sort(key=lambda item: (str(item["identity"]), int(item["version"]), str(item["kind"])))
    lock = {
        "format": LOCK_FORMAT,
        "objects": entries,
        "requirements": _build_requirements(entries),
    }
    _atomic_write_json(paths.lock, lock)
    identities = tuple(str(entry["identity"]) for entry in entries)
    return SnapshotResult(paths.lock, len(entries), identities)


def verify_snapshot(output_dir: str | Path = ".modelable") -> list[str]:
    """Return offline consistency errors for a registry snapshot."""
    paths = SnapshotPaths(Path(output_dir))
    if not paths.lock.exists():
        return [f"missing registry lock: {paths.lock}"]
    try:
        lock = json.loads(paths.lock.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot read registry lock {paths.lock}: {exc}"]
    if lock.get("format") != LOCK_FORMAT:
        return [f"unsupported registry lock format: {lock.get('format')!r}"]

    errors: list[str] = []
    objects = lock.get("objects")
    if not isinstance(objects, list):
        return ["registry lock objects must be an array"]
    seen: set[str] = set()
    for entry in objects:
        if not isinstance(entry, dict):
            errors.append("registry lock contains a non-object entry")
            continue
        content_hash = entry.get("content_hash")
        identity = entry.get("identity")
        if not isinstance(content_hash, str) or not isinstance(identity, str):
            errors.append("registry lock entry requires identity and content_hash")
            continue
        if content_hash in seen:
            continue
        seen.add(content_hash)
        object_path = paths.objects / f"{content_hash}.json"
        if not object_path.exists():
            errors.append(f"missing registry object {content_hash} for {identity}")
            continue
        try:
            payload = json.loads(object_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"cannot read registry object {content_hash}: {exc}")
            continue
        if payload.get("format") != OBJECT_FORMAT:
            errors.append(f"unsupported registry object format for {content_hash}")
            continue
        actual_hash = _content_hash({key: value for key, value in payload.items() if key != "content_hash"})
        if actual_hash != content_hash:
            errors.append(f"registry object hash mismatch for {content_hash}: found {actual_hash}")
        if payload.get("identity") != identity:
            errors.append(f"registry object identity mismatch for {content_hash}")
        if payload.get("signature") != entry.get("signature"):
            errors.append(f"registry object signature mismatch for {identity}")
        provenance = payload.get("provenance")
        if isinstance(provenance, dict):
            source = provenance.get("source")
            expected_source_hash = provenance.get("source_hash")
            if isinstance(source, str) and isinstance(expected_source_hash, str):
                source_path = Path(source)
                if source_path.exists() and source_path.is_file():
                    actual_source_hash = _file_hash(source_path)
                    if actual_source_hash != expected_source_hash:
                        errors.append(f"registry source drift for {identity}: found {actual_source_hash}")
    requirements = lock.get("requirements")
    if requirements is not None:
        if not isinstance(requirements, list):
            errors.append("registry lock requirements must be an array")
        else:
            entries_by_identity = {
                str(entry["identity"]): entry
                for entry in objects
                if isinstance(entry, dict) and isinstance(entry.get("identity"), str)
            }
            for requirement in requirements:
                if not isinstance(requirement, dict):
                    errors.append("registry lock contains a non-object requirement")
                    continue
                source_value = requirement.get("from")
                requested_value = requirement.get("requested")
                resolved_value = requirement.get("resolved")
                if (
                    not isinstance(source_value, str)
                    or not isinstance(requested_value, str)
                    or not isinstance(resolved_value, str)
                ):
                    errors.append("registry lock requirement requires from, requested, and resolved")
                    continue
                source = source_value
                resolved = resolved_value
                target = entries_by_identity.get(resolved)
                if target is None:
                    errors.append(f"registry lock requirement resolves to missing object {resolved}")
                    continue
                try:
                    expected = _resolve_dependency_entry(requested_value, objects, source_value)
                except ValueError as exc:
                    errors.append(f"invalid registry lock requirement {source} -> {resolved}: {exc}")
                else:
                    if expected.get("identity") != resolved:
                        errors.append(
                            f"registry lock requirement resolves {source} -> {resolved}, "
                            f"but {requested_value!r} selects {expected.get('identity')}"
                        )
                if target.get("signature") != requirement.get("signature"):
                    errors.append(f"registry lock requirement signature mismatch for {source} -> {resolved}")
                if target.get("content_hash") != requirement.get("object"):
                    errors.append(f"registry lock requirement object mismatch for {source} -> {resolved}")
            try:
                expected_requirements = _build_requirements(objects)
            except ValueError as exc:
                errors.append(f"cannot reconstruct registry lock requirements: {exc}")
            else:
                if requirements != expected_requirements:
                    errors.append("registry lock requirements do not match object dependency edges")
    return errors


def load_snapshot_workspace(output_dir: str | Path = ".modelable") -> Workspace:
    """Load a validated durable snapshot as a compiler workspace offline."""
    paths = SnapshotPaths(Path(output_dir))
    errors = verify_snapshot(paths.root)
    if errors:
        raise ValueError("Cannot load an invalid registry snapshot:\n" + "\n".join(errors))

    lock = json.loads(paths.lock.read_text(encoding="utf-8"))
    domains: dict[str, DomainDef] = {}
    source_paths: dict[str, str | None] = {}
    for entry in lock["objects"]:
        content_hash = str(entry["content_hash"])
        payload = json.loads((paths.objects / f"{content_hash}.json").read_text(encoding="utf-8"))
        identity = str(payload["identity"])
        qualified_name, _version = identity.rsplit("@", 1)
        domain_name, name = qualified_name.rsplit(".", 1)
        domain = domains.setdefault(domain_name, _snapshot_domain(domain_name))
        provenance = payload.get("provenance")
        if domain_name not in source_paths and isinstance(provenance, dict):
            source = provenance.get("source")
            source_paths[domain_name] = source if isinstance(source, str) else None
        contract = payload["contract"]
        kind = payload["kind"]
        if kind == "model":
            domain.models.setdefault(name, []).append(ModelVersion.model_validate(contract))
        elif kind == "projection":
            domain.projections.setdefault(name, []).append(ProjectionVersion.model_validate(contract))
        elif kind == "semantic":
            domain.semantic_types.append(SemanticTypeDecl.model_validate(contract))
        elif kind == "enum_projection":
            domain.enum_projections.append(EnumProjectionDecl.model_validate(contract))
        else:
            raise ValueError(f"unsupported registry object kind: {kind!r}")

    mdl = MdlFile(domains=list(domains.values()))
    sources = [
        WorkspaceSource(
            path=Path(source) if source is not None else None,
            uri=source or f"snapshot://{domain_name}",
            text="",
            mdl=MdlFile(domains=[domain]),
            errors=[],
            content_hash="",
        )
        for domain_name, domain in domains.items()
        for source in [source_paths.get(domain_name)]
    ]
    return Workspace(sources=sources, mdl=mdl, errors=[], warnings=[])


def _snapshot_domain(name: str) -> DomainDef:
    return DomainDef(name=name)


def diff_workspace_snapshot(workspace: Workspace, output_dir: str | Path = ".modelable") -> SnapshotDiff:
    """Compare a validated workspace with the current local snapshot offline."""
    with tempfile.TemporaryDirectory(prefix="modelable-registry-diff-") as temporary:
        candidate = resolve_workspace_snapshot(workspace, temporary)
        return diff_snapshot_paths(Path(output_dir), candidate.lock_path.parent)


def update_workspace_snapshot(
    workspace: Workspace, output_dir: str | Path = ".modelable"
) -> tuple[SnapshotResult, SnapshotDiff]:
    """Stage and atomically install a validated local snapshot candidate."""
    paths = SnapshotPaths(Path(output_dir))
    with tempfile.TemporaryDirectory(prefix="modelable-registry-update-") as temporary:
        candidate_dir = Path(temporary)
        candidate = resolve_workspace_snapshot(workspace, candidate_dir)
        candidate_errors = verify_snapshot(candidate_dir)
        if candidate_errors:
            raise ValueError("Candidate snapshot is invalid:\n" + "\n".join(candidate_errors))
        snapshot_diff = diff_snapshot_paths(paths.root, candidate_dir)

        paths.root.mkdir(parents=True, exist_ok=True)
        paths.objects.mkdir(parents=True, exist_ok=True)
        candidate_objects = candidate_dir / "registry" / "objects"
        for object_path in candidate_objects.glob("*.json"):
            destination = paths.objects / object_path.name
            if not destination.exists():
                shutil.copyfile(object_path, destination)
        temporary_lock = paths.root / f".registry.lock.tmp-{os.getpid()}"
        shutil.copyfile(candidate.lock_path, temporary_lock)
        os.replace(temporary_lock, paths.lock)
        return SnapshotResult(paths.lock, candidate.object_count, candidate.identities), snapshot_diff


def diff_snapshot_paths(current_dir: Path, candidate_dir: Path) -> SnapshotDiff:
    current_entries = _load_lock_entries(SnapshotPaths(current_dir).lock)
    candidate_entries = _load_lock_entries(SnapshotPaths(candidate_dir).lock)
    current_by_key = {_entry_key(entry): entry for entry in current_entries}
    candidate_by_key = {_entry_key(entry): entry for entry in candidate_entries}
    added = sorted(set(candidate_by_key) - set(current_by_key))
    removed = sorted(set(current_by_key) - set(candidate_by_key))
    changed = sorted(
        key
        for key in set(current_by_key) & set(candidate_by_key)
        if current_by_key[key].get("content_hash") != candidate_by_key[key].get("content_hash")
        or current_by_key[key].get("signature") != candidate_by_key[key].get("signature")
    )
    return SnapshotDiff(
        added=tuple(_display_key(key) for key in added),
        removed=tuple(_display_key(key) for key in removed),
        changed=tuple(_display_key(key) for key in changed),
    )


def snapshot_status(output_dir: str | Path = ".modelable") -> dict[str, Any]:
    paths = SnapshotPaths(Path(output_dir))
    errors = verify_snapshot(paths.root)
    object_count = 0
    if paths.lock.exists():
        try:
            lock = json.loads(paths.lock.read_text(encoding="utf-8"))
            object_count = len(lock.get("objects", []))
        except OSError, json.JSONDecodeError:
            pass
    return {
        "format": LOCK_FORMAT,
        "lock": str(paths.lock),
        "objects": object_count,
        "valid": not errors,
        "errors": errors,
    }


def prune_snapshot(output_dir: str | Path = ".modelable") -> int:
    """Remove object files not reachable from the current lock."""
    paths = SnapshotPaths(Path(output_dir))
    errors = verify_snapshot(paths.root)
    if errors:
        raise ValueError("Cannot prune an invalid snapshot:\n" + "\n".join(errors))
    lock = json.loads(paths.lock.read_text(encoding="utf-8"))
    reachable = {str(entry["content_hash"]) for entry in lock["objects"]}
    removed = 0
    if paths.objects.exists():
        for object_path in paths.objects.glob("*.json"):
            if object_path.stem not in reachable:
                object_path.unlink()
                removed += 1
    return removed


def _write_enum_object(
    paths: SnapshotPaths,
    domain_name: str,
    name: str,
    kind: str,
    declaration: SemanticTypeDecl | EnumProjectionDecl,
) -> dict[str, Any]:
    """Write a semantic-type or enum-projection snapshot object.

    Enum contracts participate in the same content-addressed, immutable object
    model as models and projections (evolution plan E4): same logical version
    with different canonical content lands as a ``changed`` diff entry under
    the existing immutability rule.
    """
    identity = f"{domain_name}.{name}@{declaration.version}"
    if isinstance(declaration, SemanticTypeDecl):
        signature = compute_semantic_signature(domain_name, declaration)
        dependencies = sorted(_enum_ref_dependencies(declaration.underlying, domain_name))
    else:
        signature = compute_enum_projection_signature(domain_name, declaration)
        dependencies = [f"{_qualified(name=declaration.source_name, domain=domain_name)}@{declaration.source_version}"]
    payload: dict[str, Any] = {
        "format": OBJECT_FORMAT,
        "identity": identity,
        "kind": kind,
        "version": declaration.version,
        "signature": signature,
        "dependencies": dependencies,
        "provenance": {"source": None},
        "contract": declaration.model_dump(mode="json"),
    }
    content_hash = _content_hash(payload)
    payload["content_hash"] = content_hash
    _atomic_write_json(paths.objects / f"{content_hash}.json", payload)
    return {
        "identity": identity,
        "kind": kind,
        "version": declaration.version,
        "signature": payload["signature"],
        "content_hash": content_hash,
        "dependencies": dependencies,
    }


def _qualified(name: str, domain: str) -> str:
    return name if "." in name else f"{domain}.{name}"


def _write_object(
    paths: SnapshotPaths,
    domain_name: str,
    name: str,
    kind: str,
    version: ModelVersion | ProjectionVersion,
    source_path: Path | None,
    mdl: MdlFile,
) -> dict[str, Any]:
    identity = f"{domain_name}.{name}@{version.version}"
    # Evolution plan D5: `provenance` (which `evolves` operation last touched
    # each field) is operation-syntax-adjacent diagnostic metadata, not
    # canonical contract content -- an evolved version and an equivalent
    # hand-written full-form version must produce the same stored object and
    # the same content_hash, the same way they already produce the same
    # `signature` (compute_version_signature never looks at it either).
    # ProjectionVersion has no such field; excluding it is a no-op there.
    contract = version.model_dump(mode="json", exclude={"provenance"})
    dependencies = _dependencies(version, mdl, domain_name)
    payload: dict[str, Any] = {
        "format": OBJECT_FORMAT,
        "identity": identity,
        "kind": kind,
        "version": version.version,
        "signature": compute_version_signature(domain_name, name, version),
        "dependencies": dependencies,
        "provenance": {
            "source": str(source_path) if source_path is not None else None,
            "source_hash": _optional_file_hash(source_path),
        },
        "contract": contract,
    }
    content_hash = _content_hash(payload)
    payload["content_hash"] = content_hash
    _atomic_write_json(paths.objects / f"{content_hash}.json", payload)
    return {
        "identity": identity,
        "kind": kind,
        "version": version.version,
        "signature": payload["signature"],
        "content_hash": content_hash,
        "dependencies": dependencies,
    }


def _load_lock_entries(lock_path: Path) -> list[dict[str, Any]]:
    if not lock_path.exists():
        return []
    try:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read registry lock {lock_path}: {exc}") from exc
    if payload.get("format") != LOCK_FORMAT or not isinstance(payload.get("objects"), list):
        raise ValueError(f"invalid registry lock {lock_path}")
    return [entry for entry in payload["objects"] if isinstance(entry, dict)]


def _entry_key(entry: dict[str, Any]) -> tuple[str, str]:
    return (str(entry.get("kind", "unknown")), str(entry.get("identity", "unknown")))


def _display_key(key: tuple[str, str]) -> str:
    return f"{key[1]} ({key[0]})"


def _dependencies(version: ModelVersion | ProjectionVersion, mdl: MdlFile, domain_name: str) -> list[str]:
    dependencies: set[str] = set()
    if isinstance(version, ProjectionVersion):
        dependencies.add(_format_dependency(version.source.model, version.source.version))
        dependencies.update(_format_dependency(join.model, join.version) for join in version.joins)
        for field in version.fields:
            _collect_field_dependencies(field.mapping, dependencies)
    else:
        for model_field in version.fields:
            _collect_type_dependencies(model_field.type, dependencies, mdl, domain_name)
    return sorted(dependencies)


def _collect_field_dependencies(mapping: Any, dependencies: set[str]) -> None:
    if getattr(mapping, "kind", None) == "direct":
        return
    expression = getattr(mapping, "expression", "")
    if expression:
        return


def _collect_type_dependencies(
    field_type: FieldType,
    dependencies: set[str],
    mdl: MdlFile | None = None,
    domain_name: str | None = None,
) -> None:
    if isinstance(field_type, RefType):
        dependencies.add(_format_dependency(field_type.target, field_type.version))
    elif isinstance(field_type, EnumRefType):
        # Exact-versioned enum references are dependency edges to the
        # declaring semantic type (evolution plan E4).
        if mdl is not None and domain_name is not None:
            try:
                resolved_domain, declaration = resolve_enum_type_ref(
                    mdl, domain_name, field_type.name, exact_version=field_type.version
                )
            except LookupError:
                pass
            else:
                if isinstance(declaration, EnumProjectionDecl):
                    dependencies.add(f"{resolved_domain}.{declaration.name}@{declaration.version}")
                else:
                    dependencies.add(f"{field_type.name}@{field_type.version}")
        else:
            dependencies.add(f"{field_type.name}@{field_type.version}")
    elif isinstance(field_type, NamedType) and mdl is not None and domain_name is not None:
        try:
            resolved_domain, declaration = resolve_enum_type_ref(mdl, domain_name, field_type.name)
        except LookupError:
            pass
        else:
            if isinstance(declaration, EnumProjectionDecl):
                dependencies.add(f"{resolved_domain}.{declaration.name}@{declaration.version}")
    elif isinstance(field_type, ArrayType):
        _collect_type_dependencies(field_type.item, dependencies, mdl, domain_name)
    elif isinstance(field_type, MapType):
        _collect_type_dependencies(field_type.key, dependencies, mdl, domain_name)
        _collect_type_dependencies(field_type.value, dependencies, mdl, domain_name)
    elif isinstance(field_type, ObjectType):
        for field in field_type.fields:
            _collect_type_dependencies(field.type, dependencies, mdl, domain_name)
    elif isinstance(field_type, UnionType):
        for variant in field_type.variants:
            _collect_type_dependencies(variant.type, dependencies, mdl, domain_name)


def _enum_ref_dependencies(field_type: FieldType, domain_name: str) -> set[str]:
    """Enum-reference edges from a semantic declaration's underlying type."""
    dependencies: set[str] = set()
    if isinstance(field_type, EnumRefType):
        dependencies.add(f"{_qualified(field_type.name, domain_name)}@{field_type.version}")
    elif isinstance(field_type, NamedType):
        dependencies.add(_qualified(field_type.name, domain_name))
    return dependencies


def _format_dependency(target: str, version: VersionSpec | None) -> str:
    if version is None:
        return f"{target}@latest"
    if isinstance(version, VersionExact):
        return f"{target}@{version.version}"
    if isinstance(version, VersionRange):
        return f"{target}@>={version.min_inclusive}<{version.max_exclusive}"
    if isinstance(version, VersionMin):
        return f"{target}@>={version.min_inclusive}"
    if isinstance(version, VersionPinned):
        return f"{target}@{version.version}#{version.content_hash}"
    return f"{target}@?"


def _build_requirements(entries: list[dict[str, Any]]) -> list[dict[str, str]]:
    requirements: list[dict[str, str]] = []
    for entry in entries:
        source = str(entry["identity"])
        for requested in entry.get("dependencies", []):
            if not isinstance(requested, str):
                raise ValueError(f"registry dependency for {source} must be a string")
            resolved = _resolve_dependency_entry(requested, entries, source)
            requirements.append(
                {
                    "from": source,
                    "requested": requested,
                    "resolved": str(resolved["identity"]),
                    "signature": str(resolved["signature"]),
                    "object": str(resolved["content_hash"]),
                }
            )
    return sorted(requirements, key=lambda item: (item["from"], item["requested"], item["resolved"]))


def _resolve_dependency_entry(
    requested: str, entries: list[dict[str, Any]], source: str | None = None
) -> dict[str, Any]:
    if "@" in requested:
        target, selector = requested.rsplit("@", 1)
    else:
        target, selector = requested, "latest"
    source_domain = source.split(".", 1)[0] if source is not None and "." in source else None
    target_names = {target}
    if source_domain is not None and "." not in target:
        target_names.add(f"{source_domain}.{target}")
    candidates = [
        entry
        for entry in entries
        if isinstance(entry.get("identity"), str)
        and any(str(entry["identity"]).startswith(f"{name}@") for name in target_names)
        and _identity_version(str(entry["identity"])) is not None
    ]
    expected_hash: str | None = None
    if "#" in selector:
        selector, expected_hash = selector.split("#", 1)
    if selector == "latest":
        matching = candidates
    elif selector.isdigit():
        matching = [entry for entry in candidates if _entry_version(entry) == int(selector)]
    else:
        range_match = re.fullmatch(r">=(\d+)<(\d+)", selector)
        minimum_match = re.fullmatch(r">=(\d+)", selector)
        if range_match:
            minimum, maximum = (int(value) for value in range_match.groups())
            matching = [entry for entry in candidates if minimum <= _entry_version(entry) < maximum]
        elif minimum_match:
            minimum = int(minimum_match.group(1))
            matching = [entry for entry in candidates if _entry_version(entry) >= minimum]
        else:
            raise ValueError(f"unsupported registry dependency selector {requested!r}")
    if not matching:
        raise ValueError(f"unresolved registry dependency {requested!r}")
    selected = max(matching, key=lambda entry: (_entry_version(entry), str(entry["kind"])))
    if expected_hash is not None and selected.get("content_hash") != expected_hash:
        raise ValueError(f"pinned registry dependency hash mismatch for {requested!r}")
    return selected


def _identity_version(identity: str) -> int | None:
    version = identity.rsplit("@", 1)[-1]
    return int(version) if version.isdigit() else None


def _entry_version(entry: dict[str, Any]) -> int:
    identity = str(entry["identity"])
    version = _identity_version(identity)
    if version is None:
        raise ValueError(f"registry object identity has no numeric version: {identity!r}")
    return version


def _content_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _optional_file_hash(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    return _file_hash(path)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
