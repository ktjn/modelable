from __future__ import annotations

import os
from pathlib import Path

import pytest

from modelable.operations.file_transaction import (
    FileTransaction,
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
    assert not list(workspace.rglob("*.modelable-tmp-*"))
    assert not list(workspace.rglob("*.modelable-backup-*"))
