from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from modelable.compiler.workspace import Workspace
from modelable.parser.ir import DirectMapping, ProjectionVersion
from modelable.registry.resolver import resolve_model_ref

CONVERSION_TOTAL_REVERSIBLE = "total_reversible"
CONVERSION_TOTAL_IRREVERSIBLE = "total_irreversible"
CONVERSION_PARTIAL_FALLIBLE = "partial_fallible"
CONVERSION_REQUIRES_HOOK = "requires_hook"
CONVERSION_IMPOSSIBLE = "impossible"


@dataclass(frozen=True)
class ConversionPlan:
    source: str
    target: str
    classification: str
    fields: tuple[str, ...]
    hook_required: bool
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "classification": self.classification,
            "fields": list(self.fields),
            "hook_required": self.hook_required,
            "reason": self.reason,
        }


def build_conversion_plans(workspace: Workspace) -> list[ConversionPlan]:
    plans: list[ConversionPlan] = []
    for domain in workspace.mdl.domains:
        for projection_name, versions in domain.projections.items():
            for projection in versions:
                plans.append(_plan_for_projection(workspace, domain.name, projection_name, projection))
    return sorted(plans, key=lambda plan: (plan.source, plan.target))


def _plan_for_projection(
    workspace: Workspace, domain_name: str, projection_name: str, projection: ProjectionVersion
) -> ConversionPlan:
    source = resolve_model_ref(workspace.mdl, projection.source.model, projection.source.version)
    source_ref = f"{source.domain_name}.{source.model_name}@{source.version.version}"
    target_ref = f"{domain_name}.{projection_name}@{projection.version}"
    if not projection.fields:
        return ConversionPlan(source_ref, target_ref, CONVERSION_IMPOSSIBLE, (), True, "projection has no fields")

    field_names = tuple(field.name for field in projection.fields)
    source_names = {field.name for field in source.version.fields}
    target_names = set(field_names)
    mapped_source_names: set[str] = set()
    for field in projection.fields:
        if not isinstance(field.mapping, DirectMapping):
            return ConversionPlan(
                source_ref,
                target_ref,
                CONVERSION_PARTIAL_FALLIBLE,
                field_names,
                True,
                "computed mappings require validation or a user hook",
            )
        mapped_source_names.add(field.mapping.source_field)
    if not mapped_source_names <= source_names:
        return ConversionPlan(
            source_ref, target_ref, CONVERSION_IMPOSSIBLE, field_names, True, "mapping references unknown fields"
        )
    if mapped_source_names == source_names and target_names == source_names:
        classification = CONVERSION_TOTAL_REVERSIBLE
        reason = "one-to-one direct mapping preserves every source field"
        hook_required = False
    else:
        classification = CONVERSION_TOTAL_IRREVERSIBLE
        reason = "direct mapping drops or renames source information"
        hook_required = False
    return ConversionPlan(source_ref, target_ref, classification, field_names, hook_required, reason)
