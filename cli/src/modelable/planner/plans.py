"""Build and write projection plan documents to .modelable/plans/."""

from __future__ import annotations

import json
from pathlib import Path

from modelable.compiler.workspace import Workspace
from modelable.parser.ir import ComputedMapping, DirectMapping, MdlFile, ProjectionVersion
from modelable.planner.lineage import ProjectionLineage, build_projection_lineage
from modelable.registry.resolver import resolve_model_ref


def build_plan(
    domain_name: str,
    projection_name: str,
    pv: ProjectionVersion,
    lineage: ProjectionLineage,
    mdl: MdlFile,
) -> dict:
    """Return the plan document dict for a single projection version."""
    source_block = _resolve_source_block(pv.source.model, pv.source.version, pv.source.alias, mdl)

    joins_block = [
        _resolve_source_block(join.model, join.version, join.alias, mdl, on=join.on)
        for join in pv.joins
    ]
    revalidation_reasons = _collect_revalidation_reasons(source_block, joins_block)

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
        fl = lineage_by_field.get(proj_field.name)
        entry["lineage"] = fl.lineage if fl else []
        fields_block.append(entry)

    return {
        "$schema": "modelable-plan/1.0",
        "domain": domain_name,
        "projection": projection_name,
        "version": pv.version,
        "auto_generated": pv.auto_generated,
        "requires_revalidation": bool(revalidation_reasons),
        "revalidation_reasons": revalidation_reasons,
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

    for domain in workspace.mdl.domains:
        for projection_name, versions in domain.projections.items():
            for pv in versions:
                lineage = build_projection_lineage(
                    domain.name, projection_name, pv, workspace.mdl
                )
                plan = build_plan(
                    domain.name, projection_name, pv, lineage, workspace.mdl
                )
                filename = f"{domain.name}.{projection_name}.v{pv.version}.plan.json"
                out_path = plans_dir / filename
                out_path.write_text(
                    json.dumps(plan, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
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
        change_kind = resolved.version.change_kind.value
    except LookupError:
        resolved_version = None
        change_kind = None

    block: dict = {
        "model": model_ref,
        "resolved_version": resolved_version,
        "alias": alias,
        "change_kind": change_kind,
    }
    if on is not None:
        block["on"] = on
    return block


def _collect_revalidation_reasons(source_block: dict, joins_block: list[dict]) -> list[str]:
    reasons: list[str] = []

    for block in [source_block, *joins_block]:
        if block.get("change_kind") == "breaking" and block.get("resolved_version") is not None:
            relation = "source" if "on" not in block else f"join {block.get('alias')}"
            reasons.append(
                f"{relation} {block['model']}@{block['resolved_version']} is marked breaking"
            )

    return reasons
