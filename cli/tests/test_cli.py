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


def test_diff_reports_required_field_addition_as_breaking(tmp_path):
    mdl = tmp_path / "customer.mdl"
    mdl.write_text(
        """
domain customer {
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }

  entity Customer @ 2 (additive) {
    @key customerId: uuid
    email: string
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
    assert "added_field email" in result.output.lower()


def test_diff_reports_enum_and_identity_changes(tmp_path):
    mdl = tmp_path / "customer.mdl"
    mdl.write_text(
        """
domain customer {
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    status: enum(active, blocked)
  }

  entity Customer @ 2 (additive) {
    customerId: uuid
    status: enum(active, blocked, archived)
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
    assert "identity_changed customerid" in result.output.lower()
    assert "enum_changed status" in result.output.lower()


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


def test_lineage_prints_model_and_projection_details(tmp_path):
    mdl = tmp_path / "workspace.mdl"
    mdl.write_text(
        """
domain customer {
  owner: "customer-platform"

  entity Customer @ 1 (additive) {
    @key customerId: uuid
    @pii
    email?: string
  }
}

domain billing {
  owner: "billing-platform"

  projection BillingCustomer @ 1
    from customer.Customer @ 1 as c
  {
    email <- c.email
    domainName = "billing"
  }
}
""",
        encoding="utf-8",
    )

    runner = CliRunner()
    model_result = runner.invoke(cli, ["lineage", "customer.Customer@1", "--path", str(tmp_path)])
    projection_result = runner.invoke(
        cli,
        ["lineage", "billing.BillingCustomer@1", "--path", str(tmp_path)],
    )

    assert model_result.exit_code == 0, model_result.output
    assert "customer.Customer@1" in model_result.output
    assert "kind: entity" in model_result.output
    assert "customerId" in model_result.output
    assert "classification" not in model_result.output or "pii" in model_result.output

    assert projection_result.exit_code == 0, projection_result.output
    assert "billing.BillingCustomer@1" in projection_result.output
    assert "source: customer.Customer @ 1 as c" in projection_result.output
    assert "- email: direct" in projection_result.output
    assert "<- customer.Customer@1.email" in projection_result.output
    assert "- domainName: computed" in projection_result.output
    assert 'expr: "billing"' in projection_result.output


def test_codegen_formats_and_types():
    runner = CliRunner()

    formats_result = runner.invoke(cli, ["codegen", "formats"])
    assert formats_result.exit_code == 0, formats_result.output
    assert "json-schema" in formats_result.output
    assert "markdown" in formats_result.output
    assert "typescript" in formats_result.output

    typescript_result = runner.invoke(cli, ["codegen", "types"])
    assert typescript_result.exit_code == 0, typescript_result.output
    assert "typescript type mappings" in typescript_result.output
    assert "array<T> -> T[]" in typescript_result.output

    json_schema_result = runner.invoke(cli, ["codegen", "types", "--format", "json-schema"])
    assert json_schema_result.exit_code == 0, json_schema_result.output
    assert 'string -> {"type":"string"}' in json_schema_result.output

    markdown_result = runner.invoke(cli, ["codegen", "types", "--format", "markdown"])
    assert markdown_result.exit_code == 0, markdown_result.output
    assert "rendered as canonical .mdl text" in markdown_result.output


def test_scenario_list_show_and_load(tmp_path):
    runner = CliRunner()

    list_result = runner.invoke(cli, ["scenario", "list"])
    assert list_result.exit_code == 0, list_result.output
    assert "01-ecommerce-data-warehouse" in list_result.output
    assert "09-auto-projections" in list_result.output
    assert "Compiler-Generated Projection Contracts" in list_result.output

    show_result = runner.invoke(cli, ["scenario", "show", "09-auto-projections"])
    assert show_result.exit_code == 0, show_result.output
    assert "09-auto-projections" in show_result.output
    assert "workspace.mdl" in show_result.output
    assert "auto projections Product @ 1" in show_result.output

    output_dir = tmp_path / "loaded"
    load_result = runner.invoke(
        cli,
        ["scenario", "load", "09-auto-projections", "--output-dir", str(output_dir)],
    )
    assert load_result.exit_code == 0, load_result.output
    loaded = output_dir / "09-auto-projections"
    assert loaded.exists()
    assert (loaded / "workspace.mdl").exists()
    assert (loaded / "catalog.mdl").exists()
    assert (loaded / "storefront.mdl").exists()
