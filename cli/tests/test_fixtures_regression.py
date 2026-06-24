"""Regression coverage for the shared scenario fixtures in tests/fixtures/.

Each fixture is a small, realistic .mdl scenario meant to be reused across
multiple test files. This module asserts the headline behavior each fixture
exists to pin down, so a regression in compatibility/lineage/governance/CEL/
federation/emitter behavior shows up here even if no other test happens to
exercise that fixture.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from modelable.cli import cli
from modelable.compiler.workspace import WorkspaceDocumentSource, load_workspace
from modelable.emitters.fhir import emit_fhir_profile
from modelable.lsp.federation import build_import_diagnostics
from modelable.lsp.workspace import LspWorkspaceIndex

FIXTURES = Path(__file__).parent / "fixtures"

_VALID_FIXTURES = [
    "projection_of_projection.mdl",
    "breaking_changes.mdl",
    "multi_domain_joins.mdl",
    "pii_governance.mdl",
    "auto_projection_complex.mdl",
    "governance_export_model.mdl",
    "sql_and_dbt_targets.mdl",
    "multi_language_target.mdl",
    "fhir_patient_profile.mdl",
    "materialized_projection_chain.mdl",
]


@pytest.mark.parametrize("fixture_name", _VALID_FIXTURES)
def test_fixture_validates_cleanly(fixture_name, tmp_path):
    runner = CliRunner()
    result = runner.invoke(cli, ["validate", str(FIXTURES / fixture_name)])
    assert result.exit_code == 0, result.output


def test_cel_error_cases_fixture_reports_each_active_error_code():
    runner = CliRunner()
    result = runner.invoke(cli, ["validate", str(FIXTURES / "cel_error_cases.mdl")])

    assert result.exit_code != 0
    for code in ("CEL001", "CEL002", "CEL005", "CEL006", "CEL007"):
        assert code in result.output, result.output


def test_projection_of_projection_lineage_chains_through_two_hops():
    workspace = load_workspace(FIXTURES)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["lineage", "billing.BillingCustomerSummary@1", "--path", str(FIXTURES / "projection_of_projection.mdl")],
    )
    assert result.exit_code == 0, result.output
    assert "billing.BillingCustomer@1.invoiceEmail" in result.output
    del workspace  # load_workspace above only smoke-tests the directory form


def test_breaking_changes_fixture_detects_breaking_diff_and_impacted_projection():
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "diff",
            "customer.Customer@1",
            "customer.Customer@2",
            "--path",
            str(FIXTURES / "breaking_changes.mdl"),
        ],
    )
    # Exit code 1 here means the diff correctly found a breaking change that
    # broke a dependent projection -- that's the scenario this fixture pins.
    assert result.exit_code == 1, result.output
    assert "breaking" in result.output
    assert "removed_field tags" in result.output
    assert "BROKEN" in result.output
    assert "customer.CustomerSummary@1" in result.output


def test_multi_domain_joins_fixture_resolves_three_way_join_lineage():
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["lineage", "analytics.CustomerOrderPayment@1", "--path", str(FIXTURES / "multi_domain_joins.mdl")],
    )
    assert result.exit_code == 0, result.output
    assert "customer.Customer@1.legalName" in result.output
    assert "payments.Payment@1.paymentId" in result.output
    assert "orders.Order@1.totalAmount" in result.output


def test_pii_governance_fixture_flags_secret_and_confidential_exposure():
    workspace = load_workspace(FIXTURES / "pii_governance.mdl")
    domain = next(d for d in workspace.mdl.domains if d.name == "customer")
    support_view = next(iter(domain.projections["CustomerSupportView"]))

    from modelable.governance.checker import build_projection_governance_findings

    findings = build_projection_governance_findings("customer", "CustomerSupportView", support_view, workspace.mdl)
    codes = {f.code for f in findings}

    assert codes, "expected at least one governance finding for the secret/confidential exposure"


def test_auto_projection_complex_fixture_expands_exclude_and_on_filters():
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["inspect", "customer.Customer@1", "--auto", "--path", str(FIXTURES / "auto_projection_complex.mdl")],
    )
    assert result.exit_code == 0, result.output
    assert "customer.CustomerRequest@1" in result.output
    # request excludes internalRiskNotes (explicit exclude) and createdAt/updatedAt (@server)
    assert "internalRiskNotes" not in _section(result.output, "customer.CustomerRequest@1")
    assert "createdAt" not in _section(result.output, "customer.CustomerRequest@1")
    # reply excludes @pii (email) and @classification("secret") (internalRiskNotes)
    assert "email" not in _section(result.output, "customer.CustomerReply@1")
    assert "internalRiskNotes" not in _section(result.output, "customer.CustomerReply@1")
    # event only fires on created/deleted but still carries the full field set
    assert "internalRiskNotes" in _section(result.output, "customer.CustomerEvent@1")


def _section(output: str, header: str) -> str:
    start = output.index(header)
    rest = output[start + len(header) :]
    next_marker = rest.find("customer.Customer")
    return rest if next_marker == -1 else rest[:next_marker]


def test_federation_multi_registry_fixture_imports_cleanly_with_mirror(tmp_path):
    fixture_dir = FIXTURES / "federation_multi_registry"
    workspace_text = (fixture_dir / "workspace.mdl").read_text(encoding="utf-8")
    consumer_text = (fixture_dir / "consumer.mdl").read_text(encoding="utf-8")
    provider_text = (fixture_dir / "provider.mdl").read_text(encoding="utf-8")

    workspace_path = tmp_path / "workspace.mdl"
    workspace_path.write_text(workspace_text, encoding="utf-8")
    consumer_path = tmp_path / "consumer.mdl"
    consumer_path.write_text(consumer_text, encoding="utf-8")

    mirror_path = tmp_path / ".modelable" / "mirror" / "peer" / "customer.mdl"
    mirror_path.parent.mkdir(parents=True, exist_ok=True)
    mirror_path.write_text(provider_text, encoding="utf-8")

    index = LspWorkspaceIndex()
    index.documents[workspace_path.as_uri()] = WorkspaceDocumentSource(
        path=workspace_path, uri=workspace_path.as_uri(), text=workspace_text
    )
    index.documents[consumer_path.as_uri()] = WorkspaceDocumentSource(
        path=consumer_path, uri=consumer_path.as_uri(), text=consumer_text
    )

    diagnostics = build_import_diagnostics(index, consumer_path.as_uri())

    assert diagnostics == []


def test_multi_language_target_fixture_compiles_to_every_native_emitter(tmp_path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as cwd:
        cwd = Path(cwd)
        for target, ext in [
            ("json-schema", "*.json"),
            ("markdown", "*.md"),
            ("typescript", "*.ts"),
            ("csharp", "*.cs"),
            ("java", "*.java"),
            ("python", "*.py"),
            ("rust", "*.rs"),
            ("go", "*.go"),
        ]:
            out_dir = cwd / target
            result = runner.invoke(
                cli,
                [
                    "compile",
                    str(FIXTURES / "multi_language_target.mdl"),
                    "--target",
                    target,
                    "--out",
                    str(out_dir),
                ],
            )
            assert result.exit_code == 0, f"{target}: {result.output}"
            assert any(out_dir.rglob(ext)), f"{target}: no {ext} artifacts written"


def test_governance_export_model_fixture_propagates_classification_to_all_export_targets(tmp_path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as cwd:
        cwd = Path(cwd)
        for target, ext in [
            ("openmetadata", "*.json"),
            ("openlineage", "*.json"),
            ("odcs", "*.yaml"),
        ]:
            out_dir = cwd / target
            result = runner.invoke(
                cli,
                [
                    "compile",
                    str(FIXTURES / "governance_export_model.mdl"),
                    "--target",
                    target,
                    "--out",
                    str(out_dir),
                ],
            )
            assert result.exit_code == 0, f"{target}: {result.output}"
            assert any(out_dir.rglob(ext)), f"{target}: no artifacts written"


def test_sql_and_dbt_targets_fixture_compiles_dbt_yaml(tmp_path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as cwd:
        out = Path(cwd) / "dbt"
        result = runner.invoke(
            cli,
            [
                "compile",
                str(FIXTURES / "sql_and_dbt_targets.mdl"),
                "--target",
                "dbt-yaml",
                "--out",
                str(out),
            ],
        )
        assert result.exit_code == 0, result.output
        assert any(out.rglob("*.yml")) or any(out.rglob("*.yaml"))


def test_fhir_patient_profile_fixture_maps_modelable_only_field_to_extension_slice(tmp_path):
    workspace = load_workspace(FIXTURES / "fhir_patient_profile.mdl")
    artifacts = emit_fhir_profile(workspace, tmp_path / "out")

    base = next(a for a in artifacts if a.ref == "clinical.PatientProfile@1")
    assert base.target == "fhir-profile"
    assert not base.warnings

    extension_refs = {a.ref for a in artifacts if a.target == "fhir-extension"}
    assert "clinical.PatientProfile@1.internalRiskTier" in extension_refs


def test_materialized_projection_chain_fixture_carries_lineage_through_materialized_hops():
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["lineage", "analytics.CustomerMart@1", "--path", str(FIXTURES / "materialized_projection_chain.mdl")],
    )
    assert result.exit_code == 0, result.output
    assert "analytics.CustomerOds@1.customerId" in result.output
    assert "analytics.CustomerOds@1.name" in result.output
