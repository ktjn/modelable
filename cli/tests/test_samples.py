from pathlib import Path

from click.testing import CliRunner

from modelable.cli import cli
from modelable.parser.parse import parse_file


def test_mvp_smoke_validates_and_compiles_all_phase_1_targets(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    sample_path = repo_root / "samples" / "mvp"
    runner = CliRunner()

    with runner.isolated_filesystem(temp_dir=tmp_path) as cwd:
        cwd = Path(cwd)
        validate_result = runner.invoke(cli, ["validate", str(sample_path), "--strict"])
        assert validate_result.exit_code == 0, validate_result.output

        jsonschema_out = cwd / "dist" / "jsonschema"
        markdown_out = cwd / "dist" / "docs"
        typescript_out = cwd / "dist" / "types"

        jsonschema_result = runner.invoke(
            cli,
            ["compile", str(sample_path), "--target", "json-schema", "--out", str(jsonschema_out)],
        )
        assert jsonschema_result.exit_code == 0, jsonschema_result.output
        assert (cwd / ".modelable" / "registry.db").exists()
        assert jsonschema_out.exists()

        markdown_result = runner.invoke(
            cli,
            ["compile", str(sample_path), "--target", "markdown", "--out", str(markdown_out)],
        )
        assert markdown_result.exit_code == 0, markdown_result.output
        assert markdown_out.exists()
        assert any(markdown_out.glob("*.md"))

        typescript_result = runner.invoke(
            cli,
            ["compile", str(sample_path), "--target", "typescript", "--out", str(typescript_out)],
        )
        assert typescript_result.exit_code == 0, typescript_result.output
        assert typescript_out.exists()
        assert any(typescript_out.glob("*.ts"))

        csharp_out = cwd / "dist" / "csharp"
        java_out = cwd / "dist" / "java"
        python_out = cwd / "dist" / "python"
        rust_out = cwd / "dist" / "rust"
        go_out = cwd / "dist" / "go"

        csharp_result = runner.invoke(
            cli,
            ["compile", str(sample_path), "--target", "csharp", "--out", str(csharp_out)],
        )
        assert csharp_result.exit_code == 0, csharp_result.output
        assert csharp_out.exists()
        assert any(csharp_out.rglob("*.cs"))

        java_result = runner.invoke(
            cli,
            ["compile", str(sample_path), "--target", "java", "--out", str(java_out)],
        )
        assert java_result.exit_code == 0, java_result.output
        assert java_out.exists()
        assert any(java_out.rglob("*.java"))

        python_result = runner.invoke(
            cli,
            ["compile", str(sample_path), "--target", "python", "--out", str(python_out)],
        )
        assert python_result.exit_code == 0, python_result.output
        assert python_out.exists()
        assert any(python_out.rglob("*.py"))

        rust_result = runner.invoke(
            cli,
            ["compile", str(sample_path), "--target", "rust", "--out", str(rust_out)],
        )
        assert rust_result.exit_code == 0, rust_result.output
        assert rust_out.exists()
        assert any(rust_out.rglob("*.rs"))

        go_result = runner.invoke(
            cli,
            ["compile", str(sample_path), "--target", "go", "--out", str(go_out)],
        )
        assert go_result.exit_code == 0, go_result.output
        assert go_out.exists()
        assert any(go_out.rglob("*.go"))

        docs_out = cwd / "dist" / "docs-wrapper"
        docs_result = runner.invoke(
            cli,
            ["docs", str(sample_path), "--out", str(docs_out)],
        )
        assert docs_result.exit_code == 0, docs_result.output
        assert docs_out.exists()
        assert any(docs_out.glob("*.md"))

        inspect_result = runner.invoke(
            cli,
            ["inspect", "customer.Customer@2", "--auto", "--path", str(sample_path)],
        )
        assert inspect_result.exit_code == 0, inspect_result.output
        assert "customer.CustomerDb@2" in inspect_result.output
        assert "customer.CustomerReply@2" in inspect_result.output
        assert "customer.CustomerEvent@2" in inspect_result.output
        assert "legalName" in inspect_result.output
        assert "email" in inspect_result.output

        resolve_result = runner.invoke(
            cli,
            ["resolve", "customer.Customer@2", "--path", str(sample_path)],
        )
        assert resolve_result.exit_code == 0, resolve_result.output
        assert "entity Customer @ 2" in resolve_result.output

        lineage_result = runner.invoke(
            cli,
            ["lineage", "billing.BillingCustomer@1", "--path", str(sample_path)],
        )
        assert lineage_result.exit_code == 0, lineage_result.output
        assert "billing.BillingCustomer@1" in lineage_result.output
        assert "invoiceEmail" in lineage_result.output


def test_all_sample_files_parse():
    repo_root = Path(__file__).resolve().parents[2]
    sample_files = sorted(repo_root.glob("samples/**/*.mdl"))

    assert sample_files, "expected at least one .mdl sample file"

    for sample_file in sample_files:
        tree = parse_file(sample_file)
        assert tree.data == "start", sample_file


# Scenarios with known intentional SEM errors (event @key, missing aggregate key).
# Any CEL error reaching this set means a new function/syntax needs adding to the validator.
_KNOWN_SEM_ONLY_ERRORS = {
    "01-ecommerce-data-warehouse",
    "03-order-saga-microservices",
    "04-credit-risk-feature-store",
    "05-partner-marketplace-api",
    "06-gdpr-compliance-audit",
    "07-multi-system-master-data",
    "08-distributed-multi-registry",
}


def test_all_scenarios_have_no_cel_errors():
    """CEL errors in any scenario mean the validator is missing a function or syntax form."""
    from modelable.compiler.workspace import load_workspace

    repo_root = Path(__file__).resolve().parents[2]
    scenarios = sorted((repo_root / "samples" / "scenarios").iterdir())

    assert scenarios, "expected at least one scenario directory"

    cel_failures: list[str] = []
    for scenario in scenarios:
        if not scenario.is_dir():
            continue
        try:
            ws = load_workspace(scenario)
        except Exception as exc:
            cel_failures.append(f"{scenario.name}: load error: {exc}")
            continue
        for diag in ws.errors:
            if diag.code == "CEL":
                cel_failures.append(f"{scenario.name}: {diag.message}")

    assert cel_failures == [], "\n".join(cel_failures)


def test_all_scenarios_sem_errors_are_known():
    """Any new SEM error in a scenario that previously had none is a regression."""
    from modelable.compiler.workspace import load_workspace

    repo_root = Path(__file__).resolve().parents[2]
    scenarios = sorted((repo_root / "samples" / "scenarios").iterdir())

    unexpected: list[str] = []
    for scenario in scenarios:
        if not scenario.is_dir():
            continue
        try:
            ws = load_workspace(scenario)
        except Exception as exc:
            unexpected.append(f"{scenario.name}: load error: {exc}")
            continue
        if scenario.name not in _KNOWN_SEM_ONLY_ERRORS:
            for diag in ws.errors:
                if diag.code == "SEM":
                    unexpected.append(f"{scenario.name}: {diag.message}")

    assert unexpected == [], "\n".join(unexpected)


def test_auto_projection_scenario_validates_cleanly():
    repo_root = Path(__file__).resolve().parents[2]
    sample_path = repo_root / "samples" / "scenarios" / "09-auto-projections"
    runner = CliRunner()

    result = runner.invoke(cli, ["validate", str(sample_path)])

    # Connector bindings (no model ref) and model bindings are both parsed without
    # model-reference validation errors — the binding grammar treats all binding
    # bodies as opaque content, so no false "invalid model reference" errors fire.
    assert result.exit_code == 0, result.output
    assert "invalid model reference" not in result.output


def test_ecommerce_scenario_reports_validation_gaps_and_compiles_targets(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    sample_path = repo_root / "samples" / "scenarios" / "01-ecommerce-data-warehouse"
    runner = CliRunner()

    with runner.isolated_filesystem(temp_dir=tmp_path) as cwd:
        cwd = Path(cwd)
        validate_result = runner.invoke(cli, ["validate", str(sample_path)])
        assert validate_result.exit_code == 1, validate_result.output
        assert "commerce.Order@4: event must not have an @key field" in validate_result.output
        assert "payments.PaymentTransaction@2: event must not have an @key field" in validate_result.output
        assert "unsupported function 'hmac_sha256'" not in validate_result.output
        assert "unsupported function 'truncate'" not in validate_result.output

        markdown_out = cwd / "dist" / "scenario01-docs"
        jsonschema_out = cwd / "dist" / "scenario01-jsonschema"

        markdown_result = runner.invoke(
            cli,
            ["compile", str(sample_path), "--target", "markdown", "--out", str(markdown_out)],
        )
        assert markdown_result.exit_code == 1, markdown_result.output
        assert "unsupported function 'hmac_sha256'" not in markdown_result.output
        assert "unsupported function 'truncate'" not in markdown_result.output

        jsonschema_result = runner.invoke(
            cli,
            ["compile", str(sample_path), "--target", "json-schema", "--out", str(jsonschema_out)],
        )
        assert jsonschema_result.exit_code == 1, jsonschema_result.output
        assert "unsupported function 'hmac_sha256'" not in jsonschema_result.output
        assert "unsupported function 'truncate'" not in jsonschema_result.output


def test_partner_marketplace_scenario_reports_aggregate_key_validation_gap(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    sample_path = repo_root / "samples" / "scenarios" / "05-partner-marketplace-api"
    runner = CliRunner()

    with runner.isolated_filesystem(temp_dir=tmp_path) as cwd:
        cwd = Path(cwd)
        validate_result = runner.invoke(cli, ["validate", str(sample_path)])
        assert validate_result.exit_code == 1, validate_result.output
        assert "inventory.SellerInventoryLevel@2: aggregate must have exactly one @key field" in validate_result.output

        markdown_out = cwd / "dist" / "scenario05-docs"
        compile_result = runner.invoke(
            cli,
            ["compile", str(sample_path), "--target", "markdown", "--out", str(markdown_out)],
        )
        assert compile_result.exit_code == 1, compile_result.output
        assert "aggregate must have exactly one @key field" in compile_result.output
