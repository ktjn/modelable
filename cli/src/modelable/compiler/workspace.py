from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from modelable.diagnostics.model import Diagnostic
from modelable.expressions.cel import CelContext, FieldRef, looks_boolean, parse_cel, validate_cel_expr
from modelable.parser.ir import (
    ArrayType,
    ComputedMapping,
    MapType,
    MdlFile,
    NamedType,
    ObjectType,
    ProjectionVersion,
)
from modelable.parser.parse import parse_text_to_ir_with_tree
from modelable.planner.planner import expand_auto_projections, expand_projection_selections
from modelable.registry.resolver import resolve_model_ref, resolve_semantic_type_ref, validate_references
from modelable.validation.deferred_syntax import find_deferred_syntax_diagnostics
from modelable.validation.semantic import validate_diagnostics, validate_ref_type_field


@dataclass(frozen=True)
class WorkspaceSource:
    path: Path | None
    uri: str
    text: str
    mdl: MdlFile
    errors: list[Diagnostic]
    content_hash: str
    warnings: list[Diagnostic] = field(default_factory=list)


@dataclass(frozen=True)
class Workspace:
    sources: list[WorkspaceSource]
    mdl: MdlFile
    errors: list[Diagnostic]
    warnings: list[Diagnostic] = field(default_factory=list)


@dataclass(frozen=True)
class WorkspaceDocumentSource:
    path: Path | None
    uri: str
    text: str


def discover_mdl_files(path: str | Path) -> list[Path]:
    """Return .mdl files from a file or directory in deterministic order."""
    root = Path(path)
    if root.is_file():
        if root.suffix != ".mdl":
            raise FileNotFoundError(f"{root} is not a .mdl file")
        return [root]

    files = sorted(root.rglob("*.mdl"), key=lambda item: item.as_posix())
    if not files:
        raise FileNotFoundError(f"No .mdl files found under {root}")
    return files


def load_workspace(path: str | Path) -> Workspace:
    """Parse and validate all local .mdl files under path."""
    sources = [
        WorkspaceDocumentSource(
            path=mdl_path,
            uri=mdl_path.resolve().as_uri(),
            text=mdl_path.read_text(encoding="utf-8"),
        )
        for mdl_path in discover_mdl_files(path)
    ]
    return load_workspace_from_sources(sources)


def load_workspace_from_sources(sources: list[WorkspaceDocumentSource]) -> Workspace:
    workspace_sources: list[WorkspaceSource] = []
    errors: list[Diagnostic] = []
    warnings: list[Diagnostic] = []
    merged = MdlFile()

    for source in sources:
        source_location = str(source.path) if source.path is not None else source.uri
        mdl, tree = parse_text_to_ir_with_tree(source.text, path=source_location)
        source_errors = validate_diagnostics(mdl, path=source_location)
        source_warnings = find_deferred_syntax_diagnostics(tree, path=source_location)
        workspace_sources.append(
            WorkspaceSource(
                path=source.path,
                uri=source.uri,
                text=source.text,
                mdl=mdl,
                errors=source_errors,
                content_hash=_content_hash(source.text),
                warnings=source_warnings,
            )
        )
        errors.extend(source_errors)
        warnings.extend(source_warnings)
        merged.domains.extend(mdl.domains)
        _merge_bindings(merged.bindings, mdl.bindings)
        if mdl.workspace is not None:
            merged.workspace = mdl.workspace

    auto_projection_errors = expand_auto_projections(merged)
    errors.extend(
        Diagnostic(code="SEM", message=error, severity="error", path="<workspace>") for error in auto_projection_errors
    )
    errors.extend(_validate_api_bindings(merged))

    selection_errors = expand_projection_selections(merged)
    errors.extend(
        Diagnostic(code="SEM", message=error, severity="error", path="<workspace>") for error in selection_errors
    )

    errors.extend(_validate_package_config(merged))
    errors.extend(_validate_merged_workspace(workspace_sources, merged))
    errors.extend(_validate_named_field_types(merged))
    ref_errors, ref_warnings = _validate_ref_types_in_merged_workspace(workspace_sources, merged)
    errors.extend(ref_errors)
    warnings.extend(ref_warnings)
    errors.extend(_validate_cel(merged))
    return Workspace(sources=workspace_sources, mdl=merged, errors=errors, warnings=warnings)


def _validate_api_bindings(mdl: MdlFile) -> list[Diagnostic]:
    errors: list[Diagnostic] = []
    for domain in mdl.domains:
        for api in domain.apis:
            for operation in api.operations:
                operation_fqn = f"{domain.name}.{api.model}@{api.version} operation '{operation.name}'"
                if operation.request is not None:
                    _validate_api_projection_ref(
                        domain.name, operation_fqn, operation.request, domain.projections, "request", errors
                    )
                for response in operation.responses:
                    _validate_api_projection_ref(
                        domain.name,
                        operation_fqn,
                        (response.projection, response.version),
                        domain.projections,
                        "response",
                        errors,
                    )
    return errors


def _validate_api_projection_ref(
    domain_name: str,
    operation_fqn: str,
    reference: tuple[str, int],
    projections: dict[str, list[ProjectionVersion]],
    binding_kind: str,
    errors: list[Diagnostic],
) -> None:
    projection_name, version = reference
    versions = projections.get(projection_name)
    projection = next((item for item in versions or [] if item.version == version), None)
    if projection is None:
        errors.append(
            Diagnostic(
                code="SEM",
                message=(
                    f"{operation_fqn}: {binding_kind} projection "
                    f"{domain_name}.{projection_name}@{version} does not exist"
                ),
                severity="error",
                path="<workspace>",
            )
        )
        return
    if binding_kind == "request" and projection_name.endswith("Reply"):
        errors.append(
            Diagnostic(
                code="SEM",
                message=f"{operation_fqn}: request binding cannot use reply projection '{projection_name}'",
                severity="error",
                path="<workspace>",
            )
        )
    if binding_kind == "response" and projection_name.endswith("Request"):
        errors.append(
            Diagnostic(
                code="SEM",
                message=f"{operation_fqn}: response binding cannot use request projection '{projection_name}'",
                severity="error",
                path="<workspace>",
            )
        )


_PACKAGE_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")


def _validate_package_config(merged: MdlFile) -> list[Diagnostic]:
    """Validate package {} blocks: safe names, no duplicates, and every domain
    assigned to exactly one package (a full partition, not just "at most one").

    Dependency cycle detection happens separately in package_graph.py, since it
    needs inter-package edges computed from NamedType refs, not just includes.
    """
    if merged.workspace is None or not merged.workspace.packages:
        return []
    errors: list[Diagnostic] = []
    known_domains = {domain.name for domain in merged.domains}

    seen_package_names: dict[str, bool] = {}
    for pkg in merged.workspace.packages:
        if not _PACKAGE_NAME_RE.fullmatch(pkg.name):
            errors.append(
                Diagnostic(
                    code="SEM",
                    message=(
                        f"invalid package name '{pkg.name}': must start with a letter and contain only "
                        "letters, digits, '-', or '_' (this becomes a directory name under --out)"
                    ),
                    severity="error",
                    path="<workspace>",
                )
            )
        elif pkg.name in seen_package_names:
            errors.append(
                Diagnostic(
                    code="SEM",
                    message=f"duplicate package name '{pkg.name}'",
                    severity="error",
                    path="<workspace>",
                )
            )
        else:
            seen_package_names[pkg.name] = True

    domain_package: dict[str, str] = {}
    for pkg in merged.workspace.packages:
        for domain_name in pkg.include:
            if domain_name not in known_domains:
                errors.append(
                    Diagnostic(
                        code="SEM",
                        message=f"package '{pkg.name}' includes unknown domain '{domain_name}'",
                        severity="error",
                        path="<workspace>",
                    )
                )
                continue
            previous_package = domain_package.get(domain_name)
            if previous_package is not None:
                errors.append(
                    Diagnostic(
                        code="SEM",
                        message=(
                            f"domain '{domain_name}' assigned to multiple packages "
                            f"('{previous_package}' and '{pkg.name}')"
                        ),
                        severity="error",
                        path="<workspace>",
                    )
                )
            else:
                domain_package[domain_name] = pkg.name

    unassigned = sorted(known_domains - domain_package.keys())
    if unassigned:
        errors.append(
            Diagnostic(
                code="SEM",
                message=(
                    "domain(s) not assigned to any package: "
                    f"{', '.join(unassigned)} (every domain must belong to exactly one package "
                    "once any package {} block is declared)"
                ),
                severity="error",
                path="<workspace>",
            )
        )
    return errors


def _validate_merged_workspace(sources: list[WorkspaceSource], merged: MdlFile) -> list[Diagnostic]:
    errors: list[Diagnostic] = []
    domains: dict[str, str] = {}
    model_versions: dict[tuple[str, str, int], str] = {}
    projection_versions: dict[tuple[str, str, int], str] = {}
    generated_projection_versions: dict[tuple[str, str, int], str] = {}

    for source in sources:
        source_location = str(source.path) if source.path is not None else source.uri
        for domain in source.mdl.domains:
            previous_domain_path = domains.get(domain.name)
            if previous_domain_path is not None:
                errors.append(
                    Diagnostic(
                        code="SEM",
                        message=(f"duplicate domain '{domain.name}' also defined in {previous_domain_path}"),
                        severity="error",
                        path=source_location,
                    )
                )
            else:
                domains[domain.name] = source_location

            for model_name, model_versions_list in domain.models.items():
                for model_version in model_versions_list:
                    key = (domain.name, model_name, model_version.version)
                    previous_model_path = model_versions.get(key)
                    if previous_model_path is not None:
                        errors.append(
                            Diagnostic(
                                code="SEM",
                                message=(
                                    "duplicate model version "
                                    f"{domain.name}.{model_name}@{model_version.version} "
                                    f"also defined in {previous_model_path}"
                                ),
                                severity="error",
                                path=source_location,
                            )
                        )
                    else:
                        model_versions[key] = source_location

            for projection_name, projection_versions_list in domain.projections.items():
                for projection_version in projection_versions_list:
                    # Skip auto-generated projections when checking for explicit
                    # projection conflicts — they are validated separately.
                    if projection_version.auto_generated:
                        continue
                    key = (domain.name, projection_name, projection_version.version)
                    previous_projection_path = projection_versions.get(key)
                    if previous_projection_path is not None:
                        errors.append(
                            Diagnostic(
                                code="SEM",
                                message=(
                                    "duplicate projection version "
                                    f"{domain.name}.{projection_name}@{projection_version.version} "
                                    f"also defined in {previous_projection_path}"
                                ),
                                severity="error",
                                path=source_location,
                            )
                        )
                    else:
                        projection_versions[key] = source_location

            for auto_projection in domain.auto_projections:
                for target in auto_projection.targets:
                    projection_name = _generated_projection_name(auto_projection.model, target.kind)
                    key = (domain.name, projection_name, auto_projection.version)

                    previous_generated_path = generated_projection_versions.get(key)
                    if previous_generated_path is not None:
                        errors.append(
                            Diagnostic(
                                code="SEM",
                                message=(
                                    "generated projection name "
                                    f"{domain.name}.{projection_name}@{auto_projection.version} "
                                    f"conflicts with auto projection declared in "
                                    f"{previous_generated_path}"
                                ),
                                severity="error",
                                path=source_location,
                            )
                        )
                    else:
                        generated_projection_versions[key] = source_location

                    explicit_projection_path = projection_versions.get(key)
                    if explicit_projection_path is not None:
                        errors.append(
                            Diagnostic(
                                code="SEM",
                                message=(
                                    "generated projection name "
                                    f"{domain.name}.{projection_name}@{auto_projection.version} "
                                    f"conflicts with explicit projection declared in "
                                    f"{explicit_projection_path}"
                                ),
                                severity="error",
                                path=source_location,
                            )
                        )

    errors.extend(
        Diagnostic(code="SEM", message=error, severity="error", path="<workspace>")
        for error in validate_references(merged)
    )
    errors.extend(_validate_bindings(merged))
    return errors


def _validate_ref_types_in_merged_workspace(
    sources: list[WorkspaceSource],
    merged: MdlFile,
) -> tuple[list[Diagnostic], list[Diagnostic]]:
    """Validate every ref<> field across all sources against the fully
    merged workspace — see validate_ref_type_field's docstring for why this
    can't happen per-source-file."""
    errors: list[Diagnostic] = []
    warnings: list[Diagnostic] = []
    for source in sources:
        source_location = str(source.path) if source.path is not None else source.uri
        for domain in source.mdl.domains:
            for model_name, versions in domain.models.items():
                fqn = f"{domain.name}.{model_name}"
                for version in versions:
                    for model_field in version.fields:
                        validate_ref_type_field(
                            f"{fqn}@{version.version}", model_field, merged, errors, warnings, source_location
                        )
    return errors, warnings


def _validate_named_field_types(merged: MdlFile) -> list[Diagnostic]:
    """Reject bare semantic field types that cannot be resolved unambiguously."""
    model_names = {model_name for domain in merged.domains for model_name in domain.models}
    opaque_names = {"bytes"}
    errors: list[Diagnostic] = []

    def visit(field_type, domain_name: str, context: str) -> None:
        if isinstance(field_type, NamedType):
            if field_type.name in model_names or field_type.name in opaque_names:
                return
            try:
                resolve_semantic_type_ref(merged, domain_name, field_type.name)
            except LookupError as exc:
                message = str(exc).replace("ambiguous semantic type", "ambiguous type", 1)
                errors.append(
                    Diagnostic(code="SEM", message=f"{context}: {message}", severity="error", path="<workspace>")
                )
        elif isinstance(field_type, ArrayType):
            visit(field_type.item, domain_name, context)
        elif isinstance(field_type, MapType):
            visit(field_type.value, domain_name, context)
        elif isinstance(field_type, ObjectType):
            for nested in field_type.fields:
                visit(nested.type, domain_name, f"{context}.{nested.name}")

    for domain in merged.domains:
        for model_name, versions in domain.models.items():
            for version in versions:
                for model_field in version.fields:
                    visit(
                        model_field.type,
                        domain.name,
                        f"{domain.name}.{model_name}@{version.version}.{model_field.name}",
                    )
    return errors


def _merge_bindings(existing: list, incoming: list) -> None:
    """Merge incoming bindings into existing, deduplicating identical definitions.

    Two bindings are considered identical if they share the same name, adapter,
    model, model_version, and table. Identical duplicates are silently dropped.
    Conflicting duplicates (same name, different adapter) are kept so that
    _validate_bindings can report them.
    """
    seen: set[tuple] = {(b.name, b.adapter, b.model, b.model_version, b.table) for b in existing}
    for b in incoming:
        key = (b.name, b.adapter, b.model, b.model_version, b.table)
        if key not in seen:
            existing.append(b)
            seen.add(key)


def _validate_bindings(merged: MdlFile) -> list[Diagnostic]:
    """Detect binding names that appear with conflicting definitions."""
    errors: list[Diagnostic] = []
    seen: dict[str, str] = {}  # name → adapter
    for b in merged.bindings:
        if b.name in seen:
            if seen[b.name] != b.adapter:
                errors.append(
                    Diagnostic(
                        code="SEM",
                        message=(
                            f"binding '{b.name}' is declared with conflicting adapter "
                            f"'{b.adapter}' (previously '{seen[b.name]}')"
                        ),
                        severity="error",
                        path="<workspace>",
                    )
                )
        else:
            seen[b.name] = b.adapter
    return errors


def _validate_cel(merged: MdlFile) -> list[Diagnostic]:
    """Validate CEL expressions in all projections across the merged workspace."""
    errors: list[Diagnostic] = []

    for domain in merged.domains:
        for projection_name, versions in domain.projections.items():
            for pv in versions:
                fqn = f"{domain.name}.{projection_name}@{pv.version}"

                # Build alias -> set[field_name] from source and all joins
                source_fields: dict[str, set[str]] = {}
                source_types: dict[str, dict[str, str]] = {}
                all_sources = [(pv.source.model, pv.source.version, pv.source.alias)]
                for join in pv.joins:
                    all_sources.append((join.model, join.version, join.alias))
                for model_ref, version_spec, alias in all_sources:
                    try:
                        resolved = resolve_model_ref(merged, model_ref, version_spec)
                        source_fields[alias] = {f.name for f in resolved.version.fields}
                        source_types[alias] = {
                            f.name: getattr(getattr(f, "type", None), "kind", "unknown")
                            for f in resolved.version.fields
                        }
                    except LookupError:
                        pass

                ctx = CelContext(
                    source_fields=source_fields,
                    has_group_by=bool(pv.group_by),
                    fqn=fqn,
                    source_types=source_types,
                )

                if pv.where:
                    ast, parse_errors = parse_cel(pv.where)
                    for err in parse_errors:
                        errors.append(
                            Diagnostic(
                                code="CEL",
                                message=f"{fqn} where: {err}",
                                severity="error",
                                path="<workspace>",
                            )
                        )
                    if ast is not None:
                        result = validate_cel_expr(ast, ctx)
                        for err in result.errors:
                            errors.append(
                                Diagnostic(
                                    code="CEL",
                                    message=f"{fqn} where: {err}",
                                    severity="error",
                                    path="<workspace>",
                                )
                            )
                        if not looks_boolean(ast):
                            errors.append(
                                Diagnostic(
                                    code="CEL",
                                    message=f"{fqn} where: CEL008: expression must be a boolean predicate",
                                    severity="error",
                                    path="<workspace>",
                                )
                            )

                if pv.group_by:
                    own_field_names = {field.name for field in pv.fields}
                    group_ctx = CelContext(source_fields=source_fields, has_group_by=False, fqn=fqn)
                    for group_expr in pv.group_by:
                        ast, parse_errors = parse_cel(group_expr)
                        for err in parse_errors:
                            errors.append(
                                Diagnostic(
                                    code="CEL",
                                    message=f"{fqn} group by: {err}",
                                    severity="error",
                                    path="<workspace>",
                                )
                            )
                        if ast is None:
                            continue
                        # SQL-style GROUP BY on a SELECT-list alias: a bare name matching
                        # one of this projection's own fields refers to that field, not a
                        # source alias.field reference — skip source-field validation for it.
                        if isinstance(ast, FieldRef) and ast.alias == "" and ast.field in own_field_names:
                            continue
                        result = validate_cel_expr(ast, group_ctx)
                        for err in result.errors:
                            errors.append(
                                Diagnostic(
                                    code="CEL",
                                    message=f"{fqn} group by: {err}",
                                    severity="error",
                                    path="<workspace>",
                                )
                            )

                for proj_field in pv.fields:
                    if not isinstance(proj_field.mapping, ComputedMapping):
                        continue
                    expression = proj_field.mapping.expression
                    ast, parse_errors = parse_cel(expression)
                    for err in parse_errors:
                        errors.append(
                            Diagnostic(
                                code="CEL",
                                message=f"{fqn}.{proj_field.name}: {err}",
                                severity="error",
                                path="<workspace>",
                            )
                        )
                    if ast is not None:
                        result = validate_cel_expr(ast, ctx)
                        for err in result.errors:
                            errors.append(
                                Diagnostic(
                                    code="CEL",
                                    message=f"{proj_field.name}: {err}",
                                    severity="error",
                                    path="<workspace>",
                                )
                            )

                for join in pv.joins:
                    if not join.on:
                        continue
                    ast, parse_errors = parse_cel(join.on)
                    for err in parse_errors:
                        errors.append(
                            Diagnostic(
                                code="CEL",
                                message=f"{fqn} join on: {err}",
                                severity="error",
                                path="<workspace>",
                            )
                        )
                    if ast is not None:
                        result = validate_cel_expr(ast, ctx)
                        for err in result.errors:
                            errors.append(
                                Diagnostic(
                                    code="CEL",
                                    message=f"{fqn} join on: {err}",
                                    severity="error",
                                    path="<workspace>",
                                )
                            )
                        if not looks_boolean(ast):
                            errors.append(
                                Diagnostic(
                                    code="CEL",
                                    message=f"{fqn} join on: CEL008: expression must be a boolean predicate",
                                    severity="error",
                                    path="<workspace>",
                                )
                            )

    return errors


def _generated_projection_name(model_name: str, kind: str) -> str:
    suffixes = {
        "db": "Db",
        "request": "Request",
        "reply": "Reply",
        "event": "Event",
    }
    return f"{model_name}{suffixes[kind]}"


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
