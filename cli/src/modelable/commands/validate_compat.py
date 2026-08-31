from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import click

from modelable.commands.common import console, load_workspace_or_exit
from modelable.compat.policy import EnforcementResult, load_policy
from modelable.compat.targets import (
    PASSING_STATUSES,
    TargetCompatibilityReport,
    compare_avro_artifacts,
    compare_fhir_artifacts,
    compare_grpc_artifacts,
    compare_json_schema_artifacts,
    compare_odcs_artifacts,
    compare_openapi_artifacts,
    compare_protobuf_manifests,
    compare_sql_artifacts,
)
from modelable.consequence import build_consequence_graph, build_standalone_target_consequences
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
from modelable.planner.protocol import PLAN_SCHEMA


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
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
def validate_compat(from_path: Path, to_path: Path, target: str, policy_path: Path | None, output_format: str) -> None:
    """Validate target-specific compatibility between two Modelable workspaces."""
    old_workspace = load_workspace_or_exit(from_path)
    new_workspace = load_workspace_or_exit(to_path)

    try:
        target_descriptor = get_codegen_target(target).extension_descriptor()
        validate_extension_admission(
            target_descriptor,
            old_workspace.mdl,
            plan_version=PLAN_SCHEMA,
            require_compatibility_support=True,
        )
        validate_extension_admission(
            target_descriptor,
            new_workspace.mdl,
            plan_version=PLAN_SCHEMA,
            require_compatibility_support=True,
        )
    except ExtensionDescriptorError as error:
        raise click.ClickException(str(error)) from error

    if target == "fhir-profile":
        report = compare_fhir_artifacts(
            emit_fhir_profile(old_workspace, Path(".modelable/compat/old/fhir-profile")),
            emit_fhir_profile(new_workspace, Path(".modelable/compat/new/fhir-profile")),
        )
    elif target == "odcs":
        report = compare_odcs_artifacts(
            emit_odcs(old_workspace, Path(".modelable/compat/old/odcs")),
            emit_odcs(new_workspace, Path(".modelable/compat/new/odcs")),
        )
    elif target in {"sql-postgres", "sql-clickhouse"}:
        dialect = target.removeprefix("sql-")
        report = compare_sql_artifacts(
            emit_sql(old_workspace, Path(f".modelable/compat/old/{target}"), dialect),
            emit_sql(new_workspace, Path(f".modelable/compat/new/{target}"), dialect),
            target=target,
        )
    elif target == "json-schema":
        report = compare_json_schema_artifacts(
            emit_json_schema(old_workspace, Path(".modelable/compat/old/json-schema")),
            emit_json_schema(new_workspace, Path(".modelable/compat/new/json-schema")),
        )
    elif target == "avro":
        report = compare_avro_artifacts(
            emit_avro(old_workspace, Path(".modelable/compat/old/avro")),
            emit_avro(new_workspace, Path(".modelable/compat/new/avro")),
        )
    elif target == "protobuf":
        report = compare_protobuf_manifests(
            emit_protobuf(old_workspace, Path(".modelable/compat/old/protobuf")),
            emit_protobuf(new_workspace, Path(".modelable/compat/new/protobuf")),
        )
    elif target == "grpc":
        report = compare_grpc_artifacts(
            emit_grpc(old_workspace, Path(".modelable/compat/old/grpc")),
            emit_grpc(new_workspace, Path(".modelable/compat/new/grpc")),
        )
    else:
        report = compare_openapi_artifacts(
            emit_openapi(old_workspace, Path(".modelable/compat/old/openapi")),
            emit_openapi(new_workspace, Path(".modelable/compat/new/openapi")),
        )

    policy_result: EnforcementResult | None = None
    if policy_path is not None:
        try:
            policy = load_policy(policy_path)
            policy_result = policy.enforce(report)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc

    if output_format == "json":
        consequences = build_standalone_target_consequences(
            report,
            source_ref=f"{report.target}:from",
            target_ref=f"{report.target}:to",
        )
        payload = {
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
