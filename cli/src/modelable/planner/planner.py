from __future__ import annotations

from modelable.dependency_graph import resolve_projection_aliases
from modelable.parser.ir import (
    AnnClassification,
    Annotation,
    AnnPii,
    AnnServer,
    AutoProjectionTarget,
    DirectMapping,
    DomainDef,
    FieldDef,
    MdlFile,
    ModelVersion,
    ProjectionField,
    ProjectionVersion,
    SelectionClause,
    SourceRef,
    VersionExact,
)


def expand_auto_projections(mdl: MdlFile) -> list[str]:
    """Expand auto projection declarations into explicit projection versions.

    Mutates ``mdl.domains`` in place, adding generated projections to each
    domain's ``projections`` dict. Returns a list of error strings.
    """
    errors: list[str] = []
    for domain in mdl.domains:
        errors.extend(_expand_domain_auto_projections(domain))
    return errors


def _expand_domain_auto_projections(domain: DomainDef) -> list[str]:
    errors: list[str] = []
    for decl in domain.auto_projections:
        model_versions = domain.models.get(decl.model)
        if model_versions is None:
            errors.append(f"{domain.name}: auto projections references unknown model '{decl.model}'")
            continue

        model_version = next((mv for mv in model_versions if mv.version == decl.version), None)
        if model_version is None:
            errors.append(
                f"{domain.name}: auto projections references {decl.model}@{decl.version} which does not exist"
            )
            continue

        for target in decl.targets:
            projection_name = _generated_projection_name(decl.model, target.kind)
            existing = domain.projections.get(projection_name)
            if existing is not None and any(projection.version == decl.version for projection in existing):
                # Skip if an explicit projection with the same name already exists.
                # The workspace validator already checks for conflicts; this is
                # just a safety guard.
                continue

            fields = _build_projection_fields(target, model_version, decl.model)
            projection = ProjectionVersion(
                version=decl.version,
                source=SourceRef(
                    model=f"{domain.name}.{decl.model}",
                    version=VersionExact(version=decl.version),
                    alias=_default_alias(decl.model),
                ),
                fields=fields,
                auto_generated=True,
                event_operations=list(target.operations) if target.kind == "event" else [],
            )
            domain.projections.setdefault(projection_name, []).append(projection)

    return errors


def _generated_projection_name(model_name: str, kind: str) -> str:
    suffixes = {
        "db": "Db",
        "request": "Request",
        "reply": "Reply",
        "event": "Event",
    }
    return f"{model_name}{suffixes[kind]}"


def _default_alias(model_name: str) -> str:
    return model_name[0].lower() + model_name[1:]


def _build_projection_fields(
    target: AutoProjectionTarget,
    model_version: ModelVersion,
    model_name: str,
) -> list[ProjectionField]:
    alias = _default_alias(model_name)
    included = []
    for field in model_version.fields:
        if _is_excluded(field, target):
            continue
        included.append(
            ProjectionField(
                name=field.name,
                mapping=DirectMapping(source_alias=alias, source_field=field.name),
                annotations=list(field.annotations),
                constraints=list(field.constraints),
            )
        )
    return included


def _is_excluded(field: FieldDef, target: AutoProjectionTarget) -> bool:
    # Explicit field name exclusions
    if field.name in target.excluded_fields:
        return True

    # Implicit request exclusion: @server fields are excluded from request models
    if target.kind == "request" and _has_annotation(field, AnnServer):
        return True

    # Check excluded annotations
    return any(annotation_matches(field, ann) for ann in target.excluded_annotations)


def _has_annotation(field: FieldDef, annotation_type: type) -> bool:
    return any(isinstance(a, annotation_type) for a in field.annotations)


def annotation_matches(field: FieldDef | ProjectionField, candidate: Annotation) -> bool:
    """True when `field`'s annotation matches `candidate`.

    Shared by auto-projection `exclude [@pii]`-style filters and Slice H1's
    `pick`/`omit` annotation selectors -- one annotation-filter matcher, not
    two independently-maintained ones. `@pii` and `@server` match by kind;
    `@classification` matches by exact level so selectors such as
    `@classification("secret")` never match a differently-classified field.
    """
    for ann in field.annotations:
        if type(ann) is not type(candidate):
            continue
        if isinstance(ann, AnnPii) and isinstance(candidate, AnnPii):
            return True
        if isinstance(ann, AnnServer) and isinstance(candidate, AnnServer):
            return True
        if isinstance(ann, AnnClassification) and isinstance(candidate, AnnClassification):
            return ann.level == candidate.level
    return False


_SourceField = FieldDef | ProjectionField


def expand_projection_selections(mdl: MdlFile) -> list[str]:
    """Expand `pick(...)`/`omit(...)` selection clauses (Slice H1) into
    explicit projection fields.

    Mutates ``mdl.domains`` in place, mirroring ``expand_auto_projections``'s
    convention, and must run on the same merged, post-auto-projection-expansion
    ``mdl`` that function receives -- pick/omit's join sources can reference
    models in other files or auto-generated projections, both only resolvable
    once the workspace is merged and auto projections have been materialized.
    Returns a list of error strings.
    """
    errors: list[str] = []
    for domain in mdl.domains:
        for projection_name, versions in domain.projections.items():
            for index, version in enumerate(versions):
                if version.selection is None:
                    continue
                fqn = f"{domain.name}.{projection_name}@{version.version}"
                expanded, version_errors = _expand_selection(mdl, fqn, version)
                if version_errors:
                    errors.extend(version_errors)
                    continue
                versions[index] = version.model_copy(update={"fields": expanded})
    return errors


def _expand_selection(
    mdl: MdlFile,
    fqn: str,
    version: ProjectionVersion,
) -> tuple[list[ProjectionField], list[str]]:
    selection = version.selection
    assert selection is not None
    errors: list[str] = []

    aliases = resolve_projection_aliases(version, mdl)
    declared_aliases = {version.source.alias, *(join.alias for join in version.joins)}
    missing = declared_aliases - set(aliases)
    if missing:
        errors.append(f"{fqn}: unresolved source reference for alias '{sorted(missing)[0]}'")
        return [], errors

    alias_fields: dict[str, dict[str, _SourceField]] = {
        alias: {field.name: field for field in resolved.version.fields} for alias, resolved in aliases.items()
    }

    resolved_selectors = _resolve_selectors(fqn, selection, alias_fields, errors)
    if errors:
        return [], errors

    if selection.mode == "pick":
        chosen = resolved_selectors
    else:
        excluded = {(alias, name) for alias, name, _ in resolved_selectors}
        chosen = [
            (alias, name, field)
            for alias, fields in alias_fields.items()
            for name, field in fields.items()
            if (alias, name) not in excluded
        ]

    existing_names = {field.name for field in version.fields}
    expanded: list[ProjectionField] = []
    seen_names: dict[str, str] = {}
    for alias, name, field in chosen:
        if name in existing_names:
            errors.append(
                f"{fqn}: field '{name}' is selected by {selection.mode}(...) and also declared in the projection body"
            )
            continue
        if name in seen_names:
            if seen_names[name] != alias:
                errors.append(
                    f"{fqn}: field '{name}' is selected from both '{seen_names[name]}' and '{alias}'; "
                    "qualify or rename one before it can be picked/omitted together"
                )
            continue
        seen_names[name] = alias
        expanded.append(
            ProjectionField(
                name=name,
                mapping=DirectMapping(source_alias=alias, source_field=name),
                annotations=list(field.annotations),
                constraints=list(field.constraints),
            )
        )

    if errors:
        return [], errors

    return expanded + version.fields, errors


def _resolve_selectors(
    fqn: str,
    selection: SelectionClause,
    alias_fields: dict[str, dict[str, _SourceField]],
    errors: list[str],
) -> list[tuple[str, str, _SourceField]]:
    resolved: list[tuple[str, str, _SourceField]] = []

    for alias, field_name in selection.qualified_fields:
        fields = alias_fields.get(alias)
        if fields is None or field_name not in fields:
            errors.append(f"{fqn}: {selection.mode} selector '{alias}.{field_name}' does not resolve to a known field")
            continue
        resolved.append((alias, field_name, fields[field_name]))

    for field_name in selection.field_names:
        matches = [
            (alias, field_name, fields[field_name]) for alias, fields in alias_fields.items() if field_name in fields
        ]
        if not matches:
            errors.append(f"{fqn}: {selection.mode} selector '{field_name}' does not resolve to a known field")
        elif len(matches) > 1:
            sources = ", ".join(sorted(alias for alias, _, _ in matches))
            errors.append(
                f"{fqn}: {selection.mode} selector '{field_name}' is ambiguous across sources "
                f"({sources}); qualify it as alias.{field_name}"
            )
        else:
            resolved.append(matches[0])

    for annotation in selection.annotations:
        matched = [
            (alias, name, field)
            for alias, fields in alias_fields.items()
            for name, field in fields.items()
            if annotation_matches(field, annotation)
        ]
        if not matched:
            errors.append(f"{fqn}: {selection.mode} annotation selector '@{annotation.kind}' matched no field")
        resolved.extend(matched)

    return resolved
