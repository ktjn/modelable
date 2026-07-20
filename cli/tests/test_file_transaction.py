from __future__ import annotations

import os
import stat
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from modelable.operations.file_transaction import (
    FileTransaction,
    FileTransactionCommittedError,
    FileTransactionError,
    LockContentionError,
    StagedFile,
)


def _snapshot(root: Path) -> dict[Path, bytes]:
    return {path.relative_to(root): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


def _staged_files(stage: Path, destinations: list[Path]) -> tuple[StagedFile, ...]:
    files = []
    for index, destination in enumerate(destinations):
        staged = stage / f"{index}.stage"
        staged.write_bytes(f"after-{index}".encode())
        files.append(StagedFile.from_path(destination=destination, staged_path=staged))
    return tuple(files)


class FailingReplace:
    def __init__(self, fail_after: int) -> None:
        self.fail_after = fail_after
        self.promotions = 0
        self.failed = False

    def __call__(self, source: str | Path, destination: str | Path) -> None:
        source_path = Path(source)
        if ".modelable-tmp-" in source_path.name:
            if self.promotions == self.fail_after and not self.failed:
                self.failed = True
                raise OSError(f"injected promotion failure {self.fail_after}")
            self.promotions += 1
        os.replace(source, destination)


@pytest.mark.parametrize("fail_after", [0, 1, 2])
def test_transaction_restores_every_file_after_injected_failure(
    tmp_path: Path,
    fail_after: int,
) -> None:
    workspace = tmp_path / "workspace"
    stage = tmp_path / "stage"
    workspace.mkdir()
    stage.mkdir()
    destinations = [workspace / f"{index}.txt" for index in range(3)]
    for index, destination in enumerate(destinations):
        destination.write_bytes(f"before-{index}".encode())
    before = _snapshot(workspace)
    transaction = FileTransaction(
        workspace_root=workspace,
        replace=FailingReplace(fail_after),
    )

    with pytest.raises(FileTransactionError, match="injected promotion failure"):
        transaction.promote(_staged_files(stage, destinations))

    assert _snapshot(workspace) == before


def test_transaction_removes_created_files_and_empty_directories_on_failure(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    stage = tmp_path / "stage"
    workspace.mkdir()
    stage.mkdir()
    destinations = [
        workspace / "new" / "nested" / "first.txt",
        workspace / "new" / "nested" / "second.txt",
    ]

    with pytest.raises(FileTransactionError):
        FileTransaction(
            workspace_root=workspace,
            replace=FailingReplace(1),
        ).promote(_staged_files(stage, destinations))

    assert not (workspace / "new").exists()
    assert not (workspace / ".modelable" / "locks").exists()


def test_transaction_rejects_workspace_lock_contention(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    stage = tmp_path / "stage"
    workspace.mkdir()
    stage.mkdir()
    destination = workspace / "result.txt"
    lock = workspace / ".modelable" / "locks" / "compilation.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text("held\n", encoding="utf-8")

    with pytest.raises(LockContentionError, match="already in progress"):
        FileTransaction(workspace_root=workspace).promote(_staged_files(stage, [destination]))

    assert lock.read_text(encoding="utf-8") == "held\n"


def test_transaction_verifies_promoted_hash_and_rolls_back(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    stage = tmp_path / "stage"
    workspace.mkdir()
    stage.mkdir()
    destination = workspace / "result.txt"
    destination.write_bytes(b"before")
    before = _snapshot(workspace)
    corrupted = False

    def corrupting_replace(source: str | Path, target: str | Path) -> None:
        nonlocal corrupted
        os.replace(source, target)
        if ".modelable-tmp-" in Path(source).name and not corrupted:
            Path(target).write_bytes(b"corrupt")
            corrupted = True

    with pytest.raises(FileTransactionError, match="hash verification"):
        FileTransaction(
            workspace_root=workspace,
            replace=corrupting_replace,
        ).promote(_staged_files(stage, [destination]))

    assert _snapshot(workspace) == before


def test_transaction_rechecks_all_preimages_after_preparation_before_any_replace(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    stage = tmp_path / "stage"
    workspace.mkdir()
    stage.mkdir()
    destinations = [workspace / "one.txt", workspace / "two.txt"]
    for index, destination in enumerate(destinations):
        destination.write_bytes(f"before-{index}".encode())
    raced = False

    def racing_copy(source: Path, target: Path) -> None:
        nonlocal raced
        target.write_bytes(source.read_bytes())
        if ".modelable-tmp-" in target.name and not raced:
            destinations[1].write_bytes(b"concurrent-change")
            raced = True

    def validate_preimages() -> None:
        if destinations[1].read_bytes() != b"before-1":
            raise OSError("destination changed during transaction")

    with pytest.raises(FileTransactionError, match="destination changed during transaction"):
        FileTransaction(
            workspace_root=workspace,
            copy_file=racing_copy,
        ).promote(
            _staged_files(stage, destinations),
            validate=validate_preimages,
        )

    assert destinations[0].read_bytes() == b"before-0"
    assert destinations[1].read_bytes() == b"concurrent-change"


@pytest.mark.skipif(os.name == "nt", reason="POSIX file metadata semantics")
def test_transaction_success_preserves_existing_destination_permissions(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    stage = tmp_path / "stage"
    workspace.mkdir()
    stage.mkdir()
    destination = workspace / "result.txt"
    destination.write_bytes(b"before")
    destination.chmod(0o640)
    staged_file = _staged_files(stage, [destination])
    staged_file[0].staged_path.chmod(0o600)

    FileTransaction(workspace_root=workspace).promote(staged_file)

    assert destination.read_bytes() == b"after-0"
    assert stat.S_IMODE(destination.stat().st_mode) == 0o640


@pytest.mark.skipif(os.name == "nt", reason="POSIX file metadata semantics")
def test_transaction_rollback_restores_existing_destination_metadata(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    stage = tmp_path / "stage"
    workspace.mkdir()
    stage.mkdir()
    destinations = [workspace / "one.txt", workspace / "two.txt"]
    for index, destination in enumerate(destinations):
        destination.write_bytes(f"before-{index}".encode())
    destinations[0].chmod(0o640)
    expected_mtime_ns = 1_700_000_000_123_456_789
    os.utime(destinations[0], ns=(expected_mtime_ns, expected_mtime_ns))

    with pytest.raises(FileTransactionError, match="injected promotion failure"):
        FileTransaction(
            workspace_root=workspace,
            replace=FailingReplace(1),
        ).promote(_staged_files(stage, destinations))

    restored = destinations[0].stat()
    assert destinations[0].read_bytes() == b"before-0"
    assert stat.S_IMODE(restored.st_mode) == 0o640
    assert restored.st_mtime_ns == expected_mtime_ns


@pytest.mark.skipif(os.name == "nt", reason="POSIX file metadata semantics")
def test_transaction_new_file_uses_staged_legacy_permissions(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    stage = tmp_path / "stage"
    workspace.mkdir()
    stage.mkdir()
    destination = workspace / "result.txt"
    staged_file = _staged_files(stage, [destination])
    staged_file[0].staged_path.chmod(0o644)

    FileTransaction(workspace_root=workspace).promote(staged_file)

    assert destination.read_bytes() == b"after-0"
    assert stat.S_IMODE(destination.stat().st_mode) == 0o644


def test_transaction_surfaces_each_rollback_error(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    stage = tmp_path / "stage"
    workspace.mkdir()
    stage.mkdir()
    destinations = [workspace / "one.txt", workspace / "two.txt"]
    for destination in destinations:
        destination.write_bytes(b"before")
    promotion_count = 0

    def failing_replace(source: str | Path, target: str | Path) -> None:
        nonlocal promotion_count
        source_path = Path(source)
        if ".modelable-tmp-" in source_path.name:
            if promotion_count == 1:
                raise OSError("promotion failed")
            promotion_count += 1
        if ".modelable-backup-" in source_path.name:
            raise OSError(f"rollback failed for {Path(target).name}")
        os.replace(source, target)

    with pytest.raises(FileTransactionError) as raised:
        FileTransaction(
            workspace_root=workspace,
            replace=failing_replace,
        ).promote(_staged_files(stage, destinations))

    assert len(raised.value.rollback_errors) == 1
    assert "rollback failed for one.txt" in str(raised.value.rollback_errors[0])
    assert "promotion failed" in str(raised.value)
    assert "rollback failed for one.txt" in str(raised.value)


def test_transaction_cleans_lock_temporaries_and_backups_after_success(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    stage = tmp_path / "stage"
    workspace.mkdir()
    stage.mkdir()
    destination = workspace / "result.txt"
    destination.write_bytes(b"before")

    written = FileTransaction(workspace_root=workspace).promote(_staged_files(stage, [destination]))

    assert written == (destination,)
    assert destination.read_bytes() == b"after-0"
    assert not (workspace / ".modelable" / "locks" / "compilation.lock").exists()
    assert not (workspace / ".modelable" / "locks").exists()
    assert not list(workspace.rglob("*.modelable-tmp-*"))
    assert not list(workspace.rglob("*.modelable-backup-*"))


@pytest.mark.parametrize("failure_kind", ["backup", "temporary"])
def test_preparation_copy_failure_cleans_partial_files_and_allows_retry(
    tmp_path: Path,
    failure_kind: str,
) -> None:
    workspace = tmp_path / "workspace"
    stage = tmp_path / "stage"
    workspace.mkdir()
    stage.mkdir()
    destination = workspace / "result.txt"
    destination.write_bytes(b"before")
    files = _staged_files(stage, [destination])
    failed = False

    def partial_copy(source: Path, target: Path) -> None:
        nonlocal failed
        is_target = (
            ".modelable-backup-" in target.name if failure_kind == "backup" else ".modelable-tmp-" in target.name
        )
        if is_target and not failed:
            failed = True
            target.write_bytes(b"partial")
            raise OSError(f"injected {failure_kind} copy failure")
        target.write_bytes(source.read_bytes())

    with pytest.raises(FileTransactionError, match=f"{failure_kind} copy failure"):
        FileTransaction(
            workspace_root=workspace,
            copy_file=partial_copy,
        ).promote(files)

    assert destination.read_bytes() == b"before"
    assert not list(workspace.rglob("*.modelable-tmp-*"))
    assert not list(workspace.rglob("*.modelable-backup-*"))
    assert not (workspace / ".modelable" / "locks" / "compilation.lock").exists()

    assert FileTransaction(workspace_root=workspace).promote(files) == (destination,)
    assert destination.read_bytes() == b"after-0"


def test_partial_backup_disposal_failure_is_explicitly_committed_and_retry_safe(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    first_stage = tmp_path / "first-stage"
    second_stage = tmp_path / "second-stage"
    workspace.mkdir()
    first_stage.mkdir()
    second_stage.mkdir()
    destinations = [workspace / "one.txt", workspace / "two.txt"]
    for destination in destinations:
        destination.write_bytes(b"before")
    disposed_backups = 0

    def fail_second_backup_unlink(path: Path, *, missing_ok: bool = False) -> None:
        nonlocal disposed_backups
        if ".modelable-backup-" in path.name:
            disposed_backups += 1
            if disposed_backups == 2:
                raise OSError("injected backup disposal failure")
        path.unlink(missing_ok=missing_ok)

    with pytest.raises(Exception) as raised:
        FileTransaction(
            workspace_root=workspace,
            unlink=fail_second_backup_unlink,
        ).promote(_staged_files(first_stage, destinations))

    assert getattr(raised.value, "committed", False)
    assert [path.read_bytes() for path in destinations] == [b"after-0", b"after-1"]
    assert not (workspace / ".modelable" / "locks" / "compilation.lock").exists()

    FileTransaction(workspace_root=workspace).promote(_staged_files(second_stage, destinations))
    assert [path.read_bytes() for path in destinations] == [b"after-0", b"after-1"]


@pytest.mark.parametrize("failure_kind", ["write", "fsync"])
def test_lock_initialization_failure_removes_owned_lock_and_allows_retry(
    tmp_path: Path,
    failure_kind: str,
) -> None:
    workspace = tmp_path / "workspace"
    stage = tmp_path / "stage"
    workspace.mkdir()
    stage.mkdir()
    destination = workspace / "result.txt"
    files = _staged_files(stage, [destination])

    def fail_write(descriptor: int, content: bytes) -> int:
        if failure_kind == "write":
            raise OSError("injected lock write failure")
        return os.write(descriptor, content)

    def fail_fsync(descriptor: int) -> None:
        if failure_kind == "fsync":
            raise OSError("injected lock fsync failure")
        os.fsync(descriptor)

    with pytest.raises(FileTransactionError, match=f"lock {failure_kind} failure"):
        FileTransaction(
            workspace_root=workspace,
            lock_write=fail_write,
            fsync=fail_fsync,
        ).promote(files)

    assert not destination.exists()
    assert not (workspace / ".modelable" / "locks" / "compilation.lock").exists()
    FileTransaction(workspace_root=workspace).promote(files)
    assert destination.read_bytes() == b"after-0"


def test_lock_unlink_failure_uses_safe_release_and_allows_retry(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    first_stage = tmp_path / "first-stage"
    second_stage = tmp_path / "second-stage"
    workspace.mkdir()
    first_stage.mkdir()
    second_stage.mkdir()
    destination = workspace / "result.txt"
    failed = False

    def fail_lock_unlink(path: Path, *, missing_ok: bool = False) -> None:
        nonlocal failed
        if path.name == "compilation.lock" and not failed:
            failed = True
            raise OSError("injected lock unlink failure")
        path.unlink(missing_ok=missing_ok)

    written = FileTransaction(
        workspace_root=workspace,
        unlink=fail_lock_unlink,
    ).promote(_staged_files(first_stage, [destination]))

    assert written == (destination,)
    assert destination.read_bytes() == b"after-0"
    assert not (workspace / ".modelable" / "locks" / "compilation.lock").exists()
    FileTransaction(workspace_root=workspace).promote(_staged_files(second_stage, [destination]))
    assert destination.read_bytes() == b"after-0"


def test_mid_chain_directory_creation_failure_cleans_created_parents(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    stage = tmp_path / "stage"
    workspace.mkdir()
    stage.mkdir()
    destination = workspace / "target" / "middle" / "leaf" / "result.txt"

    def fail_middle(path: Path) -> None:
        if path.name == "middle":
            raise OSError("injected middle mkdir failure")
        path.mkdir()

    with pytest.raises(FileTransactionError, match="middle mkdir failure"):
        FileTransaction(
            workspace_root=workspace,
            mkdir=fail_middle,
        ).promote(_staged_files(stage, [destination]))

    assert not (workspace / "target").exists()
    assert not (workspace / ".modelable" / "locks").exists()


@pytest.mark.parametrize("failure_kind", ["rename", "delete"])
def test_quarantine_failures_are_individually_reported_with_backup_state(
    tmp_path: Path,
    failure_kind: str,
) -> None:
    workspace = tmp_path / "workspace"
    stage = tmp_path / "stage"
    workspace.mkdir()
    stage.mkdir()
    destination = workspace / "result.txt"
    destination.write_bytes(b"before")

    def failing_unlink(path: Path, *, missing_ok: bool = False) -> None:
        if ".modelable-backup-" in path.name:
            raise OSError("injected backup unlink failure")
        if "modelable-cleanup-" in path.name and failure_kind == "delete":
            raise OSError("injected quarantine deletion failure")
        path.unlink(missing_ok=missing_ok)

    def failing_replace(source: str | Path, target: str | Path) -> None:
        if ".modelable-backup-" in Path(source).name and failure_kind == "rename":
            raise OSError("injected quarantine rename failure")
        os.replace(source, target)

    with pytest.raises(FileTransactionCommittedError) as raised:
        FileTransaction(
            workspace_root=workspace,
            unlink=failing_unlink,
            replace=failing_replace,
        ).promote(_staged_files(stage, [destination]))

    assert raised.value.committed
    assert len(raised.value.cleanup_errors) == 2
    assert destination.read_bytes() == b"after-0"
    backup_files = list(workspace.glob("*.modelable-backup-*"))
    quarantine_files = list(workspace.glob("*modelable-cleanup-*"))
    if failure_kind == "rename":
        assert backup_files
        assert not quarantine_files
        assert backup_files[0].read_bytes() == b"before"
    else:
        assert not backup_files
        assert quarantine_files
        assert quarantine_files[0].read_bytes() == b"before"
    assert any(error.path.exists() for error in raised.value.cleanup_errors)


def test_concurrent_virgin_lock_parent_creation_enters_normal_contention(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    first_stage = tmp_path / "first-stage"
    second_stage = tmp_path / "second-stage"
    workspace.mkdir()
    first_stage.mkdir()
    second_stage.mkdir()
    parent_barrier = threading.Barrier(2)

    def synchronized_mkdir(path: Path) -> None:
        if path.name == ".modelable":
            parent_barrier.wait(timeout=10)
        path.mkdir()

    first = FileTransaction(
        workspace_root=workspace,
        mkdir=synchronized_mkdir,
        lock_timeout=10,
    )
    second = FileTransaction(
        workspace_root=workspace,
        mkdir=synchronized_mkdir,
        lock_timeout=10,
    )
    first_files = _staged_files(first_stage, [workspace / "first.txt"])
    second_files = _staged_files(second_stage, [workspace / "second.txt"])

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = (
            executor.submit(first.promote, first_files),
            executor.submit(second.promote, second_files),
        )
        results = [future.result(timeout=20) for future in futures]

    assert results == [(workspace / "first.txt",), (workspace / "second.txt",)]
    assert not (workspace / ".modelable" / "locks").exists()
