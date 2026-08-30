from __future__ import annotations

from modelable.compiler.workspace import Workspace
from modelable.conversion_plan import (
    CONVERSION_IMPOSSIBLE,
    CONVERSION_PARTIAL_FALLIBLE,
    CONVERSION_REQUIRES_HOOK,
    CONVERSION_TOTAL_IRREVERSIBLE,
    CONVERSION_TOTAL_REVERSIBLE,
    ConversionPlan,
    build_conversion_plan,
)
from modelable.planner.plans import build_plan_documents

__all__ = [
    "CONVERSION_IMPOSSIBLE",
    "CONVERSION_PARTIAL_FALLIBLE",
    "CONVERSION_REQUIRES_HOOK",
    "CONVERSION_TOTAL_IRREVERSIBLE",
    "CONVERSION_TOTAL_REVERSIBLE",
    "ConversionPlan",
    "build_conversion_plans",
]


def build_conversion_plans(workspace: Workspace) -> list[ConversionPlan]:
    plans = [build_conversion_plan(plan) for plan in build_plan_documents(workspace)]
    return sorted(plans, key=lambda plan: (plan.source, plan.target))
