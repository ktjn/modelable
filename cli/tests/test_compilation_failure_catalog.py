from __future__ import annotations

import dataclasses
import json
import sqlite3
from pathlib import Path
from unittest.mock import Mock

import pytest
from click.testing import CliRunner
from pygls.exceptions import JsonRpcInternalError
from test_lsp_compilation_recovery import (
    assert_published,
    change_payload,
    preview_compilation,
)
from test_lsp_compilation_recovery import (
    compilation_rpc as compilation_rpc,
)

import modelable.operations.compilation as compilation
from modelable.cli import cli
from modelable.lsp.conversation_protocol import APPLY_METHOD
from modelable.operations.compilation import (
    CompilationConfirmation,
    CompilationError,
    CompilationPolicy,
    CompilationRequest,
    CompilationService,
)
from modelable.operations.file_transaction import FileTransaction, LockContentionError
from modelable.registry.ids import RegistryIdLock, RegistryIdLockContentionError
from modelable.registry.oci import OCIRegistryError


@pytest.fixture
def catalog_workspace(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    source = root / "customer.mdl"
    source.write_text(
        'domain customer { owner: "team" entity Customer @ 1 (additive) { @key customerId: uuid } }',
        encoding="utf-8",
    )
    stages = tmp_path / "stages"
    stages.mkdir()
    request = CompilationRequest(
        source=source,
        target="rust",
        out_dir=root / "dist" / "rust",
        registry_path=str(root / ".modelable" / "registry.db"),
        registry_ids_path=root / "registry-ids.lock",
        enum_numbers_path=root / "enum-numbers.lock",
    )
    return root, stages, request, CompilationService(temp_root=stages)


def prepare_pending(service, request, mode):
    if mode == "apply":
        return service.preview(
            CompilationRequest(source=request.source, target="rust"), policy=CompilationPolicy.conversation()
        )
    return None


def invoke_operation(service, request, mode, pending):
    if mode == "direct":
        return service.execute_direct(request)
    if mode == "preview":
        return service.preview(
            CompilationRequest(source=request.source, target="rust"), policy=CompilationPolicy.conversation()
        )
    assert pending is not None
    return service.apply(
        pending,
        confirmation=CompilationConfirmation(
            session_id="catalog-session",
            action_id=pending.action_id,
            manifest_fingerprint=pending.manifest_fingerprint,
            surface="cli-chat",
            provider=None,
            model=None,
        ),
    )


def assert_no_publication(root):
    assert not (root / "dist").exists()
    assert not (root / ".modelable" / "registry.db").exists()
    assert not (root / ".modelable" / "audit").exists()


@pytest.mark.parametrize(
    ("mode", "fault"),
    [
        ("direct", "ledger-lock"),
        ("apply", "ledger-lock"),
        ("direct", "publication-lock"),
        ("apply", "publication-lock"),
        ("direct", "staging-io"),
        ("preview", "staging-io"),
        ("apply", "audit-io"),
        ("direct", "sqlite"),
        ("preview", "sqlite"),
    ],
)
def test_operational_helper_failure_escapes_service_unchanged(catalog_workspace, monkeypatch, mode, fault):
    root, stages, request, service = catalog_workspace
    pending = prepare_pending(service, request, mode)
    source_bytes = request.source.read_bytes()
    if fault == "ledger-lock":
        error = RegistryIdLockContentionError("injected ledger contention")
        monkeypatch.setattr(RegistryIdLock, "__enter__", Mock(side_effect=error))
    elif fault == "publication-lock":
        error = LockContentionError("injected publication contention")
        monkeypatch.setattr(FileTransaction, "promote", Mock(side_effect=error))
    elif fault == "sqlite":
        error = sqlite3.OperationalError("injected registry database unavailable")
        monkeypatch.setattr(sqlite3, "connect", Mock(side_effect=error))
    elif fault == "staging-io":
        error = OSError("injected staging allocation failure")
        monkeypatch.setattr(compilation.tempfile, "mkdtemp", Mock(side_effect=error))
    else:
        error = OSError("injected staged audit write failure")
        original = Path.write_bytes

        def write(path, data):
            if path.name == "compilation-audit.json":
                raise error
            return original(path, data)

        monkeypatch.setattr(Path, "write_bytes", write)

    with pytest.raises(type(error)) as raised:
        invoke_operation(service, request, mode, pending)

    assert raised.value is error
    assert request.source.read_bytes() == source_bytes
    assert list(stages.iterdir()) == []
    assert_no_publication(root)


@pytest.mark.parametrize("mode", ["direct", "preview"])
def test_malformed_input_ledger_escapes_as_json_decode_error(catalog_workspace, mode):
    root, stages, request, service = catalog_workspace
    malformed = b'{"broken":'
    request.registry_ids_path.write_bytes(malformed)

    with pytest.raises(json.JSONDecodeError):
        invoke_operation(service, request, mode, None)

    assert request.registry_ids_path.read_bytes() == malformed
    assert list(stages.iterdir()) == []
    assert_no_publication(root)


def test_preview_can_stage_while_destination_ledger_lock_is_held(catalog_workspace):
    root, stages, request, service = catalog_workspace
    with RegistryIdLock(request.registry_ids_path):
        pending = service.preview(
            CompilationRequest(source=request.source, target="rust"), policy=CompilationPolicy.conversation()
        )
        assert pending.staging_dir.is_dir()
        assert not request.registry_ids_path.exists()
        assert_no_publication(root)
    service.discard(pending)
    assert list(stages.iterdir()) == []


def test_discard_wraps_cleanup_oserror_and_retains_staging(catalog_workspace, monkeypatch):
    root, _stages, request, service = catalog_workspace
    pending = prepare_pending(service, request, "apply")
    error = OSError("injected discard cleanup failure")
    monkeypatch.setattr(compilation.shutil, "rmtree", Mock(side_effect=error))

    with pytest.raises(CompilationError, match="staging cleanup failed") as raised:
        service.discard(pending)

    assert raised.value.__cause__ is error
    assert pending.staging_dir.is_dir()
    assert_no_publication(root)


@pytest.mark.parametrize("mode", ["direct", "preview"])
@pytest.mark.parametrize("kind", [RuntimeError, sqlite3.ProgrammingError])
def test_unspecified_programming_faults_are_not_normalized(catalog_workspace, monkeypatch, mode, kind):
    root, stages, request, service = catalog_workspace
    error = kind("injected unexpected programming fault")
    monkeypatch.setattr(compilation, "_run_compilation", Mock(side_effect=error))

    with pytest.raises(kind) as raised:
        invoke_operation(service, request, mode, None)

    assert raised.value is error
    assert list(stages.iterdir()) == []
    assert_no_publication(root)


@pytest.mark.parametrize(
    "error", [json.JSONDecodeError("injected invalid ledger", "{", 1), sqlite3.OperationalError("injected database IO")]
)
def test_current_cli_does_not_normalize_newly_observed_dependency_errors(catalog_workspace, monkeypatch, error):
    root, _stages, request, _service = catalog_workspace
    execute = Mock(side_effect=error)
    monkeypatch.setattr(CompilationService, "execute_direct", execute)

    result = CliRunner().invoke(cli, ["compile", str(request.source), "--target", "rust"])

    assert result.exit_code == 1
    assert result.exception is error
    assert not result.output.startswith("Error: ")
    execute.assert_called_once()
    assert_no_publication(root)


def test_unsupported_oci_is_wrapped_as_compilation_error_without_remote_io(catalog_workspace):
    root, stages, request, service = catalog_workspace
    request = dataclasses.replace(request, registry_path="oci://registry.example.test/catalog")

    with pytest.raises(CompilationError, match="not implemented") as raised:
        service.execute_direct(request)

    assert isinstance(raised.value.__cause__, OCIRegistryError)
    assert list(stages.iterdir()) == []
    assert_no_publication(root)


async def test_malformed_ledger_preview_fault_allows_repaired_request_in_same_rpc_session(compilation_rpc):
    client, root, _source, stages = compilation_rpc
    ledger = root / "registry-ids.lock"
    ledger.write_bytes(b'{"broken":')

    with pytest.raises(JsonRpcInternalError, match="JSONDecodeError") as raised:
        await preview_compilation(client, root)

    assert raised.value.code == -32603
    assert list(stages.iterdir()) == []
    assert_no_publication(root)
    ledger.write_text("{}", encoding="utf-8")
    fresh = await preview_compilation(client, root, create_session=False)
    applied = await client.protocol.send_request_async(APPLY_METHOD, change_payload(fresh))
    assert_published(fresh, applied)
    assert list(stages.iterdir()) == []
