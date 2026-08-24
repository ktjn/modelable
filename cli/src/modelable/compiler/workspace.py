from __future__ import annotations

import copy
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from modelable.config import ModelableConfig, apply_config_defaults, load_config
from modelable.diagnostics.model import Diagnostic
from modelable.expressions.cel import CelContext, FieldRef, looks_boolean, parse_cel, validate_cel_expr
from modelable.parser.ir import (
    AddFieldOp,
    ArrayType,
    BindingDef,
    ComputedMapping,
    EnumRefType,
    EnumType,
    FieldProvenance,
    FieldType,
    MapType,
    MdlFile,
    ModelVersion,
    NamedType,
    ObjectType,
    ProjectionVersion,
    RemoveFieldOp,
    RenameFieldOp,
    ReplaceFieldOp,
    UnionType,
)
from modelable.parser.parse import parse_text_to_ir_with_tree
from modelable.planner.planner import expand_auto_projections, expand_projection_selections
from modelable.registry.resolver import resolve_model_ref, resolve_semantic_type_ref, validate_references
from modelable.validation.deferred_syntax import find_deferred_syntax_diagnostics
from modelable.validation.semantic import (
    _validate_change_kind,
    _validate_models,
    validate_diagnostics,
    validate_ref_type_field,
)


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
    return load_workspace_from_sources(sources, config=load_config(path))


def load_workspace_from_sources(
    sources: list[WorkspaceDocumentSource], *, config: ModelableConfig | None = None
) -> Workspace:
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

    errors.extend(_expand_model_evolutions(merged))

    if config is not None:
        try:
            apply_config_defaults(merged, config)
        except ValueError as exc:
            errors.append(Diagnostic(code="CONFIG", message=str(exc), severity="error", path="modelable.toml"))

    auto_projection_errors = expand_auto_projections(merged)
    errors.extend(
        Diagnostic(code="SEM", message=error, severity="error", path="<workspace>") for error in auto_projection_errors
    )
    enum_projection_errors, enum_projection_warnings = _expand_enum_projections(merged)
    errors.extend(enum_projection_errors)
    warnings.extend(enum_projection_warnings)
    errors.extend(_validate_api_bindings(merged))

    selection_errors = expand_projection_selections(merged)
    errors.extend(
        Diagnostic(code="SEM", message=error, severity="error", path="<workspace>") for error in selection_errors
    )

    errors.extend(_validate_package_config(merged))
    errors.extend(_validate_merged_workspace(workspace_sources, merged))
    named_errors, named_warnings = _validate_named_field_types(merged)
    errors.extend(named_errors)
    warnings.extend(named_warnings)
    ref_errors, ref_warnings = _validate_ref_types_in_merged_workspace(workspace_sources, merged)
    errors.extend(ref_errors)
    warnings.extend(ref_warnings)
    warnings.extend(_validate_postcard_bindings(merged))
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


def _validate_named_field_types(merged: MdlFile) -> tuple[list[Diagnostic], list[Diagnostic]]:
    """Reject bare semantic field types that cannot be resolved unambiguously.

    Exact versioned enum references (``EnumRefType``) resolve to exactly the
    requested declaration version — a later version never re-resolves an
    earlier published consumer. Bare references that resolve to an enum-backed
    semantic type are accepted as an authoring form but produce a non-blocking
    ``ENUMREF`` warning naming the resolved version, mirroring the unversioned
    ``ref<>`` policy (evolution plan E2).
    """
    model_names = {model_name for domain in merged.domains for model_name in domain.models}
    opaque_names = {"bytes"}
    errors: list[Diagnostic] = []
    warnings: list[Diagnostic] = []

    def visit(field_type: FieldType, domain_name: str, context: str) -> None:
        if isinstance(field_type, NamedType):
            if field_type.name in model_names or field_type.name in opaque_names:
                return
            try:
                _declaring_domain, decl = resolve_semantic_type_ref(merged, domain_name, field_type.name)
            except LookupError as exc:
                message = str(exc).replace("ambiguous semantic type", "ambiguous type", 1)
                errors.append(
                    Diagnostic(code="SEM", message=f"{context}: {message}", severity="error", path="<workspace>")
                )
                return
            if isinstance(decl.underlying, EnumType):
                warnings.append(
                    Diagnostic(
                        code="ENUMREF",
                        message=(
                            f"{context}: semantic enum reference '{field_type.name}' resolves to "
                            f"{_declaring_domain}.{field_type.name}@{decl.version}; declare an exact "
                            f"version ('{field_type.name} @ {decl.version}') before publishing"
                        ),
                        severity="warning",
                        path="<workspace>",
                    )
                )
        elif isinstance(field_type, EnumRefType):
            try:
                _declaring_domain, decl = resolve_semantic_type_ref(
                    merged, domain_name, field_type.name, exact_version=field_type.version
                )
            except LookupError as exc:
                message = str(exc).replace("ambiguous semantic type", "ambiguous enum type", 1)
                errors.append(
                    Diagnostic(code="ENUMREF", message=f"{context}: {message}", severity="error", path="<workspace>")
                )
                return
            if not isinstance(decl.underlying, EnumType):
                errors.append(
                    Diagnostic(
                        code="ENUMREF",
                        message=(
                            f"{context}: exact enum reference '{field_type.name} @ {field_type.version}' "
                            "must target an enum-backed semantic type"
                        ),
                        severity="error",
                        path="<workspace>",
                    )
                )
        elif isinstance(field_type, ArrayType):
            visit(field_type.item, domain_name, context)
        elif isinstance(field_type, MapType):
            visit(field_type.value, domain_name, context)
        elif isinstance(field_type, ObjectType):
            for nested in field_type.fields:
                visit(nested.type, domain_name, f"{context}.{nested.name}")
        elif isinstance(field_type, UnionType):
            for variant in field_type.variants:
                visit(variant.type, domain_name, f"{context}.{variant.tag}")

    for domain in merged.domains:
        for model_name, versions in domain.models.items():
            for version in versions:
                for model_field in version.fields:
                    visit(
                        model_field.type,
                        domain.name,
                        f"{domain.name}.{model_name}@{version.version}.{model_field.name}",
                    )
    return errors, warnings


def _expand_model_evolutions(merged: MdlFile) -> list[Diagnostic]:
    """Resolve `evolves @ N` model versions into complete `ModelVersion`
    objects before anything else sees them.

    Add-only for now (evolution plan D1): the base version must be the
    highest existing version of the same model/kind below the new version --
    no first-version, missing-base, wrong-kind, forward, or branching
    histories. The result is a deep copy of the base's fields with `add`
    operations appended in order, appended to `domain.models` exactly as a
    hand-written complete version would be, so nothing downstream (semantic
    validation, compatibility, projections, emitters, registry) needs to
    know an evolution object ever existed.
    """
    errors: list[Diagnostic] = []
    for domain in merged.domains:
        for evolution in domain.model_evolutions:
            context = f"{domain.name}.{evolution.name}@{evolution.version}"
            existing_versions = domain.models.get(evolution.name, [])
            if any(version.version == evolution.version for version in existing_versions):
                errors.append(
                    Diagnostic(
                        code="SEM",
                        message=f"{context}: version is already declared",
                        severity="error",
                        path="<workspace>",
                    )
                )
                continue
            if not existing_versions:
                errors.append(
                    Diagnostic(
                        code="SEM",
                        message=f"{context}: evolves has no prior version of '{evolution.name}' to evolve from",
                        severity="error",
                        path="<workspace>",
                    )
                )
                continue

            lower_versions = [version for version in existing_versions if version.version < evolution.version]
            highest_lower = max(lower_versions, key=lambda version: version.version, default=None)
            if highest_lower is None:
                errors.append(
                    Diagnostic(
                        code="SEM",
                        message=(
                            f"{context}: evolves @ {evolution.base_version} is not before version {evolution.version}"
                        ),
                        severity="error",
                        path="<workspace>",
                    )
                )
                continue
            if highest_lower.version != evolution.base_version:
                errors.append(
                    Diagnostic(
                        code="SEM",
                        message=(
                            f"{context}: evolves @ {evolution.base_version} is not the highest version of "
                            f"'{evolution.name}' below {evolution.version} (that is @ {highest_lower.version}); "
                            "evolution cannot branch from a superseded version"
                        ),
                        severity="error",
                        path="<workspace>",
                    )
                )
                continue
            if highest_lower.model_kind != evolution.model_kind:
                errors.append(
                    Diagnostic(
                        code="SEM",
                        message=(
                            f"{context}: evolves @ {evolution.base_version} is a "
                            f"{highest_lower.model_kind.value}, but this declaration is "
                            f"{evolution.model_kind.value}"
                        ),
                        severity="error",
                        path="<workspace>",
                    )
                )
                continue

            new_fields = copy.deepcopy(highest_lower.fields)
            provenance = [FieldProvenance(field_name=f.name, origin="inherited") for f in new_fields]
            operation_failed = False
            for operation in evolution.operations:
                if isinstance(operation, AddFieldOp):
                    if any(f.name == operation.field.name for f in new_fields):
                        errors.append(
                            Diagnostic(
                                code="SEM",
                                message=f"{context}: add declares duplicate field '{operation.field.name}'",
                                severity="error",
                                path="<workspace>",
                            )
                        )
                        operation_failed = True
                        break
                    new_fields.append(copy.deepcopy(operation.field))
                    provenance.append(FieldProvenance(field_name=operation.field.name, origin="add"))
                elif isinstance(operation, RemoveFieldOp):
                    index = next((i for i, f in enumerate(new_fields) if f.name == operation.field_name), None)
                    if index is None:
                        errors.append(
                            Diagnostic(
                                code="SEM",
                                message=f"{context}: remove references unknown field '{operation.field_name}'",
                                severity="error",
                                path="<workspace>",
                            )
                        )
                        operation_failed = True
                        break
                    del new_fields[index]
                    del provenance[index]
                elif isinstance(operation, RenameFieldOp):
                    index = next((i for i, f in enumerate(new_fields) if f.name == operation.old_name), None)
                    if index is None:
                        errors.append(
                            Diagnostic(
                                code="SEM",
                                message=f"{context}: rename references unknown field '{operation.old_name}'",
                                severity="error",
                                path="<workspace>",
                            )
                        )
                        operation_failed = True
                        break
                    if operation.new_name != operation.old_name and any(
                        f.name == operation.new_name for f in new_fields
                    ):
                        errors.append(
                            Diagnostic(
                                code="SEM",
                                message=(
                                    f"{context}: rename target '{operation.new_name}' is already occupied by "
                                    "another field"
                                ),
                                severity="error",
                                path="<workspace>",
                            )
                        )
                        operation_failed = True
                        break
                    new_fields[index] = new_fields[index].model_copy(update={"name": operation.new_name})
                    provenance[index] = FieldProvenance(
                        field_name=operation.new_name, origin="rename", renamed_from=operation.old_name
                    )
                else:
                    assert isinstance(operation, ReplaceFieldOp)
                    index = next((i for i, f in enumerate(new_fields) if f.name == operation.field.name), None)
                    if index is None:
                        errors.append(
                            Diagnostic(
                                code="SEM",
                                message=(
                                    f"{context}: replace field '{operation.field.name}' does not match any "
                                    "existing field"
                                ),
                                severity="error",
                                path="<workspace>",
                            )
                        )
                        operation_failed = True
                        break
                    new_fields[index] = copy.deepcopy(operation.field)
                    provenance[index] = FieldProvenance(field_name=operation.field.name, origin="replace")
            if operation_failed:
                continue

            expanded = ModelVersion(
                model_kind=evolution.model_kind,
                version=evolution.version,
                change_kind=evolution.change_kind,
                fields=new_fields,
                has_version_header=True,
                has_change_kind=evolution.has_change_kind,
                provenance=provenance,
            )
            _validate_models(domain.name, {evolution.name: [expanded]}, errors, "<workspace>")
            _validate_change_kind(f"{domain.name}.{evolution.name}", highest_lower, expanded, errors, "<workspace>")
            domain.models.setdefault(evolution.name, []).append(expanded)
    return errors


def _expand_enum_projections(merged: MdlFile) -> tuple[list[Diagnostic], list[Diagnostic]]:
    """Resolve enum-projection sources exactly and normalize their member sets.

    Both pick(...) and omit(...) normalize into the exact resulting member
    identities of the exact referenced source version; the authored form is
    retained on the declaration only for rendering and diagnostics (evolution
    plan E3).
    """
    errors: list[Diagnostic] = []
    warnings: list[Diagnostic] = []
    for domain in merged.domains:
        seen: dict[tuple[str, int], int] = {}
        for projection in domain.enum_projections:
            context = f"{domain.name}.{projection.name}@{projection.version}"
            if seen.get((projection.name, projection.version)):
                errors.append(
                    Diagnostic(
                        code="SEM",
                        message=f"{context}: enum projection is declared more than once",
                        severity="error",
                        path="<workspace>",
                    )
                )
            seen[(projection.name, projection.version)] = 1
            if projection.name in domain.models:
                errors.append(
                    Diagnostic(
                        code="SEM",
                        message=f"{domain.name}: enum projection '{projection.name}' collides with a model of the same name",
                        severity="error",
                        path="<workspace>",
                    )
                )
            if projection.name in domain.projections:
                errors.append(
                    Diagnostic(
                        code="SEM",
                        message=(
                            f"{domain.name}: enum projection '{projection.name}' collides with a "
                            "projection of the same name"
                        ),
                        severity="error",
                        path="<workspace>",
                    )
                )
            if any(item.name == projection.name for item in domain.semantic_types):
                errors.append(
                    Diagnostic(
                        code="ENUMPROJ",
                        message=(
                            f"{domain.name}: enum projection '{projection.name}' collides with a semantic "
                            "type of the same name in the shared nominal enum namespace"
                        ),
                        severity="error",
                        path="<workspace>",
                    )
                )

            try:
                _declaring_domain, source = resolve_semantic_type_ref(
                    merged, domain.name, projection.source_name, exact_version=projection.source_version
                )
            except LookupError as exc:
                message = str(exc).replace("ambiguous semantic type", "ambiguous enum type", 1)
                errors.append(
                    Diagnostic(code="ENUMPROJ", message=f"{context}: {message}", severity="error", path="<workspace>")
                )
                continue
            if not isinstance(source.underlying, EnumType):
                errors.append(
                    Diagnostic(
                        code="ENUMPROJ",
                        message=(
                            f"{context}: enum projection source "
                            f"'{projection.source_name} @ {projection.source_version}' must be an "
                            "enum-backed semantic type"
                        ),
                        severity="error",
                        path="<workspace>",
                    )
                )
                continue

            source_values = list(source.underlying.values)
            repeated = sorted({member for member in projection.selected if projection.selected.count(member) > 1})
            if repeated:
                errors.append(
                    Diagnostic(
                        code="ENUMPROJ",
                        message=(
                            f"{context}: {projection.selection_kind} lists member(s) more than once: "
                            + ", ".join(repeated)
                        ),
                        severity="error",
                        path="<workspace>",
                    )
                )
                continue
            unknown = sorted(set(projection.selected) - set(source_values))
            if unknown:
                errors.append(
                    Diagnostic(
                        code="ENUMPROJ",
                        message=(
                            f"{context}: {projection.selection_kind} references member(s) missing from "
                            f"source '{projection.source_name} @ {projection.source_version}': " + ", ".join(unknown)
                        ),
                        severity="error",
                        path="<workspace>",
                    )
                )
                continue

            if projection.selection_kind == "pick":
                # Ordered-independent subset of exact source-member identities.
                members = sorted(set(projection.selected))
            else:
                members = sorted(value for value in source_values if value not in set(projection.selected))
            if not members:
                errors.append(
                    Diagnostic(
                        code="ENUMPROJ",
                        message=f"{context}: enum projection would have an empty member set",
                        severity="error",
                        path="<workspace>",
                    )
                )
                continue
            if projection.has_version_header and projection.version < 1:
                errors.append(
                    Diagnostic(
                        code="SEM",
                        message=f"{context}: enum projection version must be positive",
                        severity="error",
                        path="<workspace>",
                    )
                )
                continue
            projection.members = members
    return errors, warnings


def _merge_bindings(existing: list[BindingDef], incoming: list[BindingDef]) -> None:
    """Merge incoming bindings into existing, deduplicating identical definitions.

    Two bindings are considered identical if they share the same name, adapter,
    model, model_version, and table. Identical duplicates are silently dropped.
    Conflicting duplicates (same name, different adapter) are kept so that
    _validate_bindings can report them.
    """
    seen: set[tuple[str, str, str, int, str | None]] = {
        (b.name, b.adapter, b.model, b.model_version, b.table) for b in existing
    }
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


def _validate_postcard_bindings(merged: MdlFile) -> list[Diagnostic]:
    """Warn when a domain has postcard-bound models but also unbound models with
    optional fields.

    postcard is not self-describing, so unbound optional fields keep the
    default serde ``skip_serializing_if`` behaviour, which postcard cannot
    decode across presence/absence once a value is later omitted or added
    (see #430/#437). A domain that already binds some of its models to
    postcard is presumably encoding everything that way, so a sibling model
    with optional fields and no binding is the most likely place for that bug
    to reappear silently.
    """
    adapter_types: dict[str, str] = {b.name: b.adapter for b in merged.bindings if b.adapter}
    bound_models: set[str] = set()
    for b in merged.bindings:
        if not b.model:
            continue
        resolved = adapter_types.get(b.adapter, b.adapter)
        if resolved == "postcard":
            bound_models.add(b.model)
    if not bound_models:
        return []
    bound_domains = {model.split(".", 1)[0] for model in bound_models}

    warnings: list[Diagnostic] = []
    for domain in merged.domains:
        if domain.name not in bound_domains:
            continue
        for model_name, versions in domain.models.items():
            qualified = f"{domain.name}.{model_name}"
            if qualified in bound_models:
                continue
            if not any(field.optional for version in versions for field in version.fields):
                continue
            warnings.append(
                Diagnostic(
                    code="POSTCARD",
                    message=(
                        f"{qualified} has optional fields but no postcard binding, even though "
                        f"other models in domain '{domain.name}' are bound to postcard; unbound "
                        "optional fields keep skip_serializing_if, which postcard cannot decode "
                        "across presence/absence -- add a binding for this model or confirm the "
                        "omission is intentional"
                    ),
                    severity="warning",
                    path="<workspace>",
                )
            )
    return warnings


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
