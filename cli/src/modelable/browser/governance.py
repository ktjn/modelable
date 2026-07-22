from __future__ import annotations

from modelable.browser.dto import (
    BrowserGovernanceFinding,
    BrowserGovernanceResult,
)
from modelable.compiler.workspace import Workspace
from modelable.governance import build_projection_governance_findings


def build_browser_governance(
    workspace: Workspace,
    workspace_revision: int,
) -> BrowserGovernanceResult:
    findings: list[BrowserGovernanceFinding] = []

    for domain in workspace.mdl.domains:
        for projection_name, versions in sorted(domain.projections.items()):
            for pv in sorted(versions, key=lambda v: v.version):
                pv_findings = build_projection_governance_findings(domain.name, projection_name, pv, workspace.mdl)
                for finding in pv_findings:
                    findings.append(
                        BrowserGovernanceFinding(
                            code=finding.code,
                            subject=finding.subject,
                            message=finding.message,
                        )
                    )

    return BrowserGovernanceResult(
        workspace_revision=workspace_revision,
        findings=tuple(findings),
    )
