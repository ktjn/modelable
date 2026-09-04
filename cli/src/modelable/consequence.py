from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from modelable.compat.checker import CompatibilityReport, ProjectionCompatibilityReport, analyze_impact
from modelable.compat.diff import ProjectionChange
from modelable.compat.enums import EXHAUSTIVE_MATCH, EnumChange, describe_enum_change
from modelable.compat.policy import CompatibilityProfile, EnforcementResult
from modelable.compat.targets import SEVERITIES, TargetCompatibilityReport
from modelable.compiler.workspace import Workspace
from modelable.consequence_protocol import CONSEQUENCE_SCHEMA, validate_consequence_graph
from modelable.registry.resolver import find_dependents

ACTION_NO_ACTION = "no_action"
ACTION_RECOMPILE = "recompile"
ACTION_REGENERATE = "regenerate"
ACTION_CONSUMER_UPDATE = "consumer_update"
ACTION_BREAKING = "breaking"
ACTION_STORAGE_MIGRATION = "storage_migration"
ACTION_DATA_BACKFILL = "data_backfill"
ACTION_PROJECTION_REBUILD = "projection_rebuild"
ACTION_GOVERNANCE_REVIEW = "governance_review"
ACTION_EVENT_REPLAY = "event_replay"


@dataclass(frozen=True)
class Consequence:
    action: str
    subject: str
    status: str
    reason: str | None = None
    causal_path: tuple[str, ...] = ()
    causal_changes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "subject": self.subject,
            "status": self.status,
            "reason": self.reason,
            "causal_path": list(self.causal_path),
        }


def build_consequence_graph(
    consequences: list[Consequence], change_nodes: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Build a deterministic node/edge view from consequence causal paths."""
    nodes: dict[str, dict[str, Any]] = {}
    edges: set[tuple[str, str, str]] = set()
    for change_node in change_nodes or []:
        nodes[change_node["id"]] = change_node
    for consequence in consequences:
        path = consequence.causal_path or (consequence.subject,)
        for reference in path:
            nodes.setdefault("reference:" + reference, {"id": reference, "kind": "reference", "label": reference})
        edges.update(("causes", path[index], path[index + 1]) for index in range(len(path) - 1))
        action_id = f"action:{consequence.action}:{consequence.subject}"
        nodes[action_id] = {
            "id": action_id,
            "kind": "action",
            "label": consequence.action,
            "action": consequence.action,
            "subject": consequence.subject,
            "status": consequence.status,
        }
        for change_id in consequence.causal_changes:
            edges.add(("causes", path[0], change_id))
            edges.add(("causes", change_id, path[-1]))
        edges.add(("requires", path[-1], action_id))
    graph = {
        "$schema": CONSEQUENCE_SCHEMA,
        "kind": "consequence_graph",
        "nodes": sorted(nodes.values(), key=lambda node: str(node["id"])),
        "edges": [{"kind": kind, "source": source, "target": target} for kind, source, target in sorted(edges)],
    }
    return validate_consequence_graph(graph)


def build_model_consequences(workspace: Workspace, report: CompatibilityReport) -> list[Consequence]:
    """Build consequences for one model transition for native and browser hosts."""
    source_subject = f"{report.domain_name}.{report.model_name}@{report.to_version}"
    change_ids = (
        tuple(_change_node_id(change.kind, change.field_name) for change in report.changes)
        if report.status != "compatible"
        else ()
    )
    consequences = [
        Consequence(
            action=ACTION_RECOMPILE if report.status == "compatible" else ACTION_BREAKING,
            subject=source_subject,
            status=report.status,
            reason="direct contract change",
            causal_path=(f"{report.domain_name}.{report.model_name}@{report.from_version}", source_subject),
            causal_changes=change_ids,
        )
    ]
    consequences.extend(build_enum_consequences(report))
    for dependent in find_dependents(workspace.mdl, report.domain_name, report.model_name, report.from_version):
        projection_impact = analyze_impact(workspace.mdl, report, dependent)
        subject = f"{projection_impact.domain_name}.{projection_impact.projection_name}@{projection_impact.version}"
        consequences.append(
            Consequence(
                action=action_for_projection_status(projection_impact.status),
                subject=subject,
                status=projection_impact.status,
                reason=projection_impact.reason,
                causal_path=(
                    f"{report.domain_name}.{report.model_name}@{report.from_version}",
                    subject,
                ),
                causal_changes=_projection_change_ids(projection_impact.status, projection_impact.reason, report),
            )
        )
    return consequences


def build_enum_consequences(report: CompatibilityReport) -> list[Consequence]:
    """Build review actions implied by declaration-level enum evolution."""
    source_ref = f"{report.domain_name}.{report.model_name}@{report.from_version}"
    target_ref = f"{report.domain_name}.{report.model_name}@{report.to_version}"
    consequences = []
    for change in report.semantic_changes:
        if EXHAUSTIVE_MATCH not in change.consequences:
            continue
        subject = f"enum-exhaustive-match:{report.domain_name}.{report.model_name}:{change.field_name}"
        consequences.append(
            Consequence(
                action=ACTION_CONSUMER_UPDATE,
                subject=subject,
                status="review_required",
                reason=change.note,
                causal_path=(source_ref, target_ref, subject),
                causal_changes=(_change_node_id(change.kind, change.field_name),),
            )
        )
    return consequences


def build_enum_projection_consequences(
    domain_name: str,
    projection_name: str,
    from_version: int,
    to_version: int,
    changes: list[EnumChange],
) -> list[Consequence]:
    """Build direct and consumer-review consequences for an enum projection transition."""
    source_ref = f"{domain_name}.{projection_name}@{from_version}"
    target_ref = f"{domain_name}.{projection_name}@{to_version}"
    status = "breaking" if any(change.breaking for change in changes) else "compatible"
    consequences = [
        Consequence(
            action=ACTION_BREAKING if status == "breaking" else ACTION_RECOMPILE,
            subject=target_ref,
            status=status,
            reason="direct enum projection change",
            causal_path=(source_ref, target_ref),
        )
    ]
    for change in changes:
        for implication in change.consequences:
            if implication == EXHAUSTIVE_MATCH:
                subject = f"enum-exhaustive-match:{target_ref}"
            elif implication == "implicit_growth":
                subject = f"enum-implicit-growth:{target_ref}"
            else:
                continue
            consequences.append(
                Consequence(
                    action=ACTION_CONSUMER_UPDATE,
                    subject=subject,
                    status="review_required",
                    reason=describe_enum_change(change),
                    causal_path=(source_ref, target_ref, subject),
                )
            )
    return consequences


def build_usage_consumer_consequences(
    consequences: list[Consequence], usage_manifests: list[dict[str, object]]
) -> list[Consequence]:
    """Add known compiled-consumer actions from validated usage manifests."""
    consumer_consequences: list[Consequence] = []
    seen: set[tuple[str, str]] = set()
    for manifest in usage_manifests:
        consumer = manifest.get("application_id") or manifest.get("application")
        references = manifest.get("references")
        if not isinstance(consumer, str) or not isinstance(references, list):
            continue
        for reference in references:
            if not isinstance(reference, dict) or not isinstance(reference.get("ref"), str):
                continue
            ref = reference["ref"]
            for consequence in consequences:
                if consequence.status == "compatible" or ref not in consequence.causal_path:
                    continue
                subject_value = reference.get("package_id") or consumer
                if not isinstance(subject_value, str):
                    continue
                key = (subject_value, consequence.subject)
                if key in seen:
                    continue
                seen.add(key)
                path = consequence.causal_path
                if not path or path[-1] != subject_value:
                    path = (*path, subject_value)
                consumer_consequences.append(
                    Consequence(
                        action=ACTION_CONSUMER_UPDATE,
                        subject=subject_value,
                        status=consequence.status,
                        reason="compiled usage manifest",
                        causal_path=path,
                        causal_changes=consequence.causal_changes,
                    )
                )
        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, list):
            continue
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            ref = artifact.get("ref")
            target = artifact.get("target")
            path_value = artifact.get("path")
            if not isinstance(ref, str) or not isinstance(target, str) or not isinstance(path_value, str):
                continue
            artifact_subject = f"generated_artifact:{target}/{path_value}"
            for consequence in consequences:
                if consequence.status == "compatible" or ref not in consequence.causal_path:
                    continue
                key = (artifact_subject, consequence.subject)
                if key in seen:
                    continue
                seen.add(key)
                path = consequence.causal_path
                if not path or path[-1] != artifact_subject:
                    path = (*path, artifact_subject)
                consumer_consequences.append(
                    Consequence(
                        action=ACTION_REGENERATE,
                        subject=artifact_subject,
                        status=consequence.status,
                        reason="generated artifact requires regeneration",
                        causal_path=path,
                        causal_changes=consequence.causal_changes,
                    )
                )
    return consumer_consequences


def build_target_consequences(
    report: CompatibilityReport,
    target_report: TargetCompatibilityReport,
) -> list[Consequence]:
    """Turn target-evaluator findings into graph consequences for one model change."""
    source_ref = f"{report.domain_name}.{report.model_name}@{report.from_version}"
    target_ref = f"{report.domain_name}.{report.model_name}@{report.to_version}"
    consequences = []
    for finding in target_report.findings:
        subject = f"{target_report.target}:{finding.ref}:{finding.code}"
        change_ids = tuple(
            _change_node_id(change.kind, change.field_name)
            for change in report.storage_changes
            if finding.field == change.field_name or finding.index == change.field_name
        )
        consequences.append(
            Consequence(
                action=_action_for_target_finding(finding.axis, finding.severity),
                subject=subject,
                status=finding.severity,
                reason=finding.message,
                causal_path=(source_ref, target_ref, subject),
                causal_changes=change_ids,
            )
        )
    return consequences


def build_standalone_target_consequences(
    report: TargetCompatibilityReport,
    *,
    source_ref: str,
    target_ref: str,
) -> list[Consequence]:
    """Build graph consequences when no semantic model report is available."""
    consequences = []
    for finding in report.findings:
        subject = f"{report.target}:{finding.ref}:{finding.code}"
        consequences.append(
            Consequence(
                action=_action_for_target_finding(finding.axis, finding.severity),
                subject=subject,
                status=finding.severity,
                reason=finding.message,
                causal_path=(source_ref, target_ref, subject),
            )
        )
    return consequences


def build_profile_consequences(
    report: TargetCompatibilityReport,
    profile: CompatibilityProfile,
    policy_result: EnforcementResult,
) -> list[Consequence]:
    """Turn a failed named compatibility profile into a review action."""
    if policy_result.passed:
        return []
    blocking_codes = {
        id(finding): f"{report.target}:{finding.ref}:{finding.code}" for finding in policy_result.blocking_findings
    }
    blocking_refs = tuple(blocking_codes[id(finding)] for finding in report.findings if id(finding) in blocking_codes)
    subject = f"compatibility-profile:{profile.name}"
    target_ref = f"{report.target}:to"
    path = (target_ref, *blocking_refs, subject)
    severity_rank = {severity: rank for rank, severity in enumerate(SEVERITIES)}
    status = max(policy_result.blocking_findings, key=lambda finding: severity_rank[finding.severity]).severity
    return [
        Consequence(
            action=ACTION_GOVERNANCE_REVIEW,
            subject=subject,
            status=status,
            reason=f"named profile requires {profile.requirement} compatibility",
            causal_path=path,
        )
    ]


def build_profile_usage_consequences(
    report: TargetCompatibilityReport,
    policy_result: EnforcementResult,
    usage_manifests: list[dict[str, object]],
) -> list[Consequence]:
    """Attach known compiled consumers to findings blocked by a profile."""
    if policy_result.passed:
        return []
    blocking = set(policy_result.blocking_findings)
    consequences: list[Consequence] = []
    seen: set[tuple[str, str]] = set()
    for manifest in usage_manifests:
        consumer = manifest.get("application_id") or manifest.get("application")
        references = manifest.get("references")
        if not isinstance(consumer, str) or not isinstance(references, list):
            continue
        for reference in references:
            if not isinstance(reference, dict) or not isinstance(reference.get("ref"), str):
                continue
            reference_base = reference["ref"].split("@", 1)[0]
            fields = reference.get("fields")
            for finding in report.findings:
                if finding not in blocking or (
                    reference_base != finding.ref.split("@", 1)[0]
                    and not (isinstance(fields, list) and finding.field is not None and finding.field in fields)
                ):
                    continue
                subject = f"{report.target}:{finding.ref}:{finding.code}"
                key = (consumer, subject)
                if key in seen:
                    continue
                seen.add(key)
                consequences.append(
                    Consequence(
                        action=ACTION_CONSUMER_UPDATE,
                        subject=consumer,
                        status=finding.severity,
                        reason="known compiled consumer is covered by a failed compatibility profile",
                        causal_path=(f"{report.target}:to", subject, consumer),
                    )
                )
    return consequences


def build_projection_consequences(
    report: ProjectionCompatibilityReport,
    target_report: TargetCompatibilityReport,
) -> list[Consequence]:
    """Build direct and target consequences for one projection transition."""
    source_ref = f"{report.domain_name}.{report.projection_name}@{report.from_version}"
    target_ref = f"{report.domain_name}.{report.projection_name}@{report.to_version}"
    consequences = [
        Consequence(
            action=ACTION_BREAKING if report.status == "breaking" else ACTION_RECOMPILE,
            subject=target_ref,
            status=report.status,
            reason="direct projection change",
            causal_path=(source_ref, target_ref),
            causal_changes=(
                tuple(_projection_change_node_id(change) for change in report.changes)
                if report.status == "breaking"
                else ()
            ),
        )
    ]
    for finding in target_report.findings:
        subject = f"{target_report.target}:{finding.ref}:{finding.code}"
        change_ids = tuple(
            _projection_change_node_id(change) for change in report.changes if finding.field == change.field_name
        )
        consequences.append(
            Consequence(
                action=_action_for_target_finding(finding.axis, finding.severity),
                subject=subject,
                status=finding.severity,
                reason=finding.message,
                causal_path=(source_ref, target_ref, subject),
                causal_changes=change_ids,
            )
        )
    return consequences


def change_nodes_for_report(report: CompatibilityReport) -> list[dict[str, object]]:
    changes = (
        report.semantic_changes
        if report.status != "compatible"
        else [change for change in report.semantic_changes if change.consequences]
    )
    changes = [*changes, *report.storage_changes]
    return [
        {
            "id": _change_node_id(change.kind, change.field_name),
            "kind": "change",
            "change_kind": change.kind,
            "field": change.field_name,
        }
        for change in changes
    ]


def projection_change_nodes(report: ProjectionCompatibilityReport) -> list[dict[str, object]]:
    return [
        {
            "id": _projection_change_node_id(change),
            "kind": "change",
            "change_kind": change.kind,
            "field": change.field_name or "<projection>",
        }
        for change in report.changes
    ]


def _change_node_id(change_kind: str, field_name: str) -> str:
    return f"change:{change_kind}:{field_name}"


def _projection_change_node_id(change: ProjectionChange) -> str:
    return _change_node_id(change.kind, change.field_name or "<projection>")


def _projection_change_ids(status: str, reason: str | None, report: CompatibilityReport) -> tuple[str, ...]:
    if status == "compatible":
        return ()
    if reason is None or reason == "unresolved projection" or "marked breaking" in reason:
        return tuple(_change_node_id(change.kind, change.field_name) for change in report.changes)
    return tuple(
        _change_node_id(change.kind, change.field_name)
        for change in report.changes
        if f"field '{change.field_name}'" in reason
    )


def _action_for_target_finding(axis: str, severity: str) -> str:
    if severity == "breaking":
        return ACTION_BREAKING
    if axis == "data_backfill":
        return ACTION_DATA_BACKFILL
    if axis == "storage_migration":
        return ACTION_STORAGE_MIGRATION
    if axis == "projection_rebuild":
        return ACTION_PROJECTION_REBUILD
    if axis == "governance_review":
        return ACTION_GOVERNANCE_REVIEW
    return ACTION_RECOMPILE


def action_for_projection_status(status: str) -> str:
    if status == "broken":
        return ACTION_BREAKING
    if status == "affected":
        return ACTION_REGENERATE
    return ACTION_NO_ACTION
