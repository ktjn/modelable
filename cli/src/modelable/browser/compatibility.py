from __future__ import annotations

from modelable.browser.dto import (
    BrowserCompatibilityReport,
    BrowserCompatibilityResult,
    BrowserFieldChange,
    BrowserProjectionImpact,
)
from modelable.compat import (
    CompatibilityReport,
    check_model_version_compatibility,
)
from modelable.compiler.workspace import Workspace
from modelable.consequence import build_consequence_graph, build_model_consequences, change_nodes_for_report


def build_browser_compatibility(
    workspace: Workspace,
    workspace_revision: int,
) -> BrowserCompatibilityResult:
    reports: list[BrowserCompatibilityReport] = []
    impacts: list[BrowserProjectionImpact] = []
    consequences = []
    change_nodes = []

    for domain in workspace.mdl.domains:
        for model_name, versions in sorted(domain.models.items()):
            sorted_versions = sorted(versions, key=lambda v: v.version)
            for i in range(len(sorted_versions) - 1):
                from_v = sorted_versions[i].version
                to_v = sorted_versions[i + 1].version
                report = check_model_version_compatibility(workspace.mdl, domain.name, model_name, from_v, to_v)
                reports.append(_convert_report(report))

                if report.status == "breaking":
                    report_consequences = build_model_consequences(workspace, report)
                    consequences.extend(report_consequences)
                    change_nodes.extend(change_nodes_for_report(report))
                    for consequence in report_consequences[1:]:
                        domain_name, subject = consequence.subject.split(".", 1)
                        projection_name, version = subject.rsplit("@", 1)
                        impacts.append(
                            BrowserProjectionImpact(
                                domain_name=domain_name,
                                projection_name=projection_name,
                                version=int(version),
                                status=consequence.status,
                                reason=consequence.reason,
                            )
                        )

    return BrowserCompatibilityResult(
        workspace_revision=workspace_revision,
        reports=tuple(reports),
        impacts=tuple(impacts),
        consequence_graph=build_consequence_graph(consequences, change_nodes),
    )


def _convert_report(report: CompatibilityReport) -> BrowserCompatibilityReport:
    return BrowserCompatibilityReport(
        domain_name=report.domain_name,
        model_name=report.model_name,
        from_version=report.from_version,
        to_version=report.to_version,
        status=report.status,
        findings=tuple(report.findings),
        changes=tuple(
            BrowserFieldChange(
                kind=change.kind,
                field_name=change.field_name,
                previous_name=change.previous_name,
                replacement=change.replacement,
                from_optional=change.from_optional,
                to_optional=change.to_optional,
                from_nullable=change.from_nullable,
                to_nullable=change.to_nullable,
                from_type=change.from_type,
                to_type=change.to_type,
            )
            for change in report.changes
        ),
    )
