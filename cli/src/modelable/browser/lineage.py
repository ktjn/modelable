from __future__ import annotations

from modelable.browser.dto import (
    BrowserFieldLineage,
    BrowserLineageResult,
    BrowserProjectionLineage,
)
from modelable.compiler.workspace import Workspace
from modelable.planner.lineage import build_projection_lineage


def build_browser_lineage(
    workspace: Workspace,
    workspace_revision: int,
) -> BrowserLineageResult:
    projections: list[BrowserProjectionLineage] = []

    for domain in workspace.mdl.domains:
        for projection_name, versions in sorted(domain.projections.items()):
            for pv in sorted(versions, key=lambda v: v.version):
                lineage = build_projection_lineage(domain.name, projection_name, pv, workspace.mdl)
                fields = tuple(
                    BrowserFieldLineage(
                        field_name=fl.field_name,
                        kind=fl.kind,
                        lineage=tuple(fl.lineage),
                        expression=fl.expression,
                    )
                    for fl in lineage.fields
                )
                projections.append(
                    BrowserProjectionLineage(
                        domain=lineage.domain,
                        projection=lineage.projection,
                        version=lineage.version,
                        fields=fields,
                    )
                )

    return BrowserLineageResult(
        workspace_revision=workspace_revision,
        projections=tuple(projections),
    )
