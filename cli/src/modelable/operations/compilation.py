from __future__ import annotations

import dataclasses
import difflib
import hashlib
import json
import os
import shutil
import tempfile
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from modelable.compiler.workspace import Workspace, load_workspace
from modelable.diagnostics.model import Diagnostic
from modelable.emitters.base import EmittedArtifact, compute_content_hash
from modelable.emitters.csharp import emit_csharp
from modelable.emitters.dbt_yaml import emit_dbt_yaml
from modelable.emitters.descriptors import DescriptorGenerationError, compile_descriptor_set
from modelable.emitters.fhir import emit_fhir_profile
from modelable.emitters.go import emit_go
from modelable.emitters.grpc import emit_grpc
from modelable.emitters.java import emit_java
from modelable.emitters.json_schema import emit_json_schema
from modelable.emitters.markdown import emit_markdown
from modelable.emitters.odcs import emit_odcs
from modelable.emitters.openlineage import emit_openlineage
from modelable.emitters.openmetadata import emit_openmetadata
from modelable.emitters.protobuf import emit_protobuf
from modelable.emitters.python import emit_python
from modelable.emitters.rust import emit_rust
from modelable.emitters.sql import emit_sql
from modelable.emitters.targets import list_implemented_codegen_targets
from modelable.emitters.typescript import emit_typescript
from modelable.llm.workspace_editor import AffectedDefinition
from modelable.parser.ir import ArrayType, FieldDef, FieldType, MapType, MdlFile, NamedType, ObjectType, ParseError
from modelable.planner.plans import write_plans
from modelable.registry.factory import get_registry
from modelable.registry.ids import allocate_registry_ids, read_lock_file, write_lock_file
from modelable.registry.index import build_registry
from modelable.registry.oci import OCIRegistryError
from modelable.registry.resolver import resolve_model_ref

TARGETS = (
    "json-schema",
    "markdown",
    "typescript",
    "csharp",
    "java",
    "python",
    "rust",
    "go",
    "dbt-yaml",
    "fhir-profile",
    "openmetadata",
    "openlineage",
    "odcs",
    "protobuf",
    "grpc",
    "sql-postgres",
    "sql-clickhouse",
)

_DEFAULT_OUT_DIRS: dict[str, Path] = {
    target.name: target.default_out_dir
    for target in list_implemented_codegen_targets()
    if target.default_out_dir is not None
}
_TEXT_PREVIEW_LIMIT = 2 * 1024 * 1024
_INTERNAL_MODELABLE_PATHS = {
    (".modelable", "audit"),
    (".modelable", "locks"),
    (".modelable", "staging"),
}


class CompilationError(Exception):
    """A user-facing failure while compiling a workspace."""


class CompilationDiagnosticsError(CompilationError):
    """Structured parse or workspace diagnostics for presentation adapters."""

    def __init__(
        self,
        diagnostics: tuple[Diagnostic, ...],
        *,
        origin: Literal["parse", "workspace"],
    ) -> None:
        self.diagnostics = diagnostics
        self.origin = origin
        super().__init__("\n".join(diagnostic.message for diagnostic in diagnostics))


@dataclass(frozen=True)
class CompilationRequest:
    source: Path
    target: str
    out_dir: Path | None = None
    registry_path: str = ".modelable/registry.db"
    registry_ids_path: Path = Path("registry-ids.lock")
    allow_orphaned_registry_ids: bool = False
    domains: tuple[str, ...] = ()
    descriptor_set: bool = False


@dataclass(frozen=True)
class CompilationPolicy:
    restrict_to_workspace: bool
    write_audit: bool

    @classmethod
    def conversation(cls) -> CompilationPolicy:
        return cls(restrict_to_workspace=True, write_audit=True)


@dataclass(frozen=True)
class FileFingerprint:
    path: Path
    content_hash: str
    size: int
    resolved_parent: Path


@dataclass(frozen=True)
class CompilationFilePreview:
    category: Literal["registry_ids", "registry", "plan", "artifact", "descriptor"]
    destination: Path
    staged_path: Path
    status: Literal["created", "changed", "unchanged"]
    media_type: str
    ref: str | None
    before_hash: str | None
    after_hash: str
    before_size: int
    after_size: int
    before_text: str | None
    after_text: str | None
    diff_text: str | None


@dataclass(frozen=True)
class RegistryIdChange:
    ref: str
    registry_id: int


@dataclass(frozen=True)
class PendingCompilation:
    action_id: str
    request: CompilationRequest
    workspace_root: Path
    staging_dir: Path
    files: tuple[CompilationFilePreview, ...]
    source_fingerprints: tuple[FileFingerprint, ...]
    affected_definitions: tuple[AffectedDefinition, ...]
    registry_id_changes: tuple[RegistryIdChange, ...]
    warnings: tuple[str, ...]
    manifest_fingerprint: str


@dataclass(frozen=True)
class CompilationEvent:
    level: Literal["ok", "warning", "info"]
    message: str
    path: Path | None = None
    content_hash: str | None = None


@dataclass(frozen=True)
class DirectCompilationResult:
    written_paths: tuple[Path, ...]
    events: tuple[CompilationEvent, ...]


@dataclass(frozen=True)
class _CompilationRunResult:
    direct: DirectCompilationResult
    artifacts: tuple[EmittedArtifact, ...]


class CompilationService:
    def __init__(
        self,
        *,
        temp_root: Path | None = None,
        new_id: Callable[[], str] = lambda: str(uuid.uuid4()),
    ) -> None:
        self.temp_root = temp_root
        self.new_id = new_id

    def execute_direct(self, request: CompilationRequest) -> DirectCompilationResult:
        return _execute_compilation(request)

    def preview(
        self,
        request: CompilationRequest,
        *,
        policy: CompilationPolicy,
    ) -> PendingCompilation:
        workspace_root = _workspace_root(request.source)
        workspace = _load_preview_workspace(request.source)
        source_paths = _validated_source_paths(workspace, workspace_root)
        layout = _validate_preview_request(request, workspace_root, source_paths, policy)
        source_fingerprints = tuple(_fingerprint_source(path) for path in source_paths)
        existing_registry_ids = read_lock_file(layout.registry_ids)
        if self.temp_root is not None and Path(self.temp_root).resolve().is_relative_to(workspace_root):
            raise CompilationError("Compilation staging must be created outside the workspace.")

        staging_dir = Path(
            tempfile.mkdtemp(
                prefix="modelable-compile-",
                dir=self.temp_root,
            )
        ).resolve()
        try:
            staged_request = _stage_request(request, workspace_root, staging_dir, layout)
            if layout.registry_ids.exists():
                staged_request.registry_ids_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(layout.registry_ids, staged_request.registry_ids_path)

            run = _run_compilation(
                staged_request,
                plans_dir=staging_dir / ".modelable" / "plans",
            )
            result = run.direct
            artifact_refs = {Path(artifact.path).resolve(): artifact.ref for artifact in run.artifacts}

            files = _build_file_previews(
                result.written_paths,
                staging_dir=staging_dir,
                workspace_root=workspace_root,
                source_paths=set(source_paths),
                layout=layout,
                artifact_refs=artifact_refs,
            )
            _check_text_preview_limit(files)
            staged_registry_ids = read_lock_file(staged_request.registry_ids_path)
            registry_id_changes = tuple(
                RegistryIdChange(ref, registry_id)
                for ref, registry_id in sorted(staged_registry_ids.items())
                if ref not in existing_registry_ids
            )
            affected_definitions = _affected_definitions(
                workspace,
                request,
                artifacts=run.artifacts,
                registry_id_changes=registry_id_changes,
            )
            warnings = tuple(event.message for event in result.events if event.level == "warning")
            action_id = self.new_id()
            manifest_fingerprint = _manifest_fingerprint(
                action_id=action_id,
                request=request,
                workspace_root=workspace_root,
                files=files,
                source_fingerprints=source_fingerprints,
                affected_definitions=affected_definitions,
                registry_id_changes=registry_id_changes,
                warnings=warnings,
            )
            return PendingCompilation(
                action_id=action_id,
                request=request,
                workspace_root=workspace_root,
                staging_dir=staging_dir,
                files=files,
                source_fingerprints=source_fingerprints,
                affected_definitions=affected_definitions,
                registry_id_changes=registry_id_changes,
                warnings=warnings,
                manifest_fingerprint=manifest_fingerprint,
            )
        except BaseException:
            _remove_staging(staging_dir)
            raise

    def discard(self, pending: PendingCompilation) -> None:
        _remove_staging(pending.staging_dir)


@dataclass(frozen=True)
class _PreviewLayout:
    out_dir: Path
    registry: Path
    registry_ids: Path


def _workspace_root(source: Path) -> Path:
    resolved = source.resolve()
    if resolved.is_file():
        return resolved.parent
    return resolved


def _load_preview_workspace(source: Path) -> Workspace:
    try:
        workspace = load_workspace(source)
    except FileNotFoundError as exc:
        raise CompilationError(str(exc)) from exc
    except ParseError as exc:
        raise CompilationDiagnosticsError(
            (exc.diagnostic(path=str(source)),),
            origin="parse",
        ) from exc
    if workspace.errors:
        raise CompilationDiagnosticsError(tuple(workspace.errors), origin="workspace")
    return workspace


def _validated_source_paths(workspace: Workspace, workspace_root: Path) -> tuple[Path, ...]:
    paths: list[Path] = []
    for source in workspace.sources:
        if source.path is None:
            continue
        path = source.path.resolve()
        if not path.is_relative_to(workspace_root):
            raise CompilationError(f".mdl source resolves outside the workspace: {source.path}")
        paths.append(path)
    return tuple(sorted(paths))


def _validate_preview_request(
    request: CompilationRequest,
    workspace_root: Path,
    source_paths: tuple[Path, ...],
    policy: CompilationPolicy,
) -> _PreviewLayout:
    if request.target not in TARGETS:
        raise CompilationError(f"Unknown compilation target: {request.target}")
    if request.registry_path.startswith("oci://"):
        raise CompilationError("OCI registry paths are not allowed for conversational compilation.")
    if request.descriptor_set and request.target not in ("protobuf", "grpc"):
        raise CompilationError("descriptor sets are supported only for protobuf and grpc targets")
    if not policy.restrict_to_workspace:
        raise CompilationError("Compilation preview requires a workspace-restricted policy.")

    output = request.out_dir or _DEFAULT_OUT_DIRS[request.target]
    out_dir = _resolve_conversation_path(
        workspace_root,
        output,
        label="output path",
        source_paths=source_paths,
        reject_modelable=True,
    )
    registry = _resolve_conversation_path(
        workspace_root,
        Path(request.registry_path),
        label="registry path",
        source_paths=source_paths,
    )
    registry_ids = _resolve_conversation_path(
        workspace_root,
        request.registry_ids_path,
        label="registry ID path",
        source_paths=source_paths,
    )
    if registry == registry_ids:
        raise CompilationError("Registry and registry ID paths must be distinct.")
    if out_dir == registry_ids or out_dir.is_relative_to(registry_ids):
        raise CompilationError("Output path overlaps the registry ID control path.")
    if out_dir == registry or out_dir.is_relative_to(registry):
        raise CompilationError("Output path overlaps the registry control path.")
    return _PreviewLayout(out_dir=out_dir, registry=registry, registry_ids=registry_ids)


def _resolve_conversation_path(
    workspace_root: Path,
    path: Path,
    *,
    label: str,
    source_paths: tuple[Path, ...] | set[Path],
    reject_modelable: bool = False,
) -> Path:
    if path.is_absolute():
        raise CompilationError(f"{label} must be workspace-relative.")
    normalized = Path(os.path.normpath(workspace_root / path))
    resolved = normalized.resolve(strict=False)
    if not resolved.is_relative_to(workspace_root):
        raise CompilationError(f"{label} resolves outside the workspace: {path}")

    relative_parts = tuple(
        canonical
        for part in resolved.relative_to(workspace_root).parts
        if (canonical := _canonical_policy_component(part))
    )
    if ".git" in relative_parts:
        raise CompilationError(f"{label} must not be inside .git: {path}")
    for prohibited in _INTERNAL_MODELABLE_PATHS:
        if relative_parts[: len(prohibited)] == prohibited:
            rendered = "/".join(prohibited)
            raise CompilationError(f"{label} must not be inside {rendered}: {path}")
    if reject_modelable and relative_parts[:1] == (".modelable",):
        raise CompilationError(f"output path must not use internal .modelable paths: {path}")
    if (
        any(resolved == source or resolved.is_relative_to(source) for source in source_paths)
        or resolved.suffix.lower() == ".mdl"
    ):
        raise CompilationError(f"{label} overlaps a .mdl source: {path}")
    return normalized


def _canonical_policy_component(component: str) -> str:
    return component.rstrip(" .").lower()


def _stage_request(
    request: CompilationRequest,
    workspace_root: Path,
    staging_dir: Path,
    layout: _PreviewLayout,
) -> CompilationRequest:
    def staged(path: Path) -> Path:
        return staging_dir / path.relative_to(workspace_root)

    return dataclasses.replace(
        request,
        source=request.source.resolve(),
        out_dir=staged(layout.out_dir),
        registry_path=str(staged(layout.registry)),
        registry_ids_path=staged(layout.registry_ids),
    )


def _build_file_previews(
    written_paths: tuple[Path, ...],
    *,
    staging_dir: Path,
    workspace_root: Path,
    source_paths: set[Path],
    layout: _PreviewLayout,
    artifact_refs: dict[Path, str],
) -> tuple[CompilationFilePreview, ...]:
    previews: list[CompilationFilePreview] = []
    for written_path in sorted(set(written_paths)):
        staged_path = written_path.resolve()
        if not staged_path.is_relative_to(staging_dir):
            raise CompilationError(f"Compiler wrote outside the staging directory: {written_path}")
        relative = staged_path.relative_to(staging_dir)
        destination = workspace_root / relative
        _resolve_conversation_path(
            workspace_root,
            relative,
            label="generated destination",
            source_paths=source_paths,
            reject_modelable=relative.parts[:1] == (".modelable",)
            and not (
                destination == layout.registry
                or destination == layout.registry_ids
                or relative.parts[:2] == (".modelable", "plans")
            ),
        )
        category = _file_category(destination, layout)
        before_bytes = destination.read_bytes() if destination.exists() else None
        after_bytes = staged_path.read_bytes()
        previews.append(
            _file_preview(
                category=category,
                destination=destination,
                staged_path=staged_path,
                before_bytes=before_bytes,
                after_bytes=after_bytes,
                ref=artifact_refs.get(staged_path),
            )
        )
    return tuple(sorted(previews, key=lambda item: item.destination.as_posix()))


def _file_category(
    destination: Path,
    layout: _PreviewLayout,
) -> Literal["registry_ids", "registry", "plan", "artifact", "descriptor"]:
    if destination == layout.registry_ids:
        return "registry_ids"
    if destination == layout.registry:
        return "registry"
    if destination.suffix == ".pb":
        return "descriptor"
    if destination.name.endswith(".plan.json"):
        return "plan"
    return "artifact"


def _file_preview(
    *,
    category: Literal["registry_ids", "registry", "plan", "artifact", "descriptor"],
    destination: Path,
    staged_path: Path,
    before_bytes: bytes | None,
    after_bytes: bytes,
    ref: str | None,
) -> CompilationFilePreview:
    before_hash = _bytes_hash(before_bytes) if before_bytes is not None else None
    after_hash = _bytes_hash(after_bytes)
    status: Literal["created", "changed", "unchanged"]
    if before_bytes is None:
        status = "created"
    elif before_bytes == after_bytes:
        status = "unchanged"
    else:
        status = "changed"

    before_text: str | None = None
    after_text: str | None = None
    diff_text: str | None = None
    is_binary = category in ("registry", "descriptor")
    if not is_binary:
        try:
            decoded_after = after_bytes.decode("utf-8")
            decoded_before = "" if before_bytes is None else before_bytes.decode("utf-8")
        except UnicodeDecodeError:
            is_binary = True
        else:
            if status != "unchanged":
                before_text = decoded_before
                after_text = decoded_after
                diff_text = "".join(
                    difflib.unified_diff(
                        decoded_before.splitlines(keepends=True),
                        decoded_after.splitlines(keepends=True),
                        fromfile=str(destination),
                        tofile=str(destination),
                    )
                )

    return CompilationFilePreview(
        category=category,
        destination=destination,
        staged_path=staged_path,
        status=status,
        media_type=_media_type(destination, binary=is_binary),
        ref=_plan_ref(destination) if category == "plan" else ref,
        before_hash=before_hash,
        after_hash=after_hash,
        before_size=len(before_bytes) if before_bytes is not None else 0,
        after_size=len(after_bytes),
        before_text=before_text,
        after_text=after_text,
        diff_text=diff_text,
    )


def _media_type(path: Path, *, binary: bool) -> str:
    if binary:
        return "application/octet-stream"
    if path.suffix == ".json" or path.name.endswith(".lock"):
        return "application/json"
    if path.suffix in (".yaml", ".yml"):
        return "application/yaml"
    return "text/plain; charset=utf-8"


def _plan_ref(path: Path) -> str | None:
    stem = path.name.removesuffix(".plan.json")
    domain_and_name, _, version = stem.rpartition(".v")
    return f"{domain_and_name}@{version}" if domain_and_name and version else None


def _check_text_preview_limit(files: tuple[CompilationFilePreview, ...]) -> None:
    payload = [
        {
            "before": item.before_text,
            "after": item.after_text,
            "diff": item.diff_text,
        }
        for item in files
        if item.after_text is not None
    ]
    size = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    if size > _TEXT_PREVIEW_LIMIT:
        raise CompilationError(
            "Compilation text preview exceeds the 2 MiB limit; use direct modelable compile instead."
        )


def _fingerprint_source(path: Path) -> FileFingerprint:
    content = path.read_bytes()
    return FileFingerprint(
        path=path,
        content_hash=_bytes_hash(content),
        size=len(content),
        resolved_parent=path.parent.resolve(),
    )


def _affected_definitions(
    workspace: Workspace,
    request: CompilationRequest,
    *,
    artifacts: tuple[EmittedArtifact, ...],
    registry_id_changes: tuple[RegistryIdChange, ...],
) -> tuple[AffectedDefinition, ...]:
    affected: dict[str, AffectedDefinition] = {}
    artifact_refs = sorted({artifact.ref for artifact in artifacts})
    for ref in artifact_refs:
        affected[ref] = AffectedDefinition(ref, "generated", f"{request.target} artifact")
        for dependency in _definition_dependencies(workspace.mdl, ref):
            affected.setdefault(
                dependency,
                AffectedDefinition(dependency, "consumed", f"required by {ref}"),
            )
    for change in registry_id_changes:
        affected.setdefault(
            change.ref,
            AffectedDefinition(change.ref, "allocated", "new registry ID allocated"),
        )
    return tuple(affected[ref] for ref in sorted(affected))


def _definition_dependencies(mdl: MdlFile, ref: str) -> tuple[str, ...]:
    qualified_name, separator, version_text = ref.rpartition("@")
    if not separator:
        domain = next((item for item in mdl.domains if item.name == ref), None)
        if domain is None:
            return ()
        definitions = {
            *(
                f"{domain.name}.{name}@{version.version}"
                for name, versions in domain.models.items()
                for version in versions
            ),
            *(
                f"{domain.name}.{name}@{version.version}"
                for name, versions in domain.projections.items()
                for version in versions
            ),
        }
        domain_dependencies = set(definitions)
        for definition in definitions:
            domain_dependencies.update(_definition_dependencies(mdl, definition))
        return tuple(sorted(domain_dependencies))
    if not version_text.isdigit():
        return ()
    domain_name, separator, definition_name = qualified_name.partition(".")
    if not separator:
        return ()
    domain = next((item for item in mdl.domains if item.name == domain_name), None)
    if domain is None:
        return ()
    version = int(version_text)
    model = next(
        (item for item in domain.models.get(definition_name, ()) if item.version == version),
        None,
    )
    projection = next(
        (item for item in domain.projections.get(definition_name, ()) if item.version == version),
        None,
    )
    dependencies: set[str] = set()
    if model is not None:
        for field in model.fields:
            names: set[str] = set()
            _collect_named_type_names(field.type, names)
            dependencies.update(_semantic_refs(mdl, names))
    if projection is not None:
        references = [
            (projection.source.model, projection.source.version),
            *((join.model, join.version) for join in projection.joins),
        ]
        for model_ref, version_spec in references:
            try:
                resolved = resolve_model_ref(mdl, model_ref, version_spec)
            except LookupError:
                continue
            dependency = f"{resolved.domain_name}.{resolved.model_name}@{resolved.version.version}"
            dependencies.add(dependency)
            for source_field in resolved.version.fields:
                if not isinstance(source_field, FieldDef):
                    continue
                names = set()
                _collect_named_type_names(source_field.type, names)
                dependencies.update(_semantic_refs(mdl, names))
    dependencies.discard(ref)
    return tuple(sorted(dependencies))


def _semantic_refs(mdl: MdlFile, names: set[str]) -> set[str]:
    refs: set[str] = set()
    for name in sorted(names):
        domain_name = _domain_defining(mdl, name)
        if domain_name is None:
            continue
        domain = next(domain for domain in mdl.domains if domain.name == domain_name)
        if any(declaration.name == name for declaration in domain.semantic_types):
            refs.add(f"{domain.name}.{name}")
    return refs


def _manifest_fingerprint(
    *,
    action_id: str,
    request: CompilationRequest,
    workspace_root: Path,
    files: tuple[CompilationFilePreview, ...],
    source_fingerprints: tuple[FileFingerprint, ...],
    affected_definitions: tuple[AffectedDefinition, ...],
    registry_id_changes: tuple[RegistryIdChange, ...],
    warnings: tuple[str, ...],
) -> str:
    manifest = {
        "action_id": action_id,
        "request": {
            "source": str(request.source),
            "target": request.target,
            "out_dir": str(request.out_dir) if request.out_dir is not None else None,
            "registry_path": request.registry_path,
            "registry_ids_path": str(request.registry_ids_path),
            "allow_orphaned_registry_ids": request.allow_orphaned_registry_ids,
            "domains": request.domains,
            "descriptor_set": request.descriptor_set,
        },
        "workspace_root": str(workspace_root),
        "files": [
            {
                "category": item.category,
                "destination": str(item.destination),
                "status": item.status,
                "media_type": item.media_type,
                "ref": item.ref,
                "before_hash": item.before_hash,
                "after_hash": item.after_hash,
                "before_size": item.before_size,
                "after_size": item.after_size,
                "resolved_parent": str(item.destination.parent.resolve()),
            }
            for item in files
        ],
        "sources": [
            {
                "path": str(item.path),
                "content_hash": item.content_hash,
                "size": item.size,
                "resolved_parent": str(item.resolved_parent),
            }
            for item in source_fingerprints
        ],
        "affected": [dataclasses.asdict(item) for item in affected_definitions],
        "registry_id_changes": [dataclasses.asdict(item) for item in registry_id_changes],
        "warnings": warnings,
    }
    serialized = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return _bytes_hash(serialized.encode("utf-8"))


def _bytes_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _remove_staging(path: Path) -> None:
    if not path.exists():
        return
    try:
        shutil.rmtree(path)
    except OSError as exc:
        raise CompilationError(f"Compilation staging cleanup failed: {path}") from exc
    if path.exists():
        raise CompilationError(f"Compilation staging cleanup failed: {path}")


def _execute_compilation(request: CompilationRequest) -> DirectCompilationResult:
    return _run_compilation(request, plans_dir=Path(".modelable/plans")).direct


def _run_compilation(
    request: CompilationRequest,
    *,
    plans_dir: Path,
) -> _CompilationRunResult:
    if request.target not in TARGETS:
        raise CompilationError(f"Unknown compilation target: {request.target}")

    try:
        workspace = load_workspace(request.source)
    except FileNotFoundError:
        return _CompilationRunResult(
            direct=DirectCompilationResult(
                written_paths=(),
                events=(CompilationEvent("warning", "No .mdl files found."),),
            ),
            artifacts=(),
        )
    except ParseError as exc:
        raise CompilationDiagnosticsError(
            (exc.diagnostic(path=str(request.source)),),
            origin="parse",
        ) from exc

    if workspace.errors:
        raise CompilationDiagnosticsError(
            tuple(workspace.errors),
            origin="workspace",
        )

    emit_workspace = _scope_workspace(workspace, request)

    existing_registry_ids = read_lock_file(request.registry_ids_path)
    try:
        registry_ids = allocate_registry_ids(
            workspace.mdl,
            existing_registry_ids,
            allow_orphaned=request.allow_orphaned_registry_ids,
        )
    except ValueError as exc:
        raise CompilationError(str(exc)) from exc
    write_lock_file(request.registry_ids_path, registry_ids)

    registry = get_registry(request.registry_path)
    if request.registry_path.startswith("oci://"):
        built_registry_path = build_registry(workspace, Path(".modelable"), registry_ids=registry_ids)
    else:
        local_registry_path = Path(request.registry_path)
        built_registry_path = build_registry(
            workspace,
            local_registry_path.parent,
            registry_ids=registry_ids,
        )
    try:
        registry.push(built_registry_path)
    except OCIRegistryError as exc:
        raise CompilationError(str(exc)) from exc

    events = [CompilationEvent("ok", f"wrote {request.registry_path}")]
    written_paths = [request.registry_ids_path]
    if not request.registry_path.startswith("oci://"):
        written_paths.append(Path(request.registry_path))

    plan_paths = write_plans(workspace, plans_dir)
    written_paths.extend(Path(path).resolve() for path in plan_paths)
    events.extend(CompilationEvent("ok", f"wrote {path}", path=Path(path)) for path in plan_paths)

    output = request.out_dir or _DEFAULT_OUT_DIRS[request.target]
    output.mkdir(parents=True, exist_ok=True)
    artifacts = _emit_target(
        emit_workspace,
        request.target,
        output,
        registry_ids,
        descriptor_set=request.descriptor_set,
    )
    for artifact in artifacts:
        _write_artifact(artifact)
        path = Path(artifact.path)
        written_paths.append(path)
        events.extend(CompilationEvent("warning", warning) for warning in artifact.warnings)
        events.append(
            CompilationEvent(
                "ok",
                str(artifact.path),
                path=path,
                content_hash=artifact.content_hash,
            )
        )
    if not artifacts:
        events.append(CompilationEvent("warning", "No artifacts generated."))

    return _CompilationRunResult(
        direct=DirectCompilationResult(
            written_paths=tuple(sorted(set(written_paths))),
            events=tuple(events),
        ),
        artifacts=tuple(artifacts),
    )


def _scope_workspace(workspace: Workspace, request: CompilationRequest) -> Workspace:
    if not request.domains:
        return workspace

    known_domains = {domain.name for domain in workspace.mdl.domains}
    unknown_domains = sorted(set(request.domains) - known_domains)
    if unknown_domains:
        raise CompilationError(
            f"Unknown --domain value(s): {', '.join(unknown_domains)}. "
            f"Available domains: {', '.join(sorted(known_domains))}"
        )
    requested = set(request.domains)
    violations = _find_domain_scope_violations(
        workspace.mdl,
        requested,
        resolve_semantics=request.target in ("protobuf", "grpc"),
    )
    if violations:
        raise CompilationError(
            "Cannot scope compilation with --domain: the requested domain(s) have "
            "dependencies outside the requested set:\n"
            + "\n".join(f"  - {violation}" for violation in violations)
            + "\nAdd the missing domain(s) to --domain, or narrow the requested set."
        )
    scoped_domains = [domain for domain in workspace.mdl.domains if domain.name in request.domains]
    return dataclasses.replace(
        workspace,
        mdl=workspace.mdl.model_copy(update={"domains": scoped_domains}),
    )


def _emit_target(
    workspace: Workspace,
    target: str,
    output: Path,
    registry_ids: dict[str, int],
    *,
    descriptor_set: bool,
) -> list[EmittedArtifact]:
    if target == "json-schema":
        return emit_json_schema(workspace, output)
    if target == "markdown":
        return emit_markdown(workspace, output)
    if target == "typescript":
        return emit_typescript(workspace, output)
    if target == "csharp":
        return emit_csharp(workspace, output)
    if target == "java":
        return emit_java(workspace, output)
    if target == "python":
        return emit_python(workspace, output)
    if target == "rust":
        return emit_rust(workspace, output, registry_ids=registry_ids)
    if target == "go":
        return emit_go(workspace, output)
    if target == "dbt-yaml":
        return emit_dbt_yaml(workspace, output)
    if target == "fhir-profile":
        return emit_fhir_profile(workspace, output)
    if target == "openmetadata":
        return emit_openmetadata(workspace, output)
    if target == "openlineage":
        return emit_openlineage(workspace, output)
    if target == "odcs":
        return emit_odcs(workspace, output)
    if target == "protobuf":
        artifacts = emit_protobuf(workspace, output, registry_ids=registry_ids)
        if descriptor_set:
            try:
                return _emit_protobuf_with_descriptors(artifacts, output)
            except DescriptorGenerationError as exc:
                raise CompilationError(str(exc)) from exc
        return artifacts
    if target == "grpc":
        artifacts = emit_grpc(workspace, output, registry_ids=registry_ids)
        if descriptor_set:
            try:
                return _emit_grpc_with_descriptors(artifacts, output)
            except DescriptorGenerationError as exc:
                raise CompilationError(str(exc)) from exc
        return artifacts
    if target in ("sql-postgres", "sql-clickhouse"):
        return emit_sql(workspace, output, target.removeprefix("sql-"))
    raise CompilationError(f"Unknown compilation target: {target}")


def _collect_named_type_names(field_type: FieldType, result: set[str]) -> None:
    if isinstance(field_type, NamedType):
        result.add(field_type.name)
    elif isinstance(field_type, ArrayType):
        _collect_named_type_names(field_type.item, result)
    elif isinstance(field_type, MapType):
        _collect_named_type_names(field_type.value, result)
    elif isinstance(field_type, ObjectType):
        for field in field_type.fields:
            _collect_named_type_names(field.type, result)


def _domain_defining(mdl: MdlFile, name: str) -> str | None:
    for domain in mdl.domains:
        if name in domain.models:
            return domain.name
        if any(declaration.name == name for declaration in domain.semantic_types):
            return domain.name
    return None


def _semantic_domains_defining(mdl: MdlFile, name: str) -> tuple[str, ...]:
    return tuple(
        sorted(
            domain.name
            for domain in mdl.domains
            if any(declaration.name == name for declaration in domain.semantic_types)
        )
    )


def _find_domain_scope_violations(
    mdl: MdlFile,
    requested: set[str],
    *,
    resolve_semantics: bool = False,
) -> list[str]:
    violations: list[str] = []
    for domain in mdl.domains:
        if domain.name not in requested:
            continue
        for model_name, versions in domain.models.items():
            for version in versions:
                for field in version.fields:
                    names: set[str] = set()
                    _collect_named_type_names(field.type, names)
                    for name in names:
                        semantic_domains = _semantic_domains_defining(mdl, name) if resolve_semantics else ()
                        if len(semantic_domains) > 1:
                            candidates = ", ".join(f"{target_domain}.{name}" for target_domain in semantic_domains)
                            violations.append(
                                f"{domain.name}.{model_name}@{version.version} field '{field.name}' "
                                f"references ambiguous type '{name}'; candidates: {candidates}"
                            )
                            continue
                        target_domain = semantic_domains[0] if semantic_domains else _domain_defining(mdl, name)
                        if (
                            target_domain is not None
                            and target_domain != domain.name
                            and target_domain not in requested
                        ):
                            violations.append(
                                f"{domain.name}.{model_name}@{version.version} field '{field.name}' "
                                f"references type '{name}' defined in domain '{target_domain}', "
                                "which is excluded by --domain"
                            )
        for projection_name, projection_versions in domain.projections.items():
            for projection_version in projection_versions:
                referenced_models = [
                    projection_version.source.model,
                    *(join.model for join in projection_version.joins),
                ]
                for referenced_model in referenced_models:
                    try:
                        source_domain, _ = referenced_model.rsplit(".", 1)
                    except ValueError:
                        continue
                    if source_domain != domain.name and source_domain not in requested:
                        violations.append(
                            f"{domain.name}.{projection_name}@{projection_version.version} references "
                            f"'{referenced_model}' in domain '{source_domain}', which is excluded by --domain"
                        )
    return violations


def _write_artifact(artifact: EmittedArtifact) -> None:
    path = Path(artifact.path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(artifact.content, bytes):
        path.write_bytes(artifact.content)
    elif isinstance(artifact.content, dict):
        path.write_text(
            json.dumps(artifact.content, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    else:
        path.write_text(artifact.content, encoding="utf-8")


def _emit_protobuf_with_descriptors(
    artifacts: list[EmittedArtifact],
    output: Path,
) -> list[EmittedArtifact]:
    for artifact in artifacts:
        if artifact.path.name != "schema-manifest.json":
            _write_artifact(artifact)

    result: list[EmittedArtifact] = []
    for artifact in artifacts:
        if artifact.path.name != "schema-manifest.json":
            result.append(artifact)
            continue
        assert isinstance(artifact.content, str)
        schema = json.loads(artifact.content)["schemas"][0]
        ref = str(schema["ref"])
        proto_path = Path(artifact.path.parent / (artifact.path.parent.name + ".proto"))
        descriptor_path = Path(artifact.path.parent / (artifact.path.parent.name + ".descriptor.pb"))
        descriptor_bytes = compile_descriptor_set(
            proto_root=output,
            proto_files=[proto_path],
            out_path=descriptor_path,
            target_ref=ref,
        )
        descriptor_artifact = EmittedArtifact(
            target=artifact.target,
            ref=artifact.ref,
            artifact_id=f"{artifact.artifact_id}.descriptor",
            path=descriptor_path,
            content=descriptor_bytes,
            content_hash=compute_content_hash(descriptor_bytes),
        )
        manifest_content = _with_schema_descriptor_metadata(
            artifact.content,
            descriptor_path=descriptor_path,
            descriptor_hash=descriptor_artifact.content_hash,
        )
        manifest_artifact = EmittedArtifact(
            target=artifact.target,
            ref=artifact.ref,
            artifact_id=artifact.artifact_id,
            path=artifact.path,
            content=manifest_content,
            content_hash=compute_content_hash(manifest_content),
            warnings=artifact.warnings,
        )
        result.extend([descriptor_artifact, manifest_artifact])
    return result


def _with_schema_descriptor_metadata(
    manifest_content: str,
    *,
    descriptor_path: Path,
    descriptor_hash: str,
) -> str:
    manifest = json.loads(manifest_content)
    schema = manifest["schemas"][0]
    schema["descriptor"] = {
        "path": descriptor_path.name,
        "content_hash": descriptor_hash,
        "include_imports": True,
    }
    return json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"


def _emit_grpc_with_descriptors(
    artifacts: list[EmittedArtifact],
    output: Path,
) -> list[EmittedArtifact]:
    for artifact in artifacts:
        if artifact.path.name != "service-manifest.json":
            _write_artifact(artifact)

    result: list[EmittedArtifact] = []
    for artifact in artifacts:
        if artifact.path.name != "service-manifest.json":
            result.append(artifact)
            continue
        assert isinstance(artifact.content, str)
        manifest = json.loads(artifact.content)
        ref = str(manifest["ref"])
        service_proto = Path(artifact.path.parent / str(manifest["service_proto"]))
        payload_proto = Path(artifact.path.parent / (artifact.path.parent.name + ".proto"))
        descriptor_path = Path(artifact.path.parent / (artifact.path.parent.name + ".grpc.descriptor.pb"))
        proto_files = [service_proto]
        if payload_proto.exists():
            proto_files.append(payload_proto)
        descriptor_bytes = compile_descriptor_set(
            proto_root=output,
            proto_files=proto_files,
            out_path=descriptor_path,
            target_ref=ref,
        )
        descriptor_artifact = EmittedArtifact(
            target=artifact.target,
            ref=artifact.ref,
            artifact_id=f"{artifact.artifact_id}.descriptor",
            path=descriptor_path,
            content=descriptor_bytes,
            content_hash=compute_content_hash(descriptor_bytes),
        )
        manifest_content = _with_service_descriptor_metadata(
            artifact.content,
            descriptor_path=descriptor_path,
            descriptor_hash=descriptor_artifact.content_hash,
        )
        manifest_artifact = EmittedArtifact(
            target=artifact.target,
            ref=artifact.ref,
            artifact_id=artifact.artifact_id,
            path=artifact.path,
            content=manifest_content,
            content_hash=compute_content_hash(manifest_content),
            warnings=artifact.warnings,
        )
        result.extend([descriptor_artifact, manifest_artifact])
    return result


def _with_service_descriptor_metadata(
    manifest_content: str,
    *,
    descriptor_path: Path,
    descriptor_hash: str,
) -> str:
    manifest = json.loads(manifest_content)
    manifest["descriptor"] = {
        "path": descriptor_path.name,
        "content_hash": descriptor_hash,
        "include_imports": True,
    }
    return json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
