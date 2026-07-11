from __future__ import annotations

from click.testing import CliRunner

from modelable.cli import cli

_TWO_DOMAIN_MDL = """
domain logs {
  owner: "test-team"
  entity LogEntry @ 1 (additive) {
    @key logId: uuid
    message: string
  }
}

domain nlq {
  owner: "test-team"
  entity Query @ 1 (additive) {
    @key queryId: uuid
    text: string
  }
}
"""


def test_compile_domain_flag_restricts_output(tmp_path):
    mdl = tmp_path / "workspace.mdl"
    mdl.write_text(_TWO_DOMAIN_MDL, encoding="utf-8")
    out = tmp_path / "dist" / "rust"

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            cli,
            ["compile", str(mdl), "--target", "rust", "--domain", "logs", "--out", str(out)],
        )

    assert result.exit_code == 0, result.output
    assert (out / "logs" / "logs_log_entry_v1.rs").exists()
    assert not (out / "nlq").exists()


def test_compile_domain_flag_is_additive(tmp_path):
    mdl = tmp_path / "workspace.mdl"
    mdl.write_text(_TWO_DOMAIN_MDL, encoding="utf-8")
    out = tmp_path / "dist" / "rust"

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            cli,
            [
                "compile",
                str(mdl),
                "--target",
                "rust",
                "--domain",
                "logs",
                "--domain",
                "nlq",
                "--out",
                str(out),
            ],
        )

    assert result.exit_code == 0, result.output
    assert (out / "logs" / "logs_log_entry_v1.rs").exists()
    assert (out / "nlq" / "nlq_query_v1.rs").exists()


def test_compile_unknown_domain_errors_clearly(tmp_path):
    mdl = tmp_path / "workspace.mdl"
    mdl.write_text(_TWO_DOMAIN_MDL, encoding="utf-8")
    out = tmp_path / "dist" / "rust"

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            cli,
            ["compile", str(mdl), "--target", "rust", "--domain", "bogus", "--out", str(out)],
        )

    assert result.exit_code != 0
    assert "bogus" in result.output
    assert "logs" in result.output
    assert "nlq" in result.output
    assert not out.exists()


def test_compile_without_domain_flag_compiles_whole_workspace(tmp_path):
    mdl = tmp_path / "workspace.mdl"
    mdl.write_text(_TWO_DOMAIN_MDL, encoding="utf-8")
    out = tmp_path / "dist" / "rust"

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            cli,
            ["compile", str(mdl), "--target", "rust", "--out", str(out)],
        )

    assert result.exit_code == 0, result.output
    assert (out / "logs" / "logs_log_entry_v1.rs").exists()
    assert (out / "nlq" / "nlq_query_v1.rs").exists()
