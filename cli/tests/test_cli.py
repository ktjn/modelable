from pathlib import Path

from click.testing import CliRunner

from modelable.cli import cli


def test_root_bootstrap_script_delegates_to_uv_entrypoint():
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "bin" / "modelable"

    assert script.exists()
    assert script.read_text(encoding="utf-8") == (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "\n"
        'cd "$(dirname "$0")/../cli"\n'
        'exec uv run modelable "$@"\n'
    )


def test_validate_valid_file(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text(
        """
domain customer {
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    name: string
  }
}
""",
        encoding="utf-8",
    )

    result = CliRunner().invoke(cli, ["validate", str(mdl)])

    assert result.exit_code == 0
    assert "valid" in result.output.lower()


def test_validate_invalid_file_exits_nonzero(tmp_path):
    mdl = tmp_path / "bad.mdl"
    mdl.write_text(
        """
domain customer {
  entity Customer @ 1 (additive) {
    customerId: uuid
  }
}
""",
        encoding="utf-8",
    )

    result = CliRunner().invoke(cli, ["validate", str(mdl)])

    assert result.exit_code != 0
    assert "key" in result.output.lower()


def test_validate_directory(tmp_path):
    first = tmp_path / "first.mdl"
    second = tmp_path / "nested" / "second.mdl"
    second.parent.mkdir()
    first.write_text(
        """
domain customer {
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""",
        encoding="utf-8",
    )
    second.write_text(
        """
domain orders {
  entity Order @ 1 (additive) {
    @key orderId: uuid
  }
}
""",
        encoding="utf-8",
    )

    result = CliRunner().invoke(cli, ["validate", str(tmp_path)])

    assert result.exit_code == 0
    assert "2 files valid" in result.output.lower()


def test_validate_strict_mode_exits_on_error(tmp_path):
    mdl = tmp_path / "bad.mdl"
    mdl.write_text(
        """
domain customer {
  entity Customer @ 1 (additive) {
    customerId: uuid
  }
}
""",
        encoding="utf-8",
    )

    result = CliRunner().invoke(cli, ["validate", str(mdl), "--strict"])

    assert result.exit_code != 0


def test_validate_directory_reports_duplicate_model_versions(tmp_path):
    first = tmp_path / "customer-a.mdl"
    second = tmp_path / "customer-b.mdl"
    definition = """
domain customer {
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
"""
    first.write_text(definition, encoding="utf-8")
    second.write_text(definition, encoding="utf-8")

    result = CliRunner().invoke(cli, ["validate", str(tmp_path)])

    assert result.exit_code != 0
    assert "duplicate model version customer.customer@1" in result.output.lower()


def test_compile_writes_registry_db(tmp_path):
    mdl = tmp_path / "customer.mdl"
    mdl.write_text(
        """
domain customer {
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""",
        encoding="utf-8",
    )

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            cli,
            ["compile", str(mdl), "--target", "markdown", "--out", str(tmp_path / "dist")],
        )

        assert result.exit_code == 0
        assert Path(".modelable/registry.db").exists()
        assert "registry.db" in result.output


def test_diff_reports_breaking_changes(tmp_path):
    mdl = tmp_path / "customer.mdl"
    mdl.write_text(
        """
domain customer {
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    name: string
  }

  entity Customer @ 2 (additive) {
    @key customerId: uuid
  }
}
""",
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli,
        ["diff", "customer.Customer@1", "customer.Customer@2", "--path", str(tmp_path)],
    )

    assert result.exit_code == 0, result.output
    assert "breaking" in result.output.lower()
    assert "removed_field name" in result.output.lower()


def test_resolve_prints_normalized_model_and_projection(tmp_path):
    mdl = tmp_path / "workspace.mdl"
    mdl.write_text(
        """
domain customer {
  owner: "customer-platform"

  entity Customer @ 1 (additive) {
    @key customerId: uuid
    name: string
  }
}

domain billing {
  owner: "billing-platform"

  projection BillingCustomer @ 1
    from customer.Customer @ 1 as c
  {
    billingId <- c.customerId
    displayName = c.name
  }
}
""",
        encoding="utf-8",
    )

    runner = CliRunner()
    model_result = runner.invoke(cli, ["resolve", "customer.Customer@1", "--path", str(tmp_path)])
    projection_result = runner.invoke(
        cli,
        ["resolve", "billing.BillingCustomer@1", "--path", str(tmp_path)],
    )

    assert model_result.exit_code == 0, model_result.output
    assert "entity Customer @ 1 (additive)" in model_result.output
    assert "owner: \"customer-platform\"" in model_result.output
    assert "name: string" in model_result.output

    assert projection_result.exit_code == 0, projection_result.output
    assert "projection BillingCustomer @ 1" in projection_result.output
    assert "from customer.Customer @ 1 as c" in projection_result.output
    assert "billingId <- c.customerId" in projection_result.output
    assert "displayName = c.name" in projection_result.output
