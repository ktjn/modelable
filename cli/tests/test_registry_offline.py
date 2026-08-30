from pathlib import Path
from shutil import copyfile

from click.testing import CliRunner

from modelable.cli import cli
from modelable.llm.conversation_plan import AddField, AppendModelVersion, ChangeSetPlan, FieldSpec
from modelable.llm.workspace_editor import WorkspaceEditor
from modelable.parser.ir import PrimitiveType
from modelable.registry.sources import LocalSourceAdapter

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


def test_core_analysis_does_not_invoke_source_adapter_or_network(tmp_path: Path, monkeypatch) -> None:
    """Ordinary analysis and local editing use only the checked-out workspace."""

    def forbidden_operation(*_args, **_kwargs):
        raise AssertionError("ordinary compiler analysis invoked an external operation")

    monkeypatch.setattr("urllib.request.urlopen", forbidden_operation)
    monkeypatch.setattr(LocalSourceAdapter, "load", forbidden_operation)
    source = tmp_path / "customer.mdl"
    copyfile(FIXTURE, source)

    pending = WorkspaceEditor(tmp_path).preview(
        ChangeSetPlan(
            summary="Add a local customer field",
            operations=[
                AppendModelVersion(source="customer.Customer@2", version=3),
                AddField(
                    target="customer.Customer@3",
                    field=FieldSpec(name="nickname", type=PrimitiveType(kind="string"), optional=True),
                ),
            ],
        )
    )

    assert pending.changed
