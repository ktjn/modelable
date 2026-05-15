from pathlib import Path

from click.testing import CliRunner

from modelable.cli import cli


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
