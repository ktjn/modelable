from pathlib import Path

from click.testing import CliRunner

from modelable.cli import cli

FIXTURE = Path(__file__).parent / "fixtures" / "customer.mdl"


def test_core_analysis_does_not_contact_network(tmp_path: Path, monkeypatch) -> None:
    """The ordinary compiler/analysis commands use local source only."""

    def forbidden_network_call(*_args, **_kwargs):
        raise AssertionError("ordinary compiler analysis contacted the network")

    monkeypatch.setattr("urllib.request.urlopen", forbidden_network_call)
    runner = CliRunner()
    source = FIXTURE.resolve()

    checks = [
        ["validate", str(source)],
        ["compile", str(source), "--target", "json-schema", "--out", str(tmp_path / "artifacts")],
        ["diff", "customer.Customer@1", "customer.Customer@2", "--path", str(source)],
        [
            "impact",
            "--from",
            "customer.Customer@1",
            "--to",
            "customer.Customer@2",
            "--path",
            str(source),
        ],
        ["lineage", "customer.Customer@2", "--path", str(source)],
    ]

    for arguments in checks:
        result = runner.invoke(cli, arguments)
        assert result.exit_code == 0, f"{arguments}: {result.output}"
