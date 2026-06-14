from __future__ import annotations

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
            errors.append(
                f"{domain.name}: auto projections references unknown model "
                f"'{decl.model}'"
            )
            continue

        model_version = next(
            (mv for mv in model_versions if mv.version == decl.version), None
        )
        if model_version is None:
            errors.append(
                f"{domain.name}: auto projections references "
                f"{decl.model}@{decl.version} which does not exist"
            )
            continue

        for target in decl.targets:
            projection_name = _generated_projection_name(decl.model, target.kind)
            existing = domain.projections.get(projection_name)
            if existing is not None:
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
    return any(_annotation_matches(field, ann) for ann in target.excluded_annotations)


def _has_annotation(field: FieldDef, annotation_type: type) -> bool:
    return any(isinstance(a, annotation_type) for a in field.annotations)


def _annotation_matches(field: FieldDef, excluded: Annotation) -> bool:
    for ann in field.annotations:
        if type(ann) is not type(excluded):
            continue
        if isinstance(ann, AnnPii) and isinstance(excluded, AnnPii):
            return True
        if isinstance(ann, AnnServer) and isinstance(excluded, AnnServer):
            return True
        if isinstance(ann, AnnClassification) and isinstance(excluded, AnnClassification):
            return True
    return False
