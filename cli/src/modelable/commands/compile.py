from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path, PurePath

import click

from modelable.commands.common import console, load_workspace_or_exit
from modelable.emitters.base import EmittedArtifact, compute_content_hash
from modelable.emitters.csharp import emit_csharp
from modelable.emitters.dbt_yaml import emit_dbt_yaml
from modelable.emitters.descriptors import DescriptorGenerationError, compile_descriptor_set
from modelable.emitters.diagnostics import deferred_target
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
from modelable.parser.ir import ArrayType, FieldType, MapType, MdlFile, NamedType, ObjectType
from modelable.planner.plans import write_plans
from modelable.registry.factory import get_registry
from modelable.registry.ids import allocate_registry_ids, read_lock_file, write_lock_file
from modelable.registry.index import build_registry
from modelable.registry.oci import OCIRegistryError

_DEFAULT_OUT_DIRS: dict[str, Path] = {
    target.name: target.default_out_dir
    for target in list_implemented_codegen_targets()
    if target.default_out_dir is not None
}


def _collect_named_type_names(field_type: FieldType, result: set[str]) -> None:
    """Recursively collect NamedType names referenced by a field type."""
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
    """Return the first domain that defines a model or semantic type, or None."""
    for domain in mdl.domains:
        if name in domain.models:
            return domain.name
        if any(decl.name == name for decl in domain.semantic_types):
            return domain.name
    return None


def _semantic_domains_defining(mdl: MdlFile, name: str) -> tuple[str, ...]:
    """Return every domain that declares this semantic type name."""
    return tuple(
        sorted(domain.name for domain in mdl.domains if any(decl.name == name for decl in domain.semantic_types))
    )


def _find_domain_scope_violations(
    mdl: MdlFile,
    requested: set[str],
    *,
    resolve_semantics: bool = False,
) -> list[str]:
    """Find dependencies of requested domains that resolve only outside the requested set.

    Checks both NamedType field references (recursively, across arrays/maps/nested
    objects) and projection source/join model references. Uses the full, unfiltered
    `mdl` to resolve where a dependency actually lives, so a reference to a domain
    that isn't part of the workspace at all is left alone (that is `validate`'s job,
    not this filter's).
    """
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
        for projection_name, proj_versions in domain.projections.items():
            for proj_version in proj_versions:
                ref_models = [proj_version.source.model, *(join.model for join in proj_version.joins)]
                for ref_model in ref_models:
                    try:
                        source_domain, _ = ref_model.rsplit(".", 1)
                    except ValueError:
                        continue
                    if source_domain != domain.name and source_domain not in requested:
                        violations.append(
                            f"{domain.name}.{projection_name}@{proj_version.version} references "
                            f"'{ref_model}' in domain '{source_domain}', which is excluded by --domain"
                        )
    return violations


def register_compile_commands(cli_group: click.Group) -> None:
    cli_group.add_command(compile)
    cli_group.add_command(docs)


@click.command()
@click.argument("source", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--target",
    required=True,
    type=click.Choice([target.name for target in list_implemented_codegen_targets()]),
    help="Artifact target to compile after registry indexing.",
)
@click.option(
    "--out",
    "out_dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Directory for target artifacts.",
)
@click.option(
    "--registry",
    "registry_path",
    type=str,
    default=".modelable/registry.db",
    help="Path to the registry index file.",
)
@click.option(
    "--registry-ids",
    "registry_ids_path",
    type=click.Path(path_type=Path),
    default=Path("registry-ids.lock"),
    help="Path to the registry id allocation ledger (must be committed to git).",
)
@click.option(
    "--allow-orphaned-registry-ids",
    is_flag=True,
    help="Tolerate ledger entries with no matching 'registry: true' declaration instead of erroring.",
)
@click.option(
    "--domain",
    "domains",
    multiple=True,
    default=(),
    help="Restrict compilation to the named domain(s) (repeatable). Omit to compile the whole workspace.",
)
@click.option(
    "--descriptor-set",
    "descriptor_set",
    is_flag=True,
    help="For protobuf and grpc targets, compile generated .proto files into descriptor .pb artifacts.",
)
def compile(
    source: Path,
    target: str,
    out_dir: Path | None,
    registry_path: str,
    registry_ids_path: Path,
    allow_orphaned_registry_ids: bool,
    domains: tuple[str, ...],
    descriptor_set: bool,
) -> None:
    """Compile Modelable definitions and write the local registry index."""
    workspace = load_workspace_or_exit(source)

    emit_workspace = workspace
    if domains:
        known_domains = {d.name for d in workspace.mdl.domains}
        unknown_domains = sorted(set(domains) - known_domains)
        if unknown_domains:
            raise click.ClickException(
                f"Unknown --domain value(s): {', '.join(unknown_domains)}. "
                f"Available domains: {', '.join(sorted(known_domains))}"
            )
        requested = set(domains)
        violations = _find_domain_scope_violations(
            workspace.mdl,
            requested,
            resolve_semantics=target in ("protobuf", "grpc"),
        )
        if violations:
            raise click.ClickException(
                "Cannot scope compilation with --domain: the requested domain(s) have "
                "dependencies outside the requested set:\n"
                + "\n".join(f"  - {v}" for v in violations)
                + "\nAdd the missing domain(s) to --domain, or narrow the requested set."
            )
        scoped_domains = [d for d in workspace.mdl.domains if d.name in domains]
        emit_workspace = dataclasses.replace(
            workspace, mdl=workspace.mdl.model_copy(update={"domains": scoped_domains})
        )

    existing_registry_ids = read_lock_file(registry_ids_path)
    try:
        registry_ids = allocate_registry_ids(
            workspace.mdl, existing_registry_ids, allow_orphaned=allow_orphaned_registry_ids
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    write_lock_file(registry_ids_path, registry_ids)

    registry = get_registry(registry_path)
    if registry_path.startswith("oci://"):
        built_registry_path = build_registry(workspace, Path(".modelable"), registry_ids=registry_ids)
    else:
        local_registry_path = Path(registry_path)
        built_registry_path = build_registry(workspace, local_registry_path.parent, registry_ids=registry_ids)
    try:
        registry.push(built_registry_path)
    except OCIRegistryError as exc:
        raise click.ClickException(str(exc)) from exc
    console.print(f"[green]OK[/green] wrote {registry_path}")

    plans_dir = Path(".modelable/plans")
    plan_paths = write_plans(workspace, plans_dir)
    for plan_path in plan_paths:
        console.print(f"[green]OK[/green] wrote {plan_path}")

    output = out_dir or _DEFAULT_OUT_DIRS[target]
    output.mkdir(parents=True, exist_ok=True)

    if target == "json-schema":
        artifacts = emit_json_schema(emit_workspace, output)
        for art in artifacts:
            _write_artifact_text(art.path, json.dumps(art.content, indent=2, ensure_ascii=False) + "\n")
            _print_artifact_result(art)
        if not artifacts:
            console.print("[yellow]No artifacts generated.[/yellow]")
    elif target == "markdown":
        artifacts = emit_markdown(emit_workspace, output)
        for art in artifacts:
            assert isinstance(art.content, str)
            _write_artifact_text(art.path, art.content)
            _print_artifact_result(art)
        if not artifacts:
            console.print("[yellow]No artifacts generated.[/yellow]")
    elif target == "typescript":
        artifacts = emit_typescript(emit_workspace, output)
        for art in artifacts:
            assert isinstance(art.content, str)
            _write_artifact_text(art.path, art.content)
            _print_artifact_result(art)
        if not artifacts:
            console.print("[yellow]No artifacts generated.[/yellow]")
    elif target == "csharp":
        artifacts = emit_csharp(emit_workspace, output)
        for art in artifacts:
            assert isinstance(art.content, str)
            _write_artifact_text(art.path, art.content)
            _print_artifact_result(art)
        if not artifacts:
            console.print("[yellow]No artifacts generated.[/yellow]")
    elif target == "java":
        artifacts = emit_java(emit_workspace, output)
        for art in artifacts:
            assert isinstance(art.content, str)
            _write_artifact_text(art.path, art.content)
            _print_artifact_result(art)
        if not artifacts:
            console.print("[yellow]No artifacts generated.[/yellow]")
    elif target == "python":
        artifacts = emit_python(emit_workspace, output)
        for art in artifacts:
            assert isinstance(art.content, str)
            _write_artifact_text(art.path, art.content)
            _print_artifact_result(art)
        if not artifacts:
            console.print("[yellow]No artifacts generated.[/yellow]")
    elif target == "rust":
        artifacts = emit_rust(emit_workspace, output, registry_ids=registry_ids)
        for art in artifacts:
            assert isinstance(art.content, str)
            _write_artifact_text(art.path, art.content)
            _print_artifact_result(art)
        if not artifacts:
            console.print("[yellow]No artifacts generated.[/yellow]")
    elif target == "go":
        artifacts = emit_go(emit_workspace, output)
        for art in artifacts:
            assert isinstance(art.content, str)
            _write_artifact_text(art.path, art.content)
            _print_artifact_result(art)
        if not artifacts:
            console.print("[yellow]No artifacts generated.[/yellow]")
    elif target == "dbt-yaml":
        artifacts = emit_dbt_yaml(emit_workspace, output)
        for art in artifacts:
            assert isinstance(art.content, str)
            _write_artifact_text(art.path, art.content)
            _print_artifact_result(art)
        if not artifacts:
            console.print("[yellow]No artifacts generated.[/yellow]")
    elif target == "fhir-profile":
        artifacts = emit_fhir_profile(emit_workspace, output)
        for art in artifacts:
            assert isinstance(art.content, str)
            _write_artifact_text(art.path, art.content)
            _print_artifact_result(art)
        if not artifacts:
            console.print("[yellow]No artifacts generated.[/yellow]")
    elif target == "openmetadata":
        artifacts = emit_openmetadata(emit_workspace, output)
        for art in artifacts:
            content = (
                json.dumps(art.content, indent=2, ensure_ascii=False) + "\n"
                if isinstance(art.content, dict)
                else art.content
            )
            assert isinstance(content, str)
            _write_artifact_text(art.path, content)
            _print_artifact_result(art)
        if not artifacts:
            console.print("[yellow]No artifacts generated.[/yellow]")
    elif target == "openlineage":
        artifacts = emit_openlineage(emit_workspace, output)
        for art in artifacts:
            assert isinstance(art.content, dict)
            _write_artifact_text(art.path, json.dumps(art.content, indent=2, ensure_ascii=False) + "\n")
            _print_artifact_result(art)
        if not artifacts:
            console.print("[yellow]No artifacts generated.[/yellow]")
    elif target == "odcs":
        artifacts = emit_odcs(emit_workspace, output)
        for art in artifacts:
            assert isinstance(art.content, str)
            _write_artifact_text(art.path, art.content)
            _print_artifact_result(art)
        if not artifacts:
            console.print("[yellow]No artifacts generated.[/yellow]")
    elif target == "protobuf":
        artifacts = emit_protobuf(
            emit_workspace,
            output,
            registry_ids=registry_ids,
        )
        if descriptor_set:
            try:
                artifacts = _emit_protobuf_with_descriptors(artifacts, output)
            except DescriptorGenerationError as exc:
                raise click.ClickException(str(exc)) from exc
        for art in artifacts:
            _write_artifact(art)
            _print_artifact_result(art)
        if not artifacts:
            console.print("[yellow]No artifacts generated.[/yellow]")
    elif target == "grpc":
        artifacts = emit_grpc(
            emit_workspace,
            output,
            registry_ids=registry_ids,
        )
        if descriptor_set:
            try:
                artifacts = _emit_grpc_with_descriptors(artifacts, output)
            except DescriptorGenerationError as exc:
                raise click.ClickException(str(exc)) from exc
        for art in artifacts:
            _write_artifact(art)
            _print_artifact_result(art)
        if not artifacts:
            console.print("[yellow]No artifacts generated.[/yellow]")
    elif target in ("sql-postgres", "sql-clickhouse"):
        dialect = target.removeprefix("sql-")
        artifacts = emit_sql(emit_workspace, output, dialect)
        for art in artifacts:
            assert isinstance(art.content, str)
            _write_artifact_text(art.path, art.content)
            _print_artifact_result(art)
        if not artifacts:
            console.print("[yellow]No artifacts generated.[/yellow]")
    else:
        console.print(f"[yellow]{deferred_target(target)}[/yellow]")

    sys.exit(0)


@click.command()
@click.argument("source", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--out",
    "out_dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Directory for generated documentation.",
)
def docs(source: Path, out_dir: Path | None) -> None:
    """Generate Markdown documentation from Modelable definitions at SOURCE."""
    workspace = load_workspace_or_exit(source)

    output = out_dir or Path("./dist/docs")
    output.mkdir(parents=True, exist_ok=True)
    artifacts = emit_markdown(workspace, output)
    for art in artifacts:
        assert isinstance(art.content, str)
        Path(art.path).write_text(art.content, encoding="utf-8")
        _print_artifact_result(art)
    if not artifacts:
        console.print("[yellow]No artifacts generated.[/yellow]")
    sys.exit(0)


def _print_artifact_result(art: EmittedArtifact) -> None:
    for warning in art.warnings:
        console.print(f"[yellow]WARN[/yellow] {warning}")
    console.print(f"[green]OK[/green] {art.path} [dim]{art.content_hash}[/dim]")


def _write_artifact_text(path: PurePath, content: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_artifact(art: EmittedArtifact) -> None:
    path = Path(art.path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(art.content, bytes):
        path.write_bytes(art.content)
    elif isinstance(art.content, dict):
        path.write_text(json.dumps(art.content, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    else:
        path.write_text(art.content, encoding="utf-8")


def _emit_protobuf_with_descriptors(artifacts: list[EmittedArtifact], output: Path) -> list[EmittedArtifact]:
    for art in artifacts:
        if art.path.name != "schema-manifest.json":
            _write_artifact(art)

    result: list[EmittedArtifact] = []
    for art in artifacts:
        if art.path.name != "schema-manifest.json":
            result.append(art)
            continue
        assert isinstance(art.content, str)
        schema = json.loads(art.content)["schemas"][0]
        ref = str(schema["ref"])
        proto_name = art.path.parent.name + ".proto"
        proto_path = Path(art.path.parent / proto_name)
        descriptor_path = Path(art.path.parent / (art.path.parent.name + ".descriptor.pb"))
        descriptor_bytes = compile_descriptor_set(
            proto_root=output,
            proto_files=[proto_path],
            out_path=descriptor_path,
            target_ref=ref,
        )
        descriptor_artifact = EmittedArtifact(
            target=art.target,
            ref=art.ref,
            artifact_id=f"{art.artifact_id}.descriptor",
            path=descriptor_path,
            content=descriptor_bytes,
            content_hash=compute_content_hash(descriptor_bytes),
        )
        manifest_content = _with_schema_descriptor_metadata(
            art.content,
            descriptor_path=descriptor_path,
            descriptor_hash=descriptor_artifact.content_hash,
        )
        manifest_artifact = EmittedArtifact(
            target=art.target,
            ref=art.ref,
            artifact_id=art.artifact_id,
            path=art.path,
            content=manifest_content,
            content_hash=compute_content_hash(manifest_content),
            warnings=art.warnings,
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


def _emit_grpc_with_descriptors(artifacts: list[EmittedArtifact], output: Path) -> list[EmittedArtifact]:
    for art in artifacts:
        if art.path.name != "service-manifest.json":
            _write_artifact(art)

    result: list[EmittedArtifact] = []
    for art in artifacts:
        if art.path.name != "service-manifest.json":
            result.append(art)
            continue
        assert isinstance(art.content, str)
        manifest = json.loads(art.content)
        ref = str(manifest["ref"])
        service_proto = Path(art.path.parent / str(manifest["service_proto"]))
        payload_proto = Path(art.path.parent / (art.path.parent.name + ".proto"))
        descriptor_path = Path(art.path.parent / (art.path.parent.name + ".grpc.descriptor.pb"))
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
            target=art.target,
            ref=art.ref,
            artifact_id=f"{art.artifact_id}.descriptor",
            path=descriptor_path,
            content=descriptor_bytes,
            content_hash=compute_content_hash(descriptor_bytes),
        )
        manifest_content = _with_service_descriptor_metadata(
            art.content,
            descriptor_path=descriptor_path,
            descriptor_hash=descriptor_artifact.content_hash,
        )
        manifest_artifact = EmittedArtifact(
            target=art.target,
            ref=art.ref,
            artifact_id=art.artifact_id,
            path=art.path,
            content=manifest_content,
            content_hash=compute_content_hash(manifest_content),
            warnings=art.warnings,
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
