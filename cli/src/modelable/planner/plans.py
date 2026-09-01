"""Build and write projection plan documents to .modelable/plans/."""

from __future__ import annotations

from pathlib import Path

from modelable.compat.projection_fields import resolve_projection_field_type_and_optionality
from modelable.compiler.workspace import Workspace
from modelable.dependency_graph import resolve_projection_aliases
from modelable.governance.checker import build_projection_governance_findings
from modelable.parser.ir import (
    ArrayType,
    ClassificationLevel,
    ComputedMapping,
    DirectMapping,
    EnumRefType,
    EnumType,
    FieldDef,
    FieldType,
    MapType,
    MdlFile,
    ModelVersion,
    NamedType,
    ObjectType,
    ProjectionField,
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
from modelable.planner.lineage import ProjectionLineage, build_projection_lineage
from modelable.planner.protocol import PLAN_SCHEMA, PLAN_V1_SCHEMA, PlanDocument, serialize_plan
from modelable.registry.resolver import ResolvedModelRef, resolve_model_ref, resolve_ref_type, resolve_semantic_type_ref


def build_plan(
    domain_name: str,
    projection_name: str,
    pv: ProjectionVersion,
    lineage: ProjectionLineage,
    mdl: MdlFile,
    *,
    schema: str = PLAN_SCHEMA,
) -> PlanDocument:
    """Return the plan document dict for a single projection version."""
    if schema not in {PLAN_SCHEMA, PLAN_V1_SCHEMA}:
        raise ValueError(f"unsupported plan schema {schema!r}")
    source_block = _resolve_source_block(pv.source.model, pv.source.version, pv.source.alias, mdl)

    joins_block = [
        _resolve_source_block(
            join.model,
            join.version,
            join.alias,
            mdl,
            on=join.on,
            join_kind=join.join_kind,
            cardinality=join.cardinality,
        )
        for join in pv.joins
    ]
    revalidation_reasons = _collect_revalidation_reasons(source_block, joins_block)
    governance_findings = [
        finding.as_dict() for finding in build_projection_governance_findings(domain_name, projection_name, pv, mdl)
    ]

    lineage_by_field = {fl.field_name: fl for fl in lineage.fields}

    fields_block: list[dict[str, object]] = []
    for proj_field in pv.fields:
        mapping = proj_field.mapping
        entry: dict[str, object] = {"name": proj_field.name}
        if isinstance(mapping, DirectMapping):
            entry["kind"] = "direct"
            entry["source_alias"] = mapping.source_alias
            entry["source_field"] = mapping.source_field
        elif isinstance(mapping, ComputedMapping):
            entry["kind"] = "computed"
            entry["expression"] = mapping.expression
        field_type, optional = resolve_projection_field_type_and_optionality(proj_field, pv, mdl)
        entry["type"] = _field_type_document(field_type, mdl, domain_name) if field_type is not None else None
        entry["optional"] = optional
        entry["nullable"] = _resolve_projection_field_nullable(proj_field, pv, mdl)
        entry["constraints"] = [constraint.model_dump(mode="json") for constraint in proj_field.constraints]
        entry.update(_projection_governance_facts(proj_field, pv, mdl))
        fl = lineage_by_field.get(proj_field.name)
        entry["lineage"] = fl.lineage if fl else []
        if proj_field.annotations:
            entry["annotations"] = [
                annotation.model_dump(mode="json", exclude_none=True) for annotation in proj_field.annotations
            ]
        fields_block.append(entry)

    return {
        "$schema": schema,
        "domain": domain_name,
        "projection": projection_name,
        "version": pv.version,
        "auto_generated": pv.auto_generated,
        "requires_revalidation": bool(revalidation_reasons),
        "revalidation_reasons": revalidation_reasons,
        "governance_findings": governance_findings,
        "source": source_block,
        "joins": joins_block,
        "where": pv.where,
        "group_by": pv.group_by,
        "fields": fields_block,
        "planner_metadata": {
            "modelable_schema": "1.0",
        },
    }


def write_plans(workspace: Workspace, plans_dir: Path, *, schema: str = PLAN_SCHEMA) -> list[Path]:
    """Write a plan JSON file for every projection version in the workspace."""
    plans_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for plan in build_plan_documents(workspace, schema=schema):
        domain = plan["domain"]
        projection_name = plan["projection"]
        version = plan["version"]
        if not isinstance(domain, str) or not isinstance(projection_name, str) or not isinstance(version, int):
            raise TypeError("build_plan_documents returned an invalid plan identity")
        filename = f"{domain}.{projection_name}.v{version}.plan.json"
        out_path = plans_dir / filename
        out_path.write_text(serialize_plan(plan), encoding="utf-8")
        written.append(out_path)
    return written


def _resolve_source_block(
    model_ref: str,
    version_spec: VersionSpec,
    alias: str,
    mdl: MdlFile,
    on: str | None = None,
    join_kind: str | None = None,
    cardinality: str | None = None,
) -> dict[str, object]:
    try:
        resolved = resolve_model_ref(mdl, model_ref, version_spec)
        resolved_version = resolved.version.version
        change_kind = resolved.version.change_kind.value if isinstance(resolved.version, ModelVersion) else None
    except LookupError:
        resolved_version = None
        change_kind = None
        resolved_block = None
    else:
        resolved_block = _resolved_declaration_block(resolved, mdl)

    block: dict[str, object] = {
        "model": model_ref,
        "version": _version_spec(version_spec),
        "resolved_version": resolved_version,
        "alias": alias,
        "change_kind": change_kind,
        "resolved": resolved_block,
    }
    if on is not None:
        block["on"] = on
        block["kind"] = join_kind
        block["cardinality"] = cardinality
    return block


def _version_spec(version_spec: object) -> dict[str, object]:
    if isinstance(version_spec, VersionExact):
        return {"kind": "exact", "version": version_spec.version}
    if isinstance(version_spec, VersionRange):
        return {
            "kind": "range",
            "minInclusive": version_spec.min_inclusive,
            "maxExclusive": version_spec.max_exclusive,
        }
    if isinstance(version_spec, VersionMin):
        return {"kind": "min", "minInclusive": version_spec.min_inclusive}
    if isinstance(version_spec, VersionPinned):
        return {"kind": "pinned", "version": version_spec.version, "contentHash": version_spec.content_hash}
    raise TypeError(f"unsupported version specification: {type(version_spec).__name__}")


def _resolved_declaration_block(resolved: ResolvedModelRef, mdl: MdlFile) -> dict[str, object]:
    version = resolved.version
    if isinstance(version, ModelVersion):
        fields = [
            {
                "name": field.name,
                "type": _field_type_document(field.type, mdl, resolved.domain_name),
                "optional": field.optional,
                "nullable": field.nullable,
                "default": field.default,
                "constraints": [constraint.model_dump(mode="json") for constraint in field.constraints],
                "annotations": [
                    annotation.model_dump(mode="json", exclude_none=True) for annotation in field.annotations
                ],
                **_field_governance_facts(field, owner=_field_owner(field)),
            }
            for field in version.fields
        ]
        model_kind = version.model_kind.value
        kind = "model"
    else:
        fields = []
        for field in version.fields:
            field_type, optional = resolve_projection_field_type_and_optionality(field, version, mdl)
            fields.append(
                {
                    "name": field.name,
                    "type": _field_type_document(field_type, mdl, resolved.domain_name)
                    if field_type is not None
                    else None,
                    "optional": optional,
                    "nullable": _resolve_projection_field_nullable(field, version, mdl),
                    "constraints": [constraint.model_dump(mode="json") for constraint in field.constraints],
                    "annotations": [
                        annotation.model_dump(mode="json", exclude_none=True) for annotation in field.annotations
                    ],
                    **_projection_governance_facts(field, version, mdl),
                }
            )
        model_kind = None
        kind = "projection"

    return {
        "domain": resolved.domain_name,
        "name": resolved.model_name,
        "version": version.version,
        "kind": kind,
        "model_kind": model_kind,
        "fields": fields,
    }


def _field_type_document(field_type: FieldType, mdl: MdlFile, current_domain: str) -> dict[str, object]:
    document = field_type.model_dump(mode="json")
    if isinstance(field_type, ArrayType):
        document["item"] = _field_type_document(field_type.item, mdl, current_domain)
    elif isinstance(field_type, MapType):
        document["key"] = _field_type_document(field_type.key, mdl, current_domain)
        document["value"] = _field_type_document(field_type.value, mdl, current_domain)
    elif isinstance(field_type, ObjectType):
        document["fields"] = [
            {**field.model_dump(mode="json"), "type": _field_type_document(field.type, mdl, current_domain)}
            for field in field_type.fields
        ]
    elif isinstance(field_type, UnionType):
        document["variants"] = [
            {**variant.model_dump(mode="json"), "type": _field_type_document(variant.type, mdl, current_domain)}
            for variant in field_type.variants
        ]
    if isinstance(field_type, RefType):
        try:
            resolved = resolve_ref_type(field_type, mdl)
        except LookupError:
            resolved = None
        if resolved is not None and isinstance(resolved.version, ModelVersion):
            key_field = next((field for field in resolved.version.fields if field.is_key), None)
            if key_field is not None:
                document["resolved_key_type"] = _field_type_document(key_field.type, mdl, resolved.domain_name)
    if isinstance(field_type, EnumRefType):
        try:
            declaring_domain, declaration = resolve_semantic_type_ref(
                mdl, current_domain, field_type.name, field_type.version
            )
        except LookupError:
            return document
        if isinstance(declaration.underlying, EnumType):
            document["values"] = list(declaration.underlying.values)
            document["declaring_domain"] = declaring_domain
    if isinstance(field_type, NamedType):
        semantic_declaration: SemanticTypeDecl | None = None
        try:
            declaring_domain, semantic_declaration = resolve_semantic_type_ref(mdl, current_domain, field_type.name)
        except LookupError:
            declaring_domain = current_domain
        if semantic_declaration is not None:
            document["resolved_underlying_type"] = _field_type_document(
                semantic_declaration.underlying, mdl, declaring_domain
            )
        else:
            try:
                # Value objects are conventionally published at version 0;
                # named model references must include those versions in their
                # generated target-neutral facts.
                resolved = _resolve_named_model_ref(mdl, current_domain, field_type.name)
            except LookupError:
                resolved = None
            if resolved is not None and isinstance(resolved.version, ModelVersion):
                document["resolved_model"] = _resolved_declaration_block(resolved, mdl)
    return document


def _resolve_named_model_ref(mdl: MdlFile, current_domain: str, type_name: str) -> ResolvedModelRef:
    if "." in type_name:
        return resolve_model_ref(mdl, type_name, VersionMin(min_inclusive=0))
    candidates = [current_domain, *(domain.name for domain in mdl.domains if domain.name != current_domain)]
    for domain_name in candidates:
        try:
            return resolve_model_ref(mdl, f"{domain_name}.{type_name}", VersionMin(min_inclusive=0))
        except LookupError:
            continue
    raise LookupError(f"unknown model '{type_name}'")


def _resolve_projection_field_nullable(
    field: ProjectionField, projection: ProjectionVersion, mdl: MdlFile
) -> bool | None:
    if not isinstance(field.mapping, DirectMapping):
        return None
    resolved = resolve_projection_aliases(projection, mdl).get(field.mapping.source_alias)
    if resolved is None:
        return None
    return _resolve_field_nullable(resolved.version, field.mapping.source_field, mdl)


def _resolve_field_nullable(version: ModelVersion | ProjectionVersion, field_name: str, mdl: MdlFile) -> bool | None:
    if isinstance(version, ModelVersion):
        model_field: FieldDef | None = next(
            (candidate for candidate in version.fields if candidate.name == field_name), None
        )
        return model_field.nullable if model_field is not None else None
    projection_field: ProjectionField | None = next(
        (candidate for candidate in version.fields if candidate.name == field_name), None
    )
    if projection_field is None or not isinstance(projection_field.mapping, DirectMapping):
        return None
    return _resolve_projection_field_nullable(projection_field, version, mdl)


def _projection_governance_facts(
    field: ProjectionField, projection: ProjectionVersion, mdl: MdlFile
) -> dict[str, object]:
    source_field: FieldDef | ProjectionField | None = None
    if isinstance(field.mapping, DirectMapping):
        resolved = resolve_projection_aliases(projection, mdl).get(field.mapping.source_alias)
        if resolved is not None:
            source_field = next(
                (candidate for candidate in resolved.version.fields if candidate.name == field.mapping.source_field),
                None,
            )
    return _field_governance_facts(
        field,
        pii=field.is_pii or (source_field.is_pii if source_field is not None else False),
        classification=field.classification or (source_field.classification if source_field is not None else None),
        owner=_field_owner(source_field),
    )


def _field_governance_facts(
    field: FieldDef | ProjectionField,
    *,
    pii: bool | None = None,
    classification: ClassificationLevel | None = None,
    owner: str | None = None,
) -> dict[str, object]:
    level = classification if classification is not None else field.classification
    return {
        "pii": field.is_pii if pii is None else pii,
        "classification": level.value if level is not None else None,
        "owner": owner,
    }


def _field_owner(field: FieldDef | ProjectionField | None) -> str | None:
    if field is None:
        return None
    if not isinstance(field, FieldDef):
        return None
    for annotation in field.annotations:
        if annotation.kind == "owner":
            return annotation.team
    return None


def _collect_revalidation_reasons(source_block: dict[str, object], joins_block: list[dict[str, object]]) -> list[str]:
    reasons: list[str] = []

    for block in [source_block, *joins_block]:
        if block.get("change_kind") == "breaking" and block.get("resolved_version") is not None:
            relation = "source" if "on" not in block else f"join {block.get('alias')}"
            reasons.append(f"{relation} {block['model']}@{block['resolved_version']} is marked breaking")

    return reasons


def build_plan_documents(workspace: Workspace, *, schema: str = PLAN_SCHEMA) -> list[PlanDocument]:
    """Build plan documents for every workspace projection."""
    documents: list[PlanDocument] = []
    for domain in workspace.mdl.domains:
        for projection_name, versions in domain.projections.items():
            for pv in versions:
                lineage = build_projection_lineage(domain.name, projection_name, pv, workspace.mdl)
                documents.append(build_plan(domain.name, projection_name, pv, lineage, workspace.mdl, schema=schema))
    return documents
