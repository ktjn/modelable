from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import click

from modelable.commands.common import console, load_workspace_or_exit
from modelable.compat.diff import compare_model_versions
from modelable.compat.policy import CompatibilityProfile, EnforcementResult, load_policy
from modelable.compat.targets import (
    PASSING_STATUSES,
    SEVERITIES,
    TargetCompatibilityReport,
    compare_avro_artifacts,
    compare_fhir_artifacts,
    compare_grpc_artifacts,
    compare_json_schema_artifacts,
    compare_odcs_artifacts,
    compare_openapi_artifacts,
    compare_protobuf_manifests,
    compare_source_representation,
    compare_sql_artifacts,
)
from modelable.compiler.workspace import Workspace
from modelable.consequence import (
    build_consequence_graph,
    build_profile_consequences,
    build_profile_usage_consequences,
    build_standalone_target_consequences,
)
from modelable.emitters.avro import emit_avro
from modelable.emitters.fhir import emit_fhir_profile
from modelable.emitters.grpc import emit_grpc
from modelable.emitters.json_schema import emit_json_schema
from modelable.emitters.odcs import emit_odcs
from modelable.emitters.openapi import emit_openapi
from modelable.emitters.protobuf import emit_protobuf
from modelable.emitters.sql import emit_sql
from modelable.emitters.targets import get_codegen_target, list_compat_checkable_targets
from modelable.extensions import ExtensionDescriptorError, validate_extension_admission
from modelable.planner.protocol import PLAN_V1_SCHEMA
from modelable.registry.usage_protocol import UsageProtocolError, load_usage_manifest


def register_validate_compat_commands(cli_group: click.Group) -> None:
    cli_group.add_command(validate_compat)


@click.command("validate-compat")
@click.option("--from", "from_path", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--to", "to_path", type=click.Path(exists=True, path_type=Path), required=True)
@click.option(
    "--target",
    type=click.Choice([target.name for target in list_compat_checkable_targets()]),
    required=True,
)
@click.option(
    "--policy",
    "policy_path",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Path to a compatibility policy YAML file (Slice C4). Without it, "
    "every non-compatible finding fails, matching the default behavior.",
)
@click.option(
    "--profile",
    "profile_name",
    default=None,
    help="Named profile from --policy; evaluates its target and direction requirements.",
)
@click.option(
    "--usage-manifest",
    "usage_manifest_paths",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    multiple=True,
    help="Compiled-consumer usage manifest for profile consequence analysis (repeatable).",
)
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
def validate_compat(
    from_path: Path,
    to_path: Path,
    target: str,
    policy_path: Path | None,
    profile_name: str | None,
    usage_manifest_paths: tuple[Path, ...],
    output_format: str,
) -> None:
    """Validate target-specific compatibility between two Modelable workspaces."""
    old_workspace = load_workspace_or_exit(from_path)
    new_workspace = load_workspace_or_exit(to_path)
    try:
        usage_manifests = [load_usage_manifest(path) for path in usage_manifest_paths]
    except (OSError, UnicodeDecodeError, UsageProtocolError, ValueError) as exc:
        raise click.ClickException(f"cannot load usage manifest: {exc}") from exc

    try:
        target_descriptor = get_codegen_target(target).extension_descriptor()
        validate_extension_admission(
            target_descriptor,
            old_workspace.mdl,
            plan_version=PLAN_V1_SCHEMA,
            require_compatibility_support=True,
        )
        validate_extension_admission(
            target_descriptor,
            new_workspace.mdl,
            plan_version=PLAN_V1_SCHEMA,
            require_compatibility_support=True,
        )
    except ExtensionDescriptorError as error:
        raise click.ClickException(str(error)) from error

    report = _compare_target(old_workspace, new_workspace, target, "old", "new")

    policy_result: EnforcementResult | None = None
    selected_profile: CompatibilityProfile | None = None
    if profile_name is not None:
        if policy_path is None:
            raise click.ClickException("--profile requires --policy")
        try:
            policy = load_policy(policy_path)
            selected_profile = policy.profile_for(profile_name)
            if target not in selected_profile.targets:
                raise ValueError(f"compatibility profile {profile_name!r} does not include target {target!r}")
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
        if selected_profile.requirement == "forward":
            report = _compare_target(new_workspace, old_workspace, target, "forward-new", "forward-old")
            report = _merge_reports(report, _compare_semantic_workspaces(new_workspace, old_workspace))
        elif selected_profile.requirement == "full":
            reverse = _compare_target(new_workspace, old_workspace, target, "full-new", "full-old")
            report = _merge_reports(report, reverse)
            semantic = _compare_semantic_workspaces(old_workspace, new_workspace)
            reverse_semantic = _compare_semantic_workspaces(new_workspace, old_workspace)
            report = _merge_reports(report, _merge_reports(semantic, reverse_semantic))
        else:
            report = _merge_reports(report, _compare_semantic_workspaces(old_workspace, new_workspace))
    if policy_path is not None:
        try:
            policy = load_policy(policy_path)
            policy_result = policy.enforce(report, profile=selected_profile)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc

    if output_format == "json":
        consequences = build_standalone_target_consequences(
            report,
            source_ref=f"{report.target}:from",
            target_ref=f"{report.target}:to",
        )
        if selected_profile is not None and policy_result is not None:
            consequences.extend(build_profile_consequences(report, selected_profile, policy_result))
            consequences.extend(build_profile_usage_consequences(report, policy_result, usage_manifests))
        payload: dict[str, Any] = {
            "kind": "target_consequence_report",
            "target": report.target,
            "status": report.status,
            "severity": report.severity,
            "findings": [dataclasses.asdict(finding) for finding in report.findings],
            "consequences": [consequence.as_dict() for consequence in consequences],
            "consequence_graph": build_consequence_graph(consequences),
        }
        if policy_result is not None:
            payload["policy"] = {
                "target": policy_result.target,
                "threshold": policy_result.threshold,
                "passed": policy_result.passed,
                "blocking_findings": [dataclasses.asdict(finding) for finding in policy_result.blocking_findings],
            }
            if selected_profile is not None:
                payload["policy"]["profile"] = selected_profile.name
                payload["policy"]["requirement"] = selected_profile.requirement
        click.echo(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _render_report(report)
        if policy_result is not None:
            _render_policy_result(policy_result)

    if policy_result is not None:
        if not policy_result.passed:
            raise click.exceptions.Exit(1)
        return

    if report.status not in PASSING_STATUSES:
        raise click.exceptions.Exit(1)


def _compare_target(
    old_workspace: Workspace, new_workspace: Workspace, target: str, old_label: str, new_label: str
) -> TargetCompatibilityReport:
    old_root = Path(".modelable/compat") / old_label
    new_root = Path(".modelable/compat") / new_label
    if target == "fhir-profile":
        return compare_fhir_artifacts(
            emit_fhir_profile(old_workspace, old_root / target), emit_fhir_profile(new_workspace, new_root / target)
        )
    if target == "odcs":
        return compare_odcs_artifacts(
            emit_odcs(old_workspace, old_root / target), emit_odcs(new_workspace, new_root / target)
        )
    if target in {"sql-postgres", "sql-clickhouse"}:
        dialect = target.removeprefix("sql-")
        return compare_sql_artifacts(
            emit_sql(old_workspace, old_root / target, dialect),
            emit_sql(new_workspace, new_root / target, dialect),
            target=target,
        )
    if target == "json-schema":
        return compare_json_schema_artifacts(
            emit_json_schema(old_workspace, old_root / target), emit_json_schema(new_workspace, new_root / target)
        )
    if target == "avro":
        return compare_avro_artifacts(
            emit_avro(old_workspace, old_root / target), emit_avro(new_workspace, new_root / target)
        )
    if target == "protobuf":
        return compare_protobuf_manifests(
            emit_protobuf(old_workspace, old_root / target), emit_protobuf(new_workspace, new_root / target)
        )
    if target == "grpc":
        return compare_grpc_artifacts(
            emit_grpc(old_workspace, old_root / target), emit_grpc(new_workspace, new_root / target)
        )
    return compare_openapi_artifacts(
        emit_openapi(old_workspace, old_root / target), emit_openapi(new_workspace, new_root / target)
    )


def _merge_reports(first: TargetCompatibilityReport, second: TargetCompatibilityReport) -> TargetCompatibilityReport:
    severities = [first.severity, second.severity]
    worst = max(severities, key=SEVERITIES.index)
    findings = sorted(
        [*first.findings, *second.findings],
        key=lambda finding: (finding.code, finding.ref, finding.field or "", finding.index or "", finding.message),
    )
    return TargetCompatibilityReport(target=first.target, status=worst, severity=worst, findings=findings)


def _compare_semantic_workspaces(old_workspace: Workspace, new_workspace: Workspace) -> TargetCompatibilityReport:
    """Compare matching model declarations for named profile evaluation."""
    reports: list[TargetCompatibilityReport] = []
    new_domains = {domain.name: domain for domain in new_workspace.mdl.domains}
    for old_domain in old_workspace.mdl.domains:
        new_domain = new_domains.get(old_domain.name)
        if new_domain is None:
            continue
        for model_name in sorted(set(old_domain.models) & set(new_domain.models)):
            old_versions = old_domain.models[model_name]
            new_versions = new_domain.models[model_name]
            if not old_versions or not new_versions:
                continue
            old_version = max(old_versions, key=lambda version: version.version)
            new_version = max(new_versions, key=lambda version: version.version)
            changes = compare_model_versions(old_version, new_version)
            reports.append(compare_source_representation(old_domain.name, model_name, changes, target="source"))
    if not reports:
        return TargetCompatibilityReport(target="source", status="compatible", severity="compatible", findings=[])
    merged = reports[0]
    for report in reports[1:]:
        merged = _merge_reports(merged, report)
    return merged


def _render_report(report: TargetCompatibilityReport) -> None:
    console.print(f"target: {report.target}", markup=False)
    console.print(f"status: {report.status}", markup=False)
    if not report.findings:
        console.print("- no target compatibility findings", markup=False)
        return

    for finding in report.findings:
        subject = finding.field or finding.index or finding.ref
        console.print(
            f"- [{finding.status}] {finding.code}: {subject}: {finding.message}",
            markup=False,
        )


def _render_policy_result(result: EnforcementResult) -> None:
    outcome = "pass" if result.passed else "fail"
    console.print(f"policy: threshold={result.threshold} -> {outcome}", markup=False)
    for finding in result.blocking_findings:
        subject = finding.field or finding.index or finding.ref
        console.print(
            f"- [blocking:{finding.severity}] {finding.code}: {subject}: {finding.message}",
            markup=False,
        )
