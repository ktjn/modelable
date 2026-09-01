from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from modelable.compat.checker import (
    CompatibilityReport,
    ProjectionCompatibilityReport,
    check_model_version_compatibility,
    check_projection_version_compatibility,
)
from modelable.compat.enums import compare_enum_projections
from modelable.compat.targets import (
    compare_data_backfill,
    compare_governance_review,
    compare_model_storage_migration,
    compare_projection_rebuild,
    compare_projection_wire_compatibility,
    compare_semantic_compatibility,
)
from modelable.compiler.render import render_mdl
from modelable.compiler.workspace import (
    Workspace,
    WorkspaceDocumentSource,
    WorkspaceSource,
    load_workspace_from_sources,
)
from modelable.consequence import (
    ACTION_BREAKING,
    ACTION_CONSUMER_UPDATE,
    ACTION_EVENT_REPLAY,
    ACTION_RECOMPILE,
    ACTION_REGENERATE,
    ACTION_STORAGE_MIGRATION,
    Consequence,
    build_consequence_graph,
    build_enum_consequences,
    build_enum_projection_consequences,
    build_model_consequences,
    build_projection_consequences,
    build_target_consequences,
    build_usage_consumer_consequences,
)
from modelable.extensions import ExtensionDescriptorError, ExtensionPin, parse_extension_pin
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
from modelable.registry.enum_numbers import EnumNumberAllocation
from modelable.registry.enum_numbers import read_lock_file as read_enum_numbers_lock_file
from modelable.registry.ids import read_lock_file as read_registry_ids_lock_file
from modelable.registry.resolver import resolve_enum_type_ref
from modelable.registry.signature import (
    compute_enum_projection_signature,
    compute_semantic_signature,
    compute_version_signature,
)
from modelable.registry.usage import USAGE_SCHEMA, build_usage_manifest
from modelable.registry.usage_protocol import UsageProtocolError, serialize_usage_manifest, validate_usage_manifest

LOCK_FORMAT = "modelable.lock/v1"
LEGACY_LOCK_FORMAT = "modelable.registry.lock.v1"
SUPPORTED_LOCK_FORMATS = frozenset({LOCK_FORMAT, LEGACY_LOCK_FORMAT})
OBJECT_FORMAT = "modelable.registry.object.v1"


def _extension_pin_sort_key(pin: ExtensionPin) -> tuple[str, str, str]:
    return pin.id, pin.version, pin.implementation_hash


def _canonical_extension_pins(extension_pins: tuple[ExtensionPin, ...]) -> list[dict[str, Any]]:
    parsed_pins = [parse_extension_pin(pin.as_dict()) for pin in extension_pins]
    if len({(pin.id, pin.version) for pin in parsed_pins}) != len(parsed_pins):
        raise ExtensionDescriptorError("extension pins contain duplicate identities")
    return [pin.as_dict() for pin in sorted(parsed_pins, key=_extension_pin_sort_key)]


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
    dependencies: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    usage: dict[str, Any] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return (
            not self.added
            and not self.removed
            and not self.changed
            and not any(self.dependencies.values())
            and not any(isinstance(category, dict) and any(category.values()) for category in self.usage.values())
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "added": list(self.added),
            "removed": list(self.removed),
            "changed": list(self.changed),
            "dependencies": self.dependencies,
            "usage": self.usage,
            "empty": self.empty,
        }


class RegistryPolicyEvaluator(Protocol):
    """Evaluate a staged snapshot's semantic, usage, and consequence facts."""

    def evaluate(self, snapshot_diff: SnapshotDiff) -> PolicyEvaluation:
        """Return policy findings and action names that should block installation."""
        ...


@dataclass(frozen=True)
class PolicyFinding:
    """A policy diagnostic tied to a consequence and its causal path."""

    action: str
    status: str
    reason: str | None = None
    causal_path: tuple[str, ...] = ()
    severity: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "status": self.status,
            "severity": self.severity,
            "reason": self.reason,
            "causal_path": list(self.causal_path),
        }


@dataclass(frozen=True)
class PolicyEvaluation:
    """Structured policy output for a staged snapshot."""

    blocked_actions: tuple[str, ...] = ()
    findings: tuple[PolicyFinding, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "blocked_actions": list(self.blocked_actions),
            "findings": [finding.as_dict() for finding in self.findings],
        }


class RegistryPolicyError(ValueError):
    """A staged registry update was blocked after its candidate was retained."""

    def __init__(
        self,
        snapshot_diff: SnapshotDiff,
        evaluation: PolicyEvaluation,
        retained_candidate: Path,
        object_count: int,
    ) -> None:
        self.snapshot_diff = snapshot_diff
        self.evaluation = evaluation
        self.retained_candidate = retained_candidate
        self.object_count = object_count
        blocked = ", ".join(evaluation.blocked_actions)
        super().__init__(
            "registry update blocked by registry policy for action(s): "
            + blocked
            + f"; candidate retained at {retained_candidate}"
        )


@dataclass(frozen=True)
class BlockedActionPolicy:
    """Built-in policy that blocks configured consequence actions."""

    blocked_actions: tuple[str, ...] = ()

    def evaluate(self, snapshot_diff: SnapshotDiff) -> PolicyEvaluation:
        return _blocked_registry_policy(snapshot_diff, self.blocked_actions)


@dataclass(frozen=True)
class ConfiguredRegistryPolicy:
    """Apply built-in action blocks and configured external policy rules."""

    blocked_actions: tuple[str, ...] = ()
    pii_change_severity: str = "off"

    def evaluate(self, snapshot_diff: SnapshotDiff) -> PolicyEvaluation:
        base = BlockedActionPolicy(self.blocked_actions).evaluate(snapshot_diff)
        findings = list(base.findings)
        pii_findings: list[PolicyFinding] = []
        pii_facts = snapshot_diff.usage.get("policy_facts", [])
        if self.pii_change_severity != "off" and isinstance(pii_facts, list):
            for fact in pii_facts:
                if not isinstance(fact, dict) or fact.get("kind") != "pii_change":
                    continue
                reason = fact.get("reason")
                if not isinstance(reason, str):
                    continue
                pii_findings.append(
                    PolicyFinding(
                        action="governance_review",
                        status=str(fact.get("status")),
                        severity=self.pii_change_severity,
                        reason=reason,
                        causal_path=tuple(item for item in fact.get("causal_path", []) if isinstance(item, str)),
                    )
                )
        findings.extend(pii_findings)
        blocked = set(base.blocked_actions)
        if self.pii_change_severity == "error" and pii_findings:
            blocked.add("governance_review")
        findings.sort(key=lambda finding: (finding.action, finding.status, finding.reason or "", finding.causal_path))
        return PolicyEvaluation(blocked_actions=tuple(sorted(blocked)), findings=tuple(findings))


def resolve_workspace_snapshot(
    workspace: Workspace,
    output_dir: str | Path = ".modelable",
    *,
    extension_pins: tuple[ExtensionPin, ...] = (),
    enum_numbers_path: str | Path | None = None,
    registry_ids_path: str | Path | None = None,
    allow_mutable_identity_replacements: bool = False,
    artifact_manifests: Sequence[Mapping[str, Any]] = (),
    usage_manifest: Mapping[str, Any] | None = None,
) -> SnapshotResult:
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
    if enum_numbers_path is None:
        enum_numbers_path = _default_enum_numbers_path(workspace)
    if registry_ids_path is None:
        registry_ids_path = _default_registry_ids_path(workspace)

    source_locations = {
        id(domain): (source.path, source.uri) for source in workspace.sources for domain in source.mdl.domains
    }
    entries: list[dict[str, Any]] = []

    for domain in workspace.mdl.domains:
        for name, model_versions in sorted(domain.models.items()):
            for model_version in sorted(model_versions, key=lambda item: item.version):
                entries.append(
                    _write_object(
                        paths,
                        domain,
                        name,
                        "model",
                        model_version,
                        source_locations.get(id(domain)),
                        workspace.mdl,
                    )
                )
        for name, projection_versions in sorted(domain.projections.items()):
            for projection_version in sorted(projection_versions, key=lambda item: item.version):
                entries.append(
                    _write_object(
                        paths,
                        domain,
                        name,
                        "projection",
                        projection_version,
                        source_locations.get(id(domain)),
                        workspace.mdl,
                    )
                )
        for decl in sorted(domain.semantic_types, key=lambda item: (item.name, item.version)):
            entries.append(
                _write_enum_object(paths, domain, decl.name, "semantic", decl, source_locations.get(id(domain)))
            )
        for projection in sorted(domain.enum_projections, key=lambda item: (item.name, item.version)):
            entries.append(
                _write_enum_object(
                    paths,
                    domain,
                    projection.name,
                    "enum_projection",
                    projection,
                    source_locations.get(id(domain)),
                )
            )

    entries.sort(key=lambda item: (str(item["identity"]), int(item["version"]), str(item["kind"])))
    if not allow_mutable_identity_replacements:
        _reject_mutable_identity_replacements(paths.root, entries)
    try:
        canonical_pins = _canonical_extension_pins(extension_pins)
    except ExtensionDescriptorError as exc:
        raise ValueError(str(exc)) from exc
    if usage_manifest is None:
        snapshot_usage = build_usage_manifest(workspace, artifact_manifests=artifact_manifests)
    else:
        try:
            snapshot_usage = validate_usage_manifest(json.loads(serialize_usage_manifest(usage_manifest)))
        except (UsageProtocolError, TypeError, ValueError) as exc:
            raise ValueError(f"Cannot load compiled usage manifest: {exc}") from exc
        usage_errors: list[str] = []
        _verify_usage_evidence(snapshot_usage, entries, usage_errors)
        if usage_errors:
            raise ValueError(usage_errors[0])
    lock = {
        "format": LOCK_FORMAT,
        "extensions": canonical_pins,
        "objects": entries,
        "imports": _serialize_imports(workspace.mdl.imports),
        "requirements": _build_requirements(entries),
        "usage": snapshot_usage,
        "usage_source": "compiled" if usage_manifest is not None else "derived",
        "generation": _generation_fingerprints(artifact_manifests),
        "allocations": {
            "registry_ids": _serialize_registry_ids(
                read_registry_ids_lock_file(Path(registry_ids_path)) if registry_ids_path is not None else {}
            ),
            "protobuf_enums": _serialize_enum_allocations(
                read_enum_numbers_lock_file(Path(enum_numbers_path)) if enum_numbers_path is not None else {}
            ),
        },
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
        lock_text = paths.lock.read_text(encoding="utf-8")
        lock = _load_json_document(lock_text)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return [f"cannot read registry lock {paths.lock}: {exc}"]
    if not isinstance(lock, dict):
        return ["registry lock payload must be a JSON object"]
    serialization_error = lock_text != _serialize_json_document(lock)
    if lock.get("format") not in SUPPORTED_LOCK_FORMATS:
        return [f"unsupported registry lock format: {lock.get('format')!r}"]

    errors: list[str] = []
    if serialization_error:
        errors.append("registry lock is not deterministically serialized")
    usage_source = lock.get("usage_source", "derived")
    if usage_source not in {"compiled", "derived"}:
        errors.append("registry lock usage_source must be 'compiled' or 'derived'")
    extensions = lock.get("extensions", [])
    if not isinstance(extensions, list):
        errors.append("registry lock extensions must be an array")
    else:
        parsed_pins: list[ExtensionPin] = []
        for entry in extensions:
            try:
                parsed_pins.append(parse_extension_pin(entry))
            except (ExtensionDescriptorError, TypeError) as exc:
                errors.append(f"invalid registry lock extension pin: {exc}")
        if len({(pin.id, pin.version) for pin in parsed_pins}) != len(parsed_pins):
            errors.append("registry lock extension pins contain duplicate identities")
        if extensions == [pin.as_dict() for pin in sorted(parsed_pins, key=_extension_pin_sort_key)]:
            pass
        elif not any("invalid registry lock extension pin" in error for error in errors):
            errors.append("registry lock extension pins are not deterministic")
    objects = lock.get("objects")
    if not isinstance(objects, list):
        return ["registry lock objects must be an array"]
    seen: set[str] = set()
    identity_hashes: dict[str, str] = {}
    contracts_by_identity: dict[str, Any] = {}
    registry_declarations: set[str] = set()
    enum_declarations: set[str] = set()
    for entry in objects:
        if not isinstance(entry, dict):
            errors.append("registry lock contains a non-object entry")
            continue
        content_hash = entry.get("content_hash")
        identity = entry.get("identity")
        if not isinstance(content_hash, str) or not isinstance(identity, str):
            errors.append("registry lock entry requires identity and content_hash")
            continue
        previous_hash = identity_hashes.get(identity)
        if previous_hash is not None and previous_hash != content_hash:
            errors.append(
                f"registry lock identity {identity} has conflicting content hashes {previous_hash} and {content_hash}"
            )
        identity_hashes[identity] = content_hash
        if content_hash in seen:
            continue
        seen.add(content_hash)
        object_path = paths.objects / f"{content_hash}.json"
        if not object_path.exists():
            errors.append(f"missing registry object {content_hash} for {identity}")
            continue
        try:
            object_text = object_path.read_text(encoding="utf-8")
            payload = _load_json_document(object_text)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"cannot read registry object {content_hash}: {exc}")
            continue
        if not isinstance(payload, dict):
            errors.append(f"registry object payload must be a JSON object for {identity}")
            continue
        if object_text != _serialize_json_document(payload):
            errors.append(f"registry object {content_hash} is not deterministically serialized")
        if payload.get("format") != OBJECT_FORMAT:
            errors.append(f"unsupported registry object format for {content_hash}")
            continue
        actual_hash = _content_hash({key: value for key, value in payload.items() if key != "content_hash"})
        if actual_hash != content_hash:
            errors.append(f"registry object hash mismatch for {content_hash}: found {actual_hash}")
        if payload.get("identity") != identity:
            errors.append(f"registry object identity mismatch for {content_hash}")
        for metadata_field in ("kind", "version", "dependencies", "provenance"):
            if entry.get(metadata_field) != payload.get(metadata_field):
                errors.append(f"registry object {metadata_field} mismatch for {identity}")
        contracts_by_identity[identity] = payload.get("contract")
        if (
            payload.get("kind") == "semantic"
            and isinstance(payload.get("contract"), dict)
            and payload["contract"].get("registry") is True
        ):
            registry_declarations.add(identity.rsplit("@", 1)[0])
        contract = payload.get("contract")
        if (
            payload.get("kind") == "semantic"
            and isinstance(contract, dict)
            and isinstance(contract.get("underlying"), dict)
            and contract["underlying"].get("kind") == "enum"
        ):
            enum_declarations.add(identity.rsplit("@", 1)[0])
        entry_change_kind = entry.get("change_kind")
        contract = payload.get("contract")
        if entry_change_kind is not None and (
            not isinstance(contract, dict) or contract.get("change_kind") != entry_change_kind
        ):
            errors.append(f"registry object change kind mismatch for {identity}")
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
    _verify_usage_evidence(lock.get("usage"), objects, errors)
    _verify_generation_fingerprints(lock.get("generation", []), errors)
    _verify_allocations(lock.get("allocations"), errors, registry_declarations, enum_declarations)
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
            requirement_entries = [
                {
                    **entry,
                    "contract": contracts_by_identity.get(str(entry["identity"]))
                    if isinstance(entry.get("identity"), str)
                    else None,
                }
                for entry in objects
                if isinstance(entry, dict)
            ]
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
                    expected = _resolve_dependency_entry(requested_value, requirement_entries, source_value)
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
                if target.get("provenance") != requirement.get("provenance"):
                    errors.append(f"registry lock requirement provenance mismatch for {source} -> {resolved}")
            try:
                expected_requirements = _build_requirements(requirement_entries)
            except ValueError as exc:
                errors.append(f"cannot reconstruct registry lock requirements: {exc}")
            else:
                if requirements != expected_requirements:
                    errors.append("registry lock requirements do not match object dependency edges")
    _verify_imports(lock.get("imports", []), errors)
    return errors


def _generation_fingerprints(manifests: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    fingerprints = []
    for manifest in manifests:
        target = manifest.get("target")
        target_name = target.get("name") if isinstance(target, Mapping) else None
        if not isinstance(target_name, str):
            raise ValueError("artifact manifest target.name must be a string")
        encoded = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        fingerprints.append({"target": target_name, "sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest()})
    return sorted(fingerprints, key=lambda item: (item["target"], item["sha256"]))


def _verify_generation_fingerprints(generation: Any, errors: list[str]) -> None:
    if not isinstance(generation, list):
        errors.append("registry lock generation must be an array")
        return
    normalized: list[dict[str, str]] = []
    for entry in generation:
        if not isinstance(entry, dict) or set(entry) != {"target", "sha256"}:
            errors.append("registry lock generation entries require target and sha256")
            continue
        target = entry.get("target")
        fingerprint = entry.get("sha256")
        if not isinstance(target, str) or not isinstance(fingerprint, str):
            errors.append("registry lock generation entries require string target and sha256")
            continue
        if re.fullmatch(r"[0-9a-f]{64}", fingerprint) is None:
            errors.append(f"registry lock generation fingerprint for {target} is invalid")
        normalized.append({"target": target, "sha256": fingerprint})
    if generation == sorted(normalized, key=lambda item: (item["target"], item["sha256"])):
        return
    if not any("registry lock generation" in error for error in errors):
        errors.append("registry lock generation is not deterministic")


def _verify_usage_evidence(
    usage: Any,
    objects: list[Any],
    errors: list[str],
) -> None:
    if not isinstance(usage, dict):
        errors.append("registry lock usage must be an object")
        return
    try:
        validate_usage_manifest(usage)
    except UsageProtocolError as error:
        errors.append(f"registry lock usage is invalid: {error}")
    if usage.get("$schema") != USAGE_SCHEMA or usage.get("kind") != "usage_manifest":
        errors.append("registry lock usage has an unsupported format")
    if not isinstance(usage.get("application"), str):
        errors.append("registry lock usage application must be a string")
    references = usage.get("references")
    if not isinstance(references, list):
        errors.append("registry lock usage references must be an array")
        return

    entries_by_identity = {
        str(entry["identity"]): entry
        for entry in objects
        if isinstance(entry, dict) and isinstance(entry.get("identity"), str)
    }
    seen: set[str] = set()
    for reference in references:
        if not isinstance(reference, dict):
            errors.append("registry lock usage contains a non-object reference")
            continue
        ref = reference.get("ref")
        signature = reference.get("signature")
        fields = reference.get("fields")
        if not isinstance(ref, str) or not isinstance(signature, str) or not isinstance(fields, list):
            errors.append("registry lock usage reference requires ref, signature, and fields")
            continue
        if ref in seen:
            errors.append(f"registry lock usage contains duplicate reference {ref}")
        seen.add(ref)
        if re.fullmatch(r"[0-9a-f]{64}", signature) is None:
            errors.append(f"registry lock usage reference {ref} has an invalid signature")
        entry = entries_by_identity.get(ref)
        if entry is None:
            errors.append(f"registry lock usage references missing object {ref}")
        elif entry.get("signature") != signature:
            errors.append(f"usage reference {ref} signature does not match locked object")
        if any(not isinstance(field, str) for field in fields):
            errors.append(f"registry lock usage fields for {ref} must be strings")
        elif fields != sorted(set(fields)):
            errors.append(f"registry lock usage fields for {ref} are not deterministic")


def _serialize_enum_allocations(
    allocations: dict[str, EnumNumberAllocation],
) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for name, allocation in sorted(allocations.items()):
        entry: dict[str, Any] = {
            "name": name,
            "unspecified": allocation.unspecified,
            "members": [{"name": member, "number": number} for member, number in allocation.members],
            "reservations": [{"name": member, "number": number} for member, number in allocation.reservations],
        }
        entry["content_hash"] = _content_hash(entry)
        serialized.append(entry)
    return serialized


def _default_enum_numbers_path(workspace: Workspace) -> Path | None:
    for source in workspace.sources:
        if source.path is not None:
            candidate = source.path.parent / "enum-numbers.lock"
            if candidate.exists():
                return candidate
    return None


def _default_registry_ids_path(workspace: Workspace) -> Path | None:
    for source in workspace.sources:
        if source.path is not None:
            candidate = source.path.parent / "registry-ids.lock"
            if candidate.exists():
                return candidate
    return None


def _serialize_registry_ids(ids: dict[str, int]) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for name, allocated_id in sorted(ids.items(), key=lambda item: item[1]):
        entry: dict[str, Any] = {"name": name, "id": allocated_id}
        entry["content_hash"] = _content_hash(entry)
        serialized.append(entry)
    return serialized


def _verify_allocations(
    allocations: Any,
    errors: list[str],
    registry_declarations: set[str],
    enum_declarations: set[str],
) -> None:
    if not isinstance(allocations, dict):
        errors.append("registry lock allocations must be an object")
        return
    protobuf_enums = allocations.get("protobuf_enums")
    if not isinstance(protobuf_enums, list):
        errors.append("registry lock protobuf enum allocations must be an array")
    else:
        _verify_enum_allocations(protobuf_enums, errors, enum_declarations)
    registry_ids = allocations.get("registry_ids")
    if not isinstance(registry_ids, list):
        errors.append("registry lock registry ID allocations must be an array")
    else:
        _verify_registry_ids(registry_ids, errors, registry_declarations)


def _verify_registry_ids(entries: list[Any], errors: list[str], registry_declarations: set[str]) -> None:
    ids: list[int] = []
    for entry in entries:
        if not isinstance(entry, dict):
            errors.append("registry lock contains a non-object registry ID allocation")
            continue
        name = entry.get("name")
        allocated_id = entry.get("id")
        content_hash = entry.get("content_hash")
        if not isinstance(name, str) or not isinstance(allocated_id, int) or not isinstance(content_hash, str):
            errors.append("registry lock registry ID allocation requires name, id, and content_hash")
            continue
        ids.append(allocated_id)
        if _content_hash({"name": name, "id": allocated_id}) != content_hash:
            errors.append(f"registry ID allocation {name} content hash mismatch")
        if name not in registry_declarations:
            errors.append(f"registry ID allocation {name} has no matching registry declaration")
        if allocated_id <= 0:
            errors.append(f"registry ID allocation {name} must be positive")
    if ids != sorted(ids):
        errors.append("registry lock registry ID allocations are not deterministic")
    if len(ids) != len(set(ids)):
        errors.append("registry lock registry ID allocations contain duplicate IDs")


def _verify_enum_allocations(protobuf_enums: list[Any], errors: list[str], enum_declarations: set[str]) -> None:
    names: list[str] = []
    for entry in protobuf_enums:
        if not isinstance(entry, dict):
            errors.append("registry lock contains a non-object protobuf enum allocation")
            continue
        name = entry.get("name")
        unspecified = entry.get("unspecified")
        members = entry.get("members")
        reservations = entry.get("reservations")
        content_hash = entry.get("content_hash")
        if (
            not isinstance(name, str)
            or not isinstance(unspecified, int)
            or not isinstance(members, list)
            or not isinstance(reservations, list)
            or not isinstance(content_hash, str)
        ):
            errors.append("registry lock protobuf enum allocation requires name, numbers, and content_hash")
            continue
        names.append(name)
        if name not in enum_declarations:
            errors.append(f"protobuf enum allocation {name} has no matching enum declaration")
        canonical = {
            "name": name,
            "unspecified": unspecified,
            "members": members,
            "reservations": reservations,
        }
        if _content_hash(canonical) != content_hash:
            errors.append(f"protobuf enum allocation {name} content hash mismatch")
        if unspecified != 0:
            errors.append(f"protobuf enum allocation {name} must reserve number 0")
        _verify_allocation_entries(name, "members", members, errors)
        _verify_allocation_entries(name, "reservations", reservations, errors)
        for category, entries in (("members", members), ("reservations", reservations)):
            numbers = [
                entry["number"] for entry in entries if isinstance(entry, dict) and isinstance(entry.get("number"), int)
            ]
            if numbers != sorted(numbers):
                errors.append(f"protobuf enum allocation {name} {category} are not deterministic")
        member_numbers = {item.get("number") for item in members if isinstance(item, dict)}
        reserved_numbers = {item.get("number") for item in reservations if isinstance(item, dict)}
        if member_numbers & reserved_numbers:
            errors.append(f"protobuf enum allocation {name} reuses a member number")
    if names != sorted(set(names)):
        errors.append("registry lock protobuf enum allocations are not deterministic")


def _verify_allocation_entries(name: str, category: str, entries: list[Any], errors: list[str]) -> None:
    seen_names: set[str] = set()
    seen_numbers: set[int] = set()
    for entry in entries:
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("name"), str)
            or not isinstance(entry.get("number"), int)
        ):
            errors.append(f"protobuf enum allocation {name} contains an invalid {category} entry")
            continue
        member_name = entry["name"]
        number = entry["number"]
        if member_name in seen_names or number in seen_numbers:
            errors.append(f"protobuf enum allocation {name} contains duplicate {category}")
        seen_names.add(member_name)
        seen_numbers.add(number)
        if number <= 0:
            errors.append(f"protobuf enum allocation {name} contains a non-positive {category} number")


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
        metadata = payload.get("domain")
        domain = domains.setdefault(domain_name, _snapshot_domain(domain_name, metadata))
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


def load_snapshot_usage_manifest(output_dir: str | Path = ".modelable") -> dict[str, Any] | None:
    """Load the validated compiled-usage evidence stored in a snapshot lock."""
    paths = SnapshotPaths(Path(output_dir))
    errors = verify_snapshot(paths.root)
    if errors:
        raise ValueError("Cannot load an invalid registry snapshot:\n" + "\n".join(errors))
    lock = json.loads(paths.lock.read_text(encoding="utf-8"))
    if lock.get("usage_source") != "compiled":
        return None
    try:
        return validate_usage_manifest(json.loads(serialize_usage_manifest(lock["usage"])))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Cannot load snapshot usage manifest: {exc}") from exc


def load_workspace_with_snapshot(workspace: Workspace, output_dir: str | Path = ".modelable") -> Workspace:
    """Compose local source documents with an exact offline registry snapshot."""
    snapshot = load_snapshot_workspace(output_dir)
    domains: dict[str, DomainDef] = {}
    for domain in [*workspace.mdl.domains, *snapshot.mdl.domains]:
        existing = domains.get(domain.name)
        if existing is None:
            domains[domain.name] = domain.model_copy(deep=True)
            continue
        for model_name, model_versions in domain.models.items():
            existing.models.setdefault(model_name, []).extend(model_versions)
        for projection_name, projection_versions in domain.projections.items():
            existing.projections.setdefault(projection_name, []).extend(projection_versions)
        existing.auto_projections.extend(domain.auto_projections)
        existing.apis.extend(domain.apis)
        existing.generate_targets.extend(domain.generate_targets)
        existing.semantic_types.extend(domain.semantic_types)
        existing.enum_projections.extend(domain.enum_projections)
        existing.index_decls.extend(domain.index_decls)
        existing.model_evolutions.extend(domain.model_evolutions)
    text = "\n\n".join(
        [
            render_mdl(
                MdlFile(
                    domains=list(domains.values()),
                    bindings=workspace.mdl.bindings,
                    workspace=workspace.mdl.workspace,
                )
            )
        ]
    )
    return load_workspace_from_sources(
        [
            WorkspaceDocumentSource(
                path=None,
                uri=f"snapshot://{Path(output_dir).resolve()}",
                text=text,
            )
        ]
    )


def _domain_metadata(domain: DomainDef) -> dict[str, Any]:
    return {
        "name": domain.name,
        "owner": domain.owner,
        "contact": domain.contact,
        "description": domain.description,
        "auto_projections": [projection.model_dump(mode="json") for projection in domain.auto_projections],
        "apis": [api.model_dump(mode="json") for api in domain.apis],
        "index_decls": [index.model_dump(mode="json") for index in domain.index_decls],
    }


def _snapshot_domain(name: str, metadata: Any = None) -> DomainDef:
    if not isinstance(metadata, dict):
        return DomainDef(name=name)
    return DomainDef.model_validate(
        {
            "name": name,
            "owner": metadata.get("owner") if isinstance(metadata.get("owner"), str) else None,
            "contact": metadata.get("contact") if isinstance(metadata.get("contact"), str) else None,
            "description": metadata.get("description") if isinstance(metadata.get("description"), str) else None,
            "auto_projections": metadata.get("auto_projections", []),
            "apis": metadata.get("apis", []),
            "index_decls": metadata.get("index_decls", []),
        }
    )


def diff_workspace_snapshot(
    workspace: Workspace,
    output_dir: str | Path = ".modelable",
    *,
    artifact_manifests: Sequence[Mapping[str, Any]] = (),
) -> SnapshotDiff:
    """Compare a validated workspace with the current local snapshot offline."""
    with tempfile.TemporaryDirectory(prefix="modelable-registry-diff-") as temporary:
        candidate = resolve_workspace_snapshot(
            workspace,
            temporary,
            allow_mutable_identity_replacements=True,
            artifact_manifests=artifact_manifests,
        )
        return diff_snapshot_paths(Path(output_dir), candidate.lock_path.parent)


def preview_workspace_snapshot(
    workspace: Workspace,
    output_dir: str | Path = ".modelable",
    *,
    artifact_manifests: Sequence[Mapping[str, Any]] = (),
) -> tuple[SnapshotDiff, int]:
    """Resolve and validate an update candidate without changing durable state."""
    paths = SnapshotPaths(Path(output_dir))
    extension_pins = _load_snapshot_extension_pins(paths)
    with tempfile.TemporaryDirectory(prefix="modelable-registry-preview-") as temporary:
        candidate_dir = Path(temporary)
        candidate = resolve_workspace_snapshot(
            workspace,
            candidate_dir,
            extension_pins=extension_pins,
            artifact_manifests=artifact_manifests,
        )
        candidate_errors = verify_snapshot(candidate_dir)
        if candidate_errors:
            raise ValueError("Candidate snapshot is invalid:\n" + "\n".join(candidate_errors))
        _reject_mutable_identity_replacements(paths.root, _load_lock_entries(SnapshotPaths(candidate_dir).lock))
        return diff_snapshot_paths(paths.root, candidate_dir), candidate.object_count


def update_workspace_snapshot(
    workspace: Workspace,
    output_dir: str | Path = ".modelable",
    *,
    blocked_actions: tuple[str, ...] = (),
    policy_evaluator: RegistryPolicyEvaluator | None = None,
    artifact_manifests: Sequence[Mapping[str, Any]] = (),
) -> tuple[SnapshotResult, SnapshotDiff]:
    """Stage and atomically install a validated local snapshot candidate."""
    paths = SnapshotPaths(Path(output_dir))
    extension_pins = _load_snapshot_extension_pins(paths)
    with tempfile.TemporaryDirectory(prefix="modelable-registry-update-") as temporary:
        candidate_dir = Path(temporary)
        candidate = resolve_workspace_snapshot(
            workspace,
            candidate_dir,
            extension_pins=extension_pins,
            artifact_manifests=artifact_manifests,
        )
        candidate_errors = verify_snapshot(candidate_dir)
        if candidate_errors:
            raise ValueError("Candidate snapshot is invalid:\n" + "\n".join(candidate_errors))
        _reject_mutable_identity_replacements(paths.root, _load_lock_entries(SnapshotPaths(candidate_dir).lock))
        snapshot_diff = diff_snapshot_paths(paths.root, candidate_dir)
        evaluator = policy_evaluator or BlockedActionPolicy(blocked_actions)
        evaluation = _normalize_policy_evaluation(evaluator.evaluate(snapshot_diff))
        blocked = sorted(set(evaluation.blocked_actions))
        if blocked:
            retained = _retain_candidate(paths, candidate_dir)
            raise RegistryPolicyError(snapshot_diff, evaluation, retained, candidate.object_count)

        paths.root.mkdir(parents=True, exist_ok=True)
        paths.objects.mkdir(parents=True, exist_ok=True)
        candidate_objects = candidate_dir / "registry" / "objects"
        temporary_lock = paths.root / f".registry.lock.tmp-{os.getpid()}"
        new_objects: list[Path] = []
        try:
            for object_path in candidate_objects.glob("*.json"):
                destination = paths.objects / object_path.name
                if not destination.exists():
                    new_objects.append(destination)
                    shutil.copyfile(object_path, destination)
            shutil.copyfile(candidate.lock_path, temporary_lock)
            os.replace(temporary_lock, paths.lock)
        except BaseException:
            for object_path in new_objects:
                object_path.unlink(missing_ok=True)
            temporary_lock.unlink(missing_ok=True)
            raise
        return SnapshotResult(paths.lock, candidate.object_count, candidate.identities), snapshot_diff


def evaluate_registry_policy(snapshot_diff: SnapshotDiff, blocked_actions: tuple[str, ...]) -> list[str]:
    """Return configured actions that would block a staged snapshot update."""
    return list(BlockedActionPolicy(blocked_actions).evaluate(snapshot_diff).blocked_actions)


def _normalize_policy_evaluation(value: PolicyEvaluation | Sequence[str]) -> PolicyEvaluation:
    if isinstance(value, PolicyEvaluation):
        return value
    return PolicyEvaluation(blocked_actions=tuple(sorted(set(value))))


def _blocked_registry_policy(snapshot_diff: SnapshotDiff, blocked_actions: tuple[str, ...]) -> PolicyEvaluation:
    blocked = set(blocked_actions)
    consequences = snapshot_diff.usage.get("consequences", [])
    findings = [
        PolicyFinding(
            action=str(consequence["action"]),
            status=str(consequence.get("status")),
            reason=consequence.get("reason") if isinstance(consequence.get("reason"), str) else None,
            causal_path=tuple(item for item in consequence.get("causal_path", []) if isinstance(item, str)),
        )
        for consequence in consequences
        if isinstance(consequence, dict)
        and consequence.get("status") != "compatible"
        and consequence.get("action") in blocked
    ]
    findings.sort(key=lambda finding: (finding.action, finding.status, finding.reason or "", finding.causal_path))
    return PolicyEvaluation(
        blocked_actions=tuple(sorted({finding.action for finding in findings})),
        findings=tuple(findings),
    )


def _retain_candidate(paths: SnapshotPaths, candidate_dir: Path) -> Path:
    candidate_id = hashlib.sha256((candidate_dir / "registry.lock").read_bytes()).hexdigest()
    retained = paths.root / "registry" / "candidates" / candidate_id
    retained.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(candidate_dir, retained, dirs_exist_ok=True)
    return retained


def _reject_mutable_identity_replacements(current_dir: Path, candidate_entries: list[dict[str, Any]]) -> None:
    current_entries = _load_lock_entries(SnapshotPaths(current_dir).lock)
    current_signatures = {
        str(entry["identity"]): str(entry.get("signature", entry.get("content_hash")))
        for entry in current_entries
        if isinstance(entry.get("identity"), str) and isinstance(entry.get("signature", entry.get("content_hash")), str)
    }
    for entry in candidate_entries:
        identity = entry.get("identity")
        signature = entry.get("signature", entry.get("content_hash"))
        if not isinstance(identity, str) or not isinstance(signature, str):
            continue
        previous_signature = current_signatures.get(identity)
        if previous_signature is not None and previous_signature != signature:
            raise ValueError(
                f"cannot replace existing registry identity {identity} with different canonical content "
                f"({previous_signature} -> {signature})"
            )


def diff_snapshot_paths(current_dir: Path, candidate_dir: Path) -> SnapshotDiff:
    current_lock = _load_lock_payload(SnapshotPaths(current_dir).lock)
    candidate_lock = _load_lock_payload(SnapshotPaths(candidate_dir).lock)
    current_entries = _lock_objects(current_lock)
    candidate_entries = _lock_objects(candidate_lock)
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
    canonical_changed = sorted(
        key
        for key in set(current_by_key) & set(candidate_by_key)
        if current_by_key[key].get("signature") != candidate_by_key[key].get("signature")
    )
    usage = _diff_usage_manifests(current_lock.get("usage"), candidate_lock.get("usage"))
    contract_consequences = _contract_consequences(candidate_by_key, canonical_changed)
    usage["consequences"].extend(consequence.as_dict() for consequence in contract_consequences)
    usage["required_actions"].extend(_required_surface_actions(contract_consequences))
    compatibility_consequences = _compatibility_consequences(current_dir, candidate_dir, added)
    usage["consequences"].extend(consequence.as_dict() for consequence in compatibility_consequences)
    usage["required_actions"].extend(_required_surface_actions(compatibility_consequences))
    consumer_consequences: list[Consequence] = []
    compiled_usage = current_lock.get("usage") if current_lock.get("usage_source") == "compiled" else None
    if isinstance(compiled_usage, dict):
        consumer_consequences = build_usage_consumer_consequences(
            [*contract_consequences, *compatibility_consequences], [compiled_usage]
        )
        usage["consequences"].extend(consequence.as_dict() for consequence in consumer_consequences)
        usage["required_actions"].extend(_required_surface_actions(consumer_consequences))
    all_consequences = [*contract_consequences, *compatibility_consequences, *consumer_consequences]
    usage["consequence_graph"] = build_consequence_graph(
        all_consequences, _change_nodes_for_consequences(all_consequences)
    )
    policy_facts = _policy_facts(compatibility_consequences)
    if policy_facts:
        usage["policy_facts"] = policy_facts
    return SnapshotDiff(
        added=tuple(_display_key(key) for key in added),
        removed=tuple(_display_key(key) for key in removed),
        changed=tuple(_display_key(key) for key in changed),
        dependencies=_diff_lock_requirements(current_lock, candidate_lock),
        usage=usage,
    )


def _load_snapshot_extension_pins(paths: SnapshotPaths) -> tuple[ExtensionPin, ...]:
    if not paths.lock.exists():
        return ()
    try:
        lock = json.loads(paths.lock.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read existing registry lock: {exc}") from exc
    extensions = lock.get("extensions", [])
    if not isinstance(extensions, list):
        raise ValueError("Existing registry lock extensions must be an array")
    try:
        pins = tuple(parse_extension_pin(entry) for entry in extensions)
    except (ExtensionDescriptorError, TypeError) as exc:
        raise ValueError(f"Existing registry lock contains an invalid extension pin: {exc}") from exc
    if len({(pin.id, pin.version) for pin in pins}) != len(pins):
        raise ValueError("Existing registry lock contains duplicate extension pin identities")
    return tuple(sorted(pins, key=_extension_pin_sort_key))


def load_snapshot_extension_pins(output_dir: str | Path = ".modelable") -> tuple[ExtensionPin, ...]:
    """Load validated extension pins from a snapshot, if its lock exists."""
    return _load_snapshot_extension_pins(SnapshotPaths(Path(output_dir)))


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
    domain: DomainDef,
    name: str,
    kind: str,
    declaration: SemanticTypeDecl | EnumProjectionDecl,
    source_location: tuple[Path | None, str] | None,
) -> dict[str, Any]:
    """Write a semantic-type or enum-projection snapshot object.

    Enum contracts participate in the same content-addressed, immutable object
    model as models and projections (evolution plan E4): same logical version
    with different canonical content lands as a ``changed`` diff entry under
    the existing immutability rule.
    """
    identity = f"{domain.name}.{name}@{declaration.version}"
    if isinstance(declaration, SemanticTypeDecl):
        signature = compute_semantic_signature(domain.name, declaration)
        dependencies = sorted(_enum_ref_dependencies(declaration.underlying, domain.name))
    else:
        signature = compute_enum_projection_signature(domain.name, declaration)
        dependencies = [f"{_qualified(name=declaration.source_name, domain=domain.name)}@{declaration.source_version}"]
    payload: dict[str, Any] = {
        "format": OBJECT_FORMAT,
        "identity": identity,
        "kind": kind,
        "version": declaration.version,
        "signature": signature,
        "dependencies": dependencies,
        "domain": _domain_metadata(domain),
        "provenance": _provenance(source_location),
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
        "provenance": payload["provenance"],
    }


def _qualified(name: str, domain: str) -> str:
    return name if "." in name else f"{domain}.{name}"


def _write_object(
    paths: SnapshotPaths,
    domain: DomainDef,
    name: str,
    kind: str,
    version: ModelVersion | ProjectionVersion,
    source_location: tuple[Path | None, str] | None,
    mdl: MdlFile,
) -> dict[str, Any]:
    identity = f"{domain.name}.{name}@{version.version}"
    # Evolution plan D5: `provenance` (which `evolves` operation last touched
    # each field) is operation-syntax-adjacent diagnostic metadata, not
    # canonical contract content -- an evolved version and an equivalent
    # hand-written full-form version must produce the same stored object and
    # the same content_hash, the same way they already produce the same
    # `signature` (compute_version_signature never looks at it either).
    # ProjectionVersion has no such field; excluding it is a no-op there.
    contract = version.model_dump(mode="json", exclude={"provenance"})
    dependencies = _dependencies(version, mdl, domain.name)
    payload: dict[str, Any] = {
        "format": OBJECT_FORMAT,
        "identity": identity,
        "kind": kind,
        "version": version.version,
        "signature": compute_version_signature(domain.name, name, version),
        "dependencies": dependencies,
        "domain": _domain_metadata(domain),
        "provenance": _provenance(source_location),
        "contract": contract,
    }
    content_hash = _content_hash(payload)
    payload["content_hash"] = content_hash
    _atomic_write_json(paths.objects / f"{content_hash}.json", payload)
    return {
        "identity": identity,
        "kind": kind,
        "version": version.version,
        **({"change_kind": version.change_kind.value} if isinstance(version, ModelVersion) else {}),
        "signature": payload["signature"],
        "content_hash": content_hash,
        "dependencies": dependencies,
        "provenance": payload["provenance"],
    }


def _load_lock_entries(lock_path: Path) -> list[dict[str, Any]]:
    return _lock_objects(_load_lock_payload(lock_path))


def _load_lock_payload(lock_path: Path) -> dict[str, Any]:
    if not lock_path.exists():
        return {}
    try:
        payload = _load_json_document(lock_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"cannot read registry lock {lock_path}: {exc}") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("format") not in SUPPORTED_LOCK_FORMATS
        or not isinstance(payload.get("objects"), list)
    ):
        raise ValueError(f"invalid registry lock {lock_path}")
    return payload


def _lock_objects(lock: dict[str, Any]) -> list[dict[str, Any]]:
    objects = lock.get("objects", [])
    return [entry for entry in objects if isinstance(entry, dict)] if isinstance(objects, list) else []


def _diff_lock_requirements(current: dict[str, Any], candidate: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    current_requirements = _requirements_by_source(current.get("requirements"))
    candidate_requirements = _requirements_by_source(candidate.get("requirements"))
    added = sorted(set(candidate_requirements) - set(current_requirements))
    removed = sorted(set(current_requirements) - set(candidate_requirements))
    changed = sorted(set(current_requirements) & set(candidate_requirements))
    return {
        "added": [candidate_requirements[source] for source in added],
        "removed": [current_requirements[source] for source in removed],
        "changed": [
            {
                "from": source,
                "current": current_requirements[source],
                "candidate": candidate_requirements[source],
            }
            for source in changed
            if current_requirements[source] != candidate_requirements[source]
        ],
    }


def _requirements_by_source(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for requirement in value:
        if isinstance(requirement, dict) and isinstance(requirement.get("from"), str):
            result[requirement["from"]] = requirement
    return result


def _diff_usage_manifests(current: Any, candidate: Any) -> dict[str, Any]:
    current_manifest = current if isinstance(current, dict) else {}
    candidate_manifest = candidate if isinstance(candidate, dict) else {}
    surface_diff = _diff_usage_entries(current_manifest.get("surfaces"), candidate_manifest.get("surfaces"), "id")
    consequences = _surface_consequences(current_manifest.get("surfaces"), candidate_manifest.get("surfaces"))
    consequences.extend(_artifact_consequences(current_manifest.get("artifacts"), candidate_manifest.get("artifacts")))
    return {
        "references": _diff_usage_entries(
            current_manifest.get("references"), candidate_manifest.get("references"), "ref"
        ),
        "artifacts": _diff_usage_entries(
            current_manifest.get("artifacts"), candidate_manifest.get("artifacts"), "target", "path"
        ),
        "surfaces": surface_diff,
        "required_actions": _required_surface_actions(consequences),
        "consequences": [consequence.as_dict() for consequence in consequences],
    }


def _contract_consequences(
    candidate_by_key: dict[tuple[str, str], dict[str, Any]], changed: list[tuple[str, str]]
) -> list[Consequence]:
    consequences: list[Consequence] = []
    for key in changed:
        entry = candidate_by_key[key]
        subject = str(entry["identity"])
        consequences.append(
            Consequence(
                action=ACTION_RECOMPILE,
                subject=subject,
                status="required",
                reason="contract content changed",
                causal_path=(subject,),
            )
        )
    return consequences


def _policy_facts(consequences: list[Consequence]) -> list[dict[str, Any]]:
    """Project stable semantic change facts for external policy evaluators."""
    facts = []
    for consequence in consequences:
        if not any(change.startswith("change:pii_changed:") for change in consequence.causal_changes):
            continue
        facts.append(
            {
                "kind": "pii_change",
                "action": consequence.action,
                "status": consequence.status,
                "reason": consequence.reason,
                "causal_path": list(consequence.causal_path),
            }
        )
    return sorted(
        facts,
        key=lambda fact: (
            str(fact["action"]),
            str(fact["status"]),
            str(fact["reason"]),
            tuple(str(item) for item in fact["causal_path"]),
        ),
    )


def _compatibility_consequences(
    current_dir: Path, candidate_dir: Path, added: list[tuple[str, str]]
) -> list[Consequence]:
    candidate_workspace = load_snapshot_workspace(candidate_dir)
    current_versions: dict[tuple[str, str, str], list[int]] = {}
    current_lock = _load_lock_payload(SnapshotPaths(current_dir).lock)
    for entry in _lock_objects(current_lock):
        kind = entry.get("kind")
        identity = entry.get("identity")
        if (
            kind not in {"model", "projection", "enum_projection"}
            or not isinstance(identity, str)
            or "@" not in identity
            or "." not in identity
        ):
            continue
        qualified_name, version_text = identity.rsplit("@", 1)
        try:
            version = int(version_text)
        except ValueError:
            continue
        domain_name, model_name = qualified_name.rsplit(".", 1)
        current_versions.setdefault((str(kind), domain_name, model_name), []).append(version)
    consequences: list[Consequence] = []
    for kind, identity in added:
        if kind not in {"model", "projection", "enum_projection"} or "@" not in identity or "." not in identity:
            continue
        qualified_name, version_text = identity.rsplit("@", 1)
        domain_name, model_name = qualified_name.rsplit(".", 1)
        try:
            to_version = int(version_text)
        except ValueError:
            continue
        previous_versions = [
            version for version in current_versions.get((kind, domain_name, model_name), ()) if version < to_version
        ]
        if not previous_versions:
            continue
        from_version = max(previous_versions)
        if kind == "model":
            report: CompatibilityReport = check_model_version_compatibility(
                candidate_workspace.mdl, domain_name, model_name, from_version, to_version
            )
            status = report.status
            reason = "direct contract change"
        elif kind == "projection":
            projection_report: ProjectionCompatibilityReport = check_projection_version_compatibility(
                candidate_workspace.mdl, domain_name, model_name, from_version, to_version
            )
            status = projection_report.status
            reason = "direct projection change"
        else:
            declarations = next(
                (domain.enum_projections for domain in candidate_workspace.mdl.domains if domain.name == domain_name),
                [],
            )
            new_declaration = next((item for item in declarations if item.version == to_version), None)
            old_declaration = next((item for item in declarations if item.version == from_version), None)
            if new_declaration is None or old_declaration is None:
                continue
            enum_changes = compare_enum_projections(domain_name, old_declaration, new_declaration)
            status = "breaking" if any(change.breaking for change in enum_changes) else "compatible"
            reason = "direct enum projection change"
        action = ACTION_BREAKING if status == "breaking" else ACTION_RECOMPILE
        consequences.append(
            Consequence(
                action=action,
                subject=identity,
                status=status,
                reason=reason,
                causal_path=(f"{domain_name}.{model_name}@{from_version}", identity),
            )
        )
        if kind == "model":
            consequences.extend(build_enum_consequences(report))
            semantic_report = compare_semantic_compatibility(report)
            consequences.extend(build_target_consequences(report, semantic_report))
            storage_report = compare_model_storage_migration(report)
            consequences.extend(build_target_consequences(report, storage_report))
            backfill_report = compare_data_backfill(report)
            consequences.extend(build_target_consequences(report, backfill_report))
            direct_subject = f"{domain_name}.{model_name}@{to_version}"
            consequences.extend(
                consequence
                for consequence in build_model_consequences(candidate_workspace, report)
                if consequence.subject != direct_subject
                and not consequence.subject.startswith("enum-exhaustive-match:")
            )
        elif kind == "projection":
            rebuild_report = compare_projection_rebuild(domain_name, model_name, projection_report.changes)
            consequences.extend(build_projection_consequences(projection_report, rebuild_report)[1:])
            governance_report = compare_governance_review(domain_name, model_name, projection_report.changes)
            consequences.extend(build_projection_consequences(projection_report, governance_report)[1:])
            wire_report = compare_projection_wire_compatibility(domain_name, model_name, projection_report.changes)
            consequences.extend(build_projection_consequences(projection_report, wire_report)[1:])
        else:
            consequences.extend(
                build_enum_projection_consequences(
                    domain_name,
                    model_name,
                    from_version,
                    to_version,
                    enum_changes,
                )[1:]
            )
    return consequences


def _artifact_consequences(current: Any, candidate: Any) -> list[Consequence]:
    artifact_diff = _diff_usage_entries(current, candidate, "target", "path")
    consequences: list[Consequence] = []
    for change in artifact_diff["changed"]:
        current_entry = change["current"]
        candidate_entry = change["candidate"]
        target = str(candidate_entry["target"])
        path = str(candidate_entry["path"])
        subject = f"generated_artifact:{target}/{path}"
        current_ref = current_entry.get("ref")
        candidate_ref = candidate_entry.get("ref")
        causal_path_values: list[str] = []
        for ref in (current_ref, candidate_ref, subject):
            if isinstance(ref, str) and (not causal_path_values or causal_path_values[-1] != ref):
                causal_path_values.append(ref)
        consequences.append(
            Consequence(
                action=ACTION_REGENERATE,
                subject=subject,
                status="required",
                reason="generated artifact changed",
                causal_path=tuple(causal_path_values),
            )
        )
    return consequences


def _surface_consequences(current: Any, candidate: Any) -> list[Consequence]:
    current_surfaces = _surface_entries_by_logical_key(current)
    candidate_surfaces = _surface_entries_by_logical_key(candidate)
    consequences: dict[tuple[str, str], Consequence] = {}
    for key in sorted(set(current_surfaces) & set(candidate_surfaces)):
        for old, new in zip(current_surfaces[key], candidate_surfaces[key], strict=False):
            if old == new:
                continue
            kind, ref = key
            if kind == "storage":
                action = ACTION_STORAGE_MIGRATION
                subject = ref
                reason = "persistence surface changed"
            elif kind == "event":
                action = ACTION_EVENT_REPLAY
                subject = str(new["id"])
                reason = "event surface changed"
            else:
                action = ACTION_CONSUMER_UPDATE
                subject = str(new["id"])
                reason = _surface_change_reason(kind)
            consequences[(action, subject)] = Consequence(
                action=action,
                subject=subject,
                status="required",
                reason=reason,
                causal_path=(ref, str(new["id"])),
            )

    return [consequences[key] for key in sorted(consequences)]


def _required_surface_actions(consequences: list[Consequence]) -> list[dict[str, str]]:
    return [
        {
            "action": consequence.action,
            "subject": consequence.subject,
            "status": consequence.status,
            "reason": consequence.reason or "",
        }
        for consequence in consequences
    ]


def _change_nodes_for_consequences(consequences: Sequence[Consequence]) -> list[dict[str, str]]:
    nodes: dict[str, dict[str, str]] = {}
    for consequence in consequences:
        for change_id in consequence.causal_changes:
            prefix, separator, remainder = change_id.partition(":")
            change_kind, separator, field = remainder.partition(":")
            if prefix != "change" or not separator or not change_kind or not field:
                continue
            nodes[change_id] = {
                "id": change_id,
                "kind": "change",
                "change_kind": change_kind,
                "field": field,
            }
    return [nodes[node_id] for node_id in sorted(nodes)]


def _surface_change_reason(kind: str) -> str:
    label = "API operation" if kind == "api_operation" else kind
    return f"{label} surface changed"


def _surface_entries_by_logical_key(value: Any) -> dict[tuple[str, str], list[dict[str, Any]]]:
    if not isinstance(value, list):
        return {}
    result: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for entry in value:
        if not isinstance(entry, dict):
            continue
        kind = entry.get("kind")
        ref = entry.get("ref")
        if isinstance(kind, str) and isinstance(ref, str):
            result.setdefault((kind, ref), []).append(entry)
    for entries in result.values():
        entries.sort(key=lambda entry: str(entry.get("id", "")))
    return result


def _diff_usage_entries(current: Any, candidate: Any, *key_fields: str) -> dict[str, list[dict[str, Any]]]:
    current_entries = _usage_entries_by_key(current, key_fields)
    candidate_entries = _usage_entries_by_key(candidate, key_fields)
    added = sorted(set(candidate_entries) - set(current_entries))
    removed = sorted(set(current_entries) - set(candidate_entries))
    changed = sorted(set(current_entries) & set(candidate_entries))
    return {
        "added": [candidate_entries[key] for key in added],
        "removed": [current_entries[key] for key in removed],
        "changed": [
            {"key": list(key), "current": current_entries[key], "candidate": candidate_entries[key]}
            for key in changed
            if current_entries[key] != candidate_entries[key]
        ],
    }


def _usage_entries_by_key(value: Any, key_fields: tuple[str, ...]) -> dict[tuple[str, ...], dict[str, Any]]:
    if not isinstance(value, list):
        return {}
    result: dict[tuple[str, ...], dict[str, Any]] = {}
    for entry in value:
        if isinstance(entry, dict) and all(isinstance(entry.get(field_name), str) for field_name in key_fields):
            result[tuple(entry[field_name] for field_name in key_fields)] = entry
    return result


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
                    "provenance": resolved["provenance"],
                }
            )
    return sorted(requirements, key=lambda item: (item["from"], item["requested"], item["resolved"]))


def _serialize_imports(imports: Sequence[Any]) -> list[dict[str, Any]]:
    serialized = [imported.model_dump(mode="json") for imported in imports if hasattr(imported, "model_dump")]
    return sorted(serialized, key=lambda item: (str(item.get("domain")), str(item.get("registry"))))


def _verify_imports(value: Any, errors: list[str]) -> None:
    if not isinstance(value, list):
        errors.append("registry lock imports must be an array")
        return
    keys: list[tuple[str, str]] = []
    for imported in value:
        if not isinstance(imported, dict):
            errors.append("registry lock contains a non-object import")
            continue
        domain = imported.get("domain")
        registry = imported.get("registry")
        if not isinstance(domain, str) or (registry is not None and not isinstance(registry, str)):
            errors.append("registry lock import requires a domain and optional registry")
            continue
        keys.append((domain, registry or ""))
    if keys != sorted(keys):
        errors.append("registry lock imports are not deterministic")
    if len(keys) != len(set(keys)):
        errors.append("registry lock imports contain duplicate domains and registries")


def _resolve_dependency_entry(
    requested: str, entries: list[dict[str, Any]], source: str | None = None
) -> dict[str, Any]:
    target, selector = _parse_dependency_requirement(requested)
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
        minimum = min((_entry_version(entry) for entry in candidates), default=None)
    elif selector.isdigit():
        matching = [entry for entry in candidates if _entry_version(entry) == int(selector)]
        minimum = None
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
    selected_version = _entry_version(selected)
    if minimum is not None:
        for entry in candidates:
            version = _entry_version(entry)
            if minimum < version <= selected_version and _entry_is_breaking(entry):
                raise ValueError(
                    f"unresolved registry dependency {requested!r}: "
                    f"breaking change at version {version} blocks automatic resolution"
                )
    if expected_hash is not None and selected.get("content_hash") != expected_hash:
        raise ValueError(f"pinned registry dependency hash mismatch for {requested!r}")
    return selected


def _parse_dependency_requirement(requested: str) -> tuple[str, str]:
    if "@" in requested:
        target, selector = requested.rsplit("@", 1)
    else:
        target, selector = requested, "latest"
    return target.strip(), "".join(selector.split()) or "latest"


def _identity_version(identity: str) -> int | None:
    version = identity.rsplit("@", 1)[-1]
    return int(version) if version.isdigit() else None


def _entry_version(entry: dict[str, Any]) -> int:
    identity = str(entry["identity"])
    version = _identity_version(identity)
    if version is None:
        raise ValueError(f"registry object identity has no numeric version: {identity!r}")
    return version


def _entry_is_breaking(entry: dict[str, Any]) -> bool:
    if entry.get("change_kind") == "breaking":
        return True
    contract = entry.get("contract")
    return isinstance(contract, dict) and contract.get("change_kind") == "breaking"


def _content_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _provenance(source_location: tuple[Path | None, str] | None) -> dict[str, str | None]:
    if source_location is None:
        return {"source": None, "source_hash": None}
    source_path, source_uri = source_location
    return {
        "source": str(source_path) if source_path is not None else source_uri,
        "source_hash": _optional_file_hash(source_path),
    }


def _optional_file_hash(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    return _file_hash(path)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(
        _serialize_json_document(payload),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _load_json_document(text: str) -> object:
    return json.loads(text, object_pairs_hook=_reject_duplicate_keys, parse_constant=_reject_non_finite)


def _serialize_json_document(document: object) -> str:
    return json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError(f"Duplicate JSON key {key!r}")
        document[key] = value
    return document


def _reject_non_finite(value: str) -> object:
    raise ValueError(f"Non-finite JSON number {value!r}")
