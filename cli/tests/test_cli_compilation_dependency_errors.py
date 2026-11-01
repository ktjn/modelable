import json
import sqlite3
from unittest.mock import Mock

import pytest
from click.testing import CliRunner
from test_cli_compilation_errors import invoke_compile
from test_compilation_failure_catalog import assert_no_publication
from test_compilation_failure_catalog import catalog_workspace as catalog_workspace

from modelable.cli import cli


@pytest.mark.parametrize(
    "error", [json.JSONDecodeError("invalid ledger", "{", 1), sqlite3.OperationalError("database unavailable")]
)
def test_compile_renders_dependency_operational_errors(error, tmp_path, monkeypatch):
    result, execute = invoke_compile(error, tmp_path, monkeypatch)

    assert result.exit_code == 1
    assert result.output.startswith("Error: ")
    assert str(error) in result.output
    assert isinstance(result.exception, SystemExit)
    execute.assert_called_once()


@pytest.mark.parametrize("error", [RuntimeError("internal fault"), sqlite3.ProgrammingError("invalid SQL API usage")])
def test_compile_preserves_programming_fault_identity(error, tmp_path, monkeypatch):
    result, execute = invoke_compile(error, tmp_path, monkeypatch)

    assert result.exit_code == 1
    assert result.exception is error
    assert not result.output.startswith("Error: ")
    execute.assert_called_once()


@pytest.mark.parametrize("fault", ["malformed-ledger", "sqlite-operational"])
def test_compile_dependency_failure_preserves_inputs_and_allows_retry(catalog_workspace, monkeypatch, fault):
    root, stages, request, service = catalog_workspace
    monkeypatch.setattr("modelable.commands.compile.CompilationService", lambda: service)
    runner = CliRunner()
    command = [
        "compile",
        str(request.source),
        "--target",
        "rust",
        "--out",
        str(request.out_dir),
        "--registry",
        request.registry_path,
    ]
    source_bytes = request.source.read_bytes()
    malformed = b'{"broken":'
    if fault == "malformed-ledger":
        request.registry_ids_path.write_bytes(malformed)
        result = runner.invoke(cli, command)
        assert request.registry_ids_path.read_bytes() == malformed
        assert "Expecting value" in result.output
    else:
        with monkeypatch.context() as patch:
            connect = Mock(side_effect=sqlite3.OperationalError("registry database unavailable"))
            patch.setattr(sqlite3, "connect", connect)
            result = runner.invoke(cli, command)
            connect.assert_called_once()
        assert not request.registry_ids_path.exists()
        assert "registry database unavailable" in result.output
    assert result.exit_code == 1
    assert result.output.startswith("Error: ")
    assert isinstance(result.exception, SystemExit)
    assert request.source.read_bytes() == source_bytes
    assert list(stages.iterdir()) == []
    assert_no_publication(root)

    if fault == "malformed-ledger":
        request.registry_ids_path.write_text("{}", encoding="utf-8")
    retry = runner.invoke(cli, command)
    assert retry.exit_code == 0, retry.output
    assert request.source.read_bytes() == source_bytes
    assert (root / ".modelable" / "registry.db").is_file()
    assert list(request.out_dir.rglob("*.rs"))
    assert list(stages.iterdir()) == []
