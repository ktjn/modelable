"""Build and write projection plan documents to .modelable/plans/."""

from __future__ import annotations

from pathlib import Path

from modelable.compat.projection_fields import resolve_projection_field_type_and_optionality
from modelable.compiler.workspace import Workspace
from modelable.dependency_graph import resolve_projection_aliases
from modelable.governance.checker import build_projection_governance_findings
from modelable.parser.ir import (
    ComputedMapping,
    DirectMapping,
    FieldDef,
    MdlFile,
    ModelVersion,
    ProjectionField,
    ProjectionVersion,
)
from modelable.planner.lineage import ProjectionLineage, build_projection_lineage
from modelable.planner.protocol import PLAN_SCHEMA, PlanDocument, serialize_plan
from modelable.registry.resolver import ResolvedModelRef, resolve_model_ref


def build_plan(
    domain_name: str,
    projection_name: str,
    pv: ProjectionVersion,
    lineage: ProjectionLineage,
    mdl: MdlFile,
) -> dict:
    """Return the plan document dict for a single projection version."""
    source_block = _resolve_source_block(pv.source.model, pv.source.version, pv.source.alias, mdl)

    joins_block = [_resolve_source_block(join.model, join.version, join.alias, mdl, on=join.on) for join in pv.joins]
    revalidation_reasons = _collect_revalidation_reasons(source_block, joins_block)
    governance_findings = [
        finding.as_dict() for finding in build_projection_governance_findings(domain_name, projection_name, pv, mdl)
    ]

    lineage_by_field = {fl.field_name: fl for fl in lineage.fields}

    fields_block = []
    for proj_field in pv.fields:
        mapping = proj_field.mapping
        entry: dict = {"name": proj_field.name}
        if isinstance(mapping, DirectMapping):
            entry["kind"] = "direct"
            entry["source_alias"] = mapping.source_alias
            entry["source_field"] = mapping.source_field
        elif isinstance(mapping, ComputedMapping):
            entry["kind"] = "computed"
            entry["expression"] = mapping.expression
        field_type, optional = resolve_projection_field_type_and_optionality(proj_field, pv, mdl)
        entry["type"] = field_type.model_dump(mode="json") if field_type is not None else None
        entry["optional"] = optional
        fl = lineage_by_field.get(proj_field.name)
        entry["lineage"] = fl.lineage if fl else []
        fields_block.append(entry)

    return {
        "$schema": PLAN_SCHEMA,
        "domain": domain_name,
        "projection": projection_name,
        "version": pv.version,
        "auto_generated": pv.auto_generated,
        "requires_revalidation": bool(revalidation_reasons),
        "revalidation_reasons": revalidation_reasons,
        "governance_findings": governance_findings,
        "source": source_block,
        "joins": joins_block,
        "group_by": pv.group_by,
        "fields": fields_block,
        "planner_metadata": {
            "modelable_schema": "1.0",
        },
    }


def write_plans(workspace: Workspace, plans_dir: Path) -> list[Path]:
    """Write a plan JSON file for every projection version in the workspace."""
    plans_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for plan in build_plan_documents(workspace):
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
    version_spec,
    alias: str,
    mdl: MdlFile,
    on: str | None = None,
) -> dict:
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

    block: dict = {
        "model": model_ref,
        "resolved_version": resolved_version,
        "alias": alias,
        "change_kind": change_kind,
        "resolved": resolved_block,
    }
    if on is not None:
        block["on"] = on
    return block


def _resolved_declaration_block(resolved: ResolvedModelRef, mdl: MdlFile) -> dict[str, object]:
    version = resolved.version
    if isinstance(version, ModelVersion):
        fields = [
            {
                "name": field.name,
                "type": field.type.model_dump(mode="json"),
                "optional": field.optional,
                "nullable": field.nullable,
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
                    "type": field_type.model_dump(mode="json") if field_type is not None else None,
                    "optional": optional,
                    "nullable": _resolve_projection_field_nullable(field, version, mdl),
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


def _collect_revalidation_reasons(source_block: dict, joins_block: list[dict]) -> list[str]:
    reasons: list[str] = []

    for block in [source_block, *joins_block]:
        if block.get("change_kind") == "breaking" and block.get("resolved_version") is not None:
            relation = "source" if "on" not in block else f"join {block.get('alias')}"
            reasons.append(f"{relation} {block['model']}@{block['resolved_version']} is marked breaking")

    return reasons


def build_plan_documents(workspace: Workspace) -> list[PlanDocument]:
    """Build plan/v0 documents for every workspace projection."""
    documents: list[PlanDocument] = []
    for domain in workspace.mdl.domains:
        for projection_name, versions in domain.projections.items():
            for pv in versions:
                lineage = build_projection_lineage(domain.name, projection_name, pv, workspace.mdl)
                documents.append(build_plan(domain.name, projection_name, pv, lineage, workspace.mdl))
    return documents
