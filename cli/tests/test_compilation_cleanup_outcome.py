import pytest

import modelable.operations.compilation as compilation
from modelable.operations.compilation import (
    CompilationConfirmation,
    CompilationError,
    CompilationPolicy,
    CompilationRequest,
    CompilationService,
)
from modelable.operations.file_transaction import FileTransaction, FileTransactionCommittedError


@pytest.mark.parametrize("mode", ["direct", "apply"])
def test_successful_promotion_keeps_committed_outcome_when_staging_cleanup_fails(tmp_path, monkeypatch, mode):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "customer.mdl"
    source.write_text(
        'domain customer { owner: "team" entity Customer @ 1 (additive) { @key customerId: uuid } }',
        encoding="utf-8",
    )
    request = CompilationRequest(
        source=source,
        target="rust",
        out_dir=workspace / "dist" / "rust",
        registry_path=str(workspace / "registry.db"),
        registry_ids_path=workspace / "registry-ids.lock",
        enum_numbers_path=workspace / "enum-numbers.lock",
    )
    service = CompilationService(temp_root=tmp_path, new_id=lambda: "cleanup-outcome")
    pending = (
        service.preview(CompilationRequest(source=source, target="rust"), policy=CompilationPolicy.conversation())
        if mode == "apply"
        else None
    )
    promoted = []
    cleanup_paths = []
    original_promote = FileTransaction.promote
    failure = CompilationError("injected staging cleanup failure")

    def record_promotion(transaction, *args, **kwargs):
        paths = original_promote(transaction, *args, **kwargs)
        promoted.append(paths)
        return paths

    def fail_cleanup(path):
        cleanup_paths.append(path)
        raise failure

    monkeypatch.setattr(FileTransaction, "promote", record_promotion)
    monkeypatch.setattr(compilation, "_remove_staging", fail_cleanup)
    with pytest.raises(FileTransactionCommittedError) as raised:
        if pending is None:
            service.execute_direct(request)
        else:
            service.apply(
                pending,
                confirmation=CompilationConfirmation(
                    session_id="test-session",
                    action_id=pending.action_id,
                    manifest_fingerprint=pending.manifest_fingerprint,
                    surface="cli-chat",
                    provider=None,
                    model=None,
                ),
            )

    error = raised.value
    assert error.committed is True
    assert len(promoted) == 1
    assert error.written_paths == tuple(promoted[0])
    assert error.written_paths and all(path.is_file() for path in error.written_paths)
    assert len(cleanup_paths) == 1
    assert cleanup_paths[0].is_dir()
    assert len(error.cleanup_errors) == 1
    assert error.cleanup_errors[0].path == cleanup_paths[0]
    assert error.cleanup_errors[0].error is failure
    assert error.__cause__ is failure
    if pending is not None:
        assert pending.audit_path in error.written_paths
        for item in pending.files:
            assert item.destination.read_bytes() == item.staged_path.read_bytes()
    else:
        assert not (workspace / ".modelable" / "audit").exists()
