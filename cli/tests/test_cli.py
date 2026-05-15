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
