from __future__ import annotations

import hashlib
import os
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StagedFile:
    destination: Path
    staged_path: Path
    content_hash: str

    @classmethod
    def from_path(cls, *, destination: Path, staged_path: Path) -> StagedFile:
        return cls(
            destination=destination,
            staged_path=staged_path,
            content_hash=_file_hash(staged_path),
        )


@dataclass(frozen=True)
class RollbackError:
    path: Path
    error: Exception

    def __str__(self) -> str:
        return f"{self.path}: {self.error}"


class LockContentionError(Exception):
    """Another compilation transaction owns the workspace lock."""


class FileTransactionError(Exception):
    """A failed promotion and every error encountered while rolling it back."""

    def __init__(
        self,
        error: Exception,
        rollback_errors: Sequence[RollbackError] = (),
    ) -> None:
        self.error = error
        self.rollback_errors = tuple(rollback_errors)
        message = f"File transaction failed: {error}"
        if self.rollback_errors:
            details = "\n".join(f"  - {item}" for item in self.rollback_errors)
            message += f"\nRollback errors:\n{details}"
        super().__init__(message)


@dataclass(frozen=True)
class _Promotion:
    file: StagedFile
    temporary: Path
    backup: Path | None


class FileTransaction:
    def __init__(
        self,
        *,
        workspace_root: Path | None = None,
        replace: Callable[[str | Path, str | Path], None] = os.replace,
    ) -> None:
        self.workspace_root = workspace_root.resolve() if workspace_root is not None else None
        self._replace = replace
        self._lock_path: Path | None = None
        self._lock_directories: tuple[Path, ...] = ()

    def promote(self, files: Sequence[StagedFile]) -> tuple[Path, ...]:
        ordered = tuple(files)
        if not ordered:
            return ()
        destinations = [file.destination for file in ordered]
        if len(set(destinations)) != len(destinations):
            raise FileTransactionError(ValueError("duplicate transaction destination"))
        root = self.workspace_root or _common_root(destinations)
        self._acquire_lock(root)
        promotions: list[_Promotion] = []
        promoted: list[_Promotion] = []
        created_directories: list[Path] = []
        try:
            for index, file in enumerate(ordered):
                if _file_hash(file.staged_path) != file.content_hash:
                    raise OSError(f"staged file hash verification failed before promotion: {file.staged_path}")
                created_directories.extend(_ensure_parent(file.destination.parent))
                temporary = file.destination.parent / (f".{file.destination.name}.modelable-tmp-{index}")
                backup = (
                    file.destination.parent / f".{file.destination.name}.modelable-backup-{index}"
                    if file.destination.exists()
                    else None
                )
                if temporary.exists() or (backup is not None and backup.exists()):
                    raise OSError(f"transaction temporary already exists for {file.destination}")
                if backup is not None:
                    _copy_file(file.destination, backup)
                _copy_file(file.staged_path, temporary)
                promotions.append(_Promotion(file, temporary, backup))

            for promotion in promotions:
                self._replace(promotion.temporary, promotion.file.destination)
                promoted.append(promotion)

            for promotion in promotions:
                if _file_hash(promotion.file.destination) != promotion.file.content_hash:
                    raise OSError(f"post-write hash verification failed for {promotion.file.destination}")

            for promotion in promotions:
                if promotion.backup is not None:
                    promotion.backup.unlink()
            return tuple(sorted(destinations))
        except Exception as error:
            rollback_errors = self._rollback(
                promoted,
                promotions,
                created_directories,
            )
            raise FileTransactionError(error, rollback_errors) from error
        finally:
            self._cleanup_temporaries(promotions)
            self._release_lock()

    def _acquire_lock(self, root: Path) -> None:
        lock_path = root / ".modelable" / "locks" / "compilation.lock"
        self._lock_directories = tuple(_ensure_parent(lock_path.parent))
        try:
            descriptor = os.open(
                lock_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except FileExistsError as exc:
            _remove_empty_directories(self._lock_directories)
            self._lock_directories = ()
            raise LockContentionError(f"Compilation promotion is already in progress for {root}.") from exc
        try:
            os.write(descriptor, b"locked\n")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        self._lock_path = lock_path

    def _rollback(
        self,
        promoted: Sequence[_Promotion],
        promotions: Sequence[_Promotion],
        created_directories: Sequence[Path],
    ) -> tuple[RollbackError, ...]:
        errors: list[RollbackError] = []
        for promotion in reversed(promoted):
            try:
                if promotion.backup is None:
                    promotion.file.destination.unlink(missing_ok=True)
                else:
                    self._replace(promotion.backup, promotion.file.destination)
            except Exception as error:
                errors.append(RollbackError(promotion.file.destination, error))
        self._cleanup_temporaries(promotions, errors)
        for directory in dict.fromkeys(created_directories):
            try:
                directory.rmdir()
            except FileNotFoundError:
                continue
            except OSError as error:
                if directory.exists() and not any(directory.iterdir()):
                    errors.append(RollbackError(directory, error))
        return tuple(errors)

    def _cleanup_temporaries(
        self,
        promotions: Sequence[_Promotion],
        errors: list[RollbackError] | None = None,
    ) -> None:
        for promotion in promotions:
            for path in (promotion.temporary, promotion.backup):
                if path is None:
                    continue
                try:
                    path.unlink(missing_ok=True)
                except OSError as error:
                    if errors is not None:
                        errors.append(RollbackError(path, error))

    def _release_lock(self) -> None:
        if self._lock_path is not None:
            self._lock_path.unlink(missing_ok=True)
            self._lock_path = None
        _remove_empty_directories(self._lock_directories)
        self._lock_directories = ()


def _copy_file(source: Path, destination: Path) -> None:
    content = source.read_bytes()
    descriptor = os.open(
        destination,
        os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0),
        0o600,
    )
    try:
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _ensure_parent(path: Path) -> list[Path]:
    missing: list[Path] = []
    current = path
    while not current.exists():
        missing.append(current)
        current = current.parent
    for directory in reversed(missing):
        directory.mkdir()
    return missing


def _remove_empty_directories(paths: Sequence[Path]) -> None:
    for path in paths:
        with suppress(OSError):
            path.rmdir()


def _common_root(destinations: Sequence[Path]) -> Path:
    resolved_parents = [str(path.resolve(strict=False).parent) for path in destinations]
    return Path(os.path.commonpath(resolved_parents))


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
