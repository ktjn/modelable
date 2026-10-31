from pathlib import Path
from unittest.mock import Mock

import pytest
from click.testing import CliRunner, Result

from modelable.cli import cli
from modelable.operations.file_transaction import (
    FileTransactionCommittedError,
    FileTransactionError,
    LockContentionError,
    RollbackError,
)
from modelable.registry.ids import RegistryIdLockContentionError


def invoke_compile(error: Exception, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Result, Mock]:
    source = tmp_path / "workspace.mdl"
    source.write_text("domain sample {}", encoding="utf-8")
    execute = Mock(side_effect=error)
    monkeypatch.setattr("modelable.commands.compile.CompilationService.execute_direct", execute)
    return CliRunner().invoke(cli, ["compile", str(source), "--target", "rust"]), execute


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(
            FileTransactionError(
                OSError("promotion failed"), [RollbackError(Path("retained.backup"), OSError("rollback denied"))]
            ),
            id="promotion-with-rollback",
        ),
        pytest.param(LockContentionError("workspace is busy"), id="workspace-lock"),
        pytest.param(RegistryIdLockContentionError("ledger is busy"), id="ledger-lock"),
        pytest.param(OSError("staging is unavailable"), id="filesystem"),
    ],
)
def test_compile_renders_known_operational_errors(error: Exception, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    result, execute = invoke_compile(error, tmp_path, monkeypatch)

    assert result.exit_code == 1
    assert result.output.startswith("Error: ")
    assert str(error) in result.output
    assert isinstance(result.exception, SystemExit)
    execute.assert_called_once()


def test_compile_reports_committed_paths_and_keeps_cleanup_details(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    written = tmp_path / "generated.rs"
    backup = tmp_path / "retained.backup"
    written.write_bytes(b"published")
    backup.write_bytes(b"original")
    error = FileTransactionCommittedError([written], [RollbackError(backup, OSError("backup cleanup denied"))])

    result, execute = invoke_compile(error, tmp_path, monkeypatch)

    assert result.exit_code == 1
    assert result.output.startswith("Error: ")
    assert "committed" in result.output.lower()
    assert "Written paths:" in result.output
    assert str(written) in result.output
    assert str(backup) in result.output
    assert "backup cleanup denied" in result.output
    assert isinstance(result.exception, SystemExit)
    assert written.read_bytes() == b"published"
    assert backup.read_bytes() == b"original"
    execute.assert_called_once()


def test_compile_does_not_swallow_unexpected_programming_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    error = RuntimeError("unexpected internal fault")

    result, execute = invoke_compile(error, tmp_path, monkeypatch)

    assert result.exit_code == 1
    assert result.exception is error
    assert not result.output.startswith("Error: ")
    execute.assert_called_once()
