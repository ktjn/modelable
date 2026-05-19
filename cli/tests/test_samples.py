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
