from __future__ import annotations

import dataclasses
import json
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
from modelable.parser.ir import ArrayType, FieldType, MapType, MdlFile, NamedType, ObjectType, ParseError
from modelable.planner.plans import write_plans
from modelable.registry.factory import get_registry
from modelable.registry.ids import allocate_registry_ids, read_lock_file, write_lock_file
from modelable.registry.index import build_registry
from modelable.registry.oci import OCIRegistryError

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
class CompilationEvent:
    level: Literal["ok", "warning", "info"]
    message: str
    path: Path | None = None
    content_hash: str | None = None


@dataclass(frozen=True)
class DirectCompilationResult:
    written_paths: tuple[Path, ...]
    events: tuple[CompilationEvent, ...]


class CompilationService:
    def execute_direct(self, request: CompilationRequest) -> DirectCompilationResult:
        return _execute_compilation(request)


def _execute_compilation(request: CompilationRequest) -> DirectCompilationResult:
    if request.target not in TARGETS:
        raise CompilationError(f"Unknown compilation target: {request.target}")

    try:
        workspace = load_workspace(request.source)
    except FileNotFoundError:
        return DirectCompilationResult(
            written_paths=(),
            events=(CompilationEvent("warning", "No .mdl files found."),),
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

    plans_dir = Path(".modelable/plans")
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

    return DirectCompilationResult(
        written_paths=tuple(sorted(set(written_paths))),
        events=tuple(events),
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
