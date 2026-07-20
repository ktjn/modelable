from __future__ import annotations

import hashlib
import os
import time
import uuid
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


class FileTransactionCommittedError(Exception):
    """Promotion committed, but post-commit cleanup was incomplete."""

    committed = True

    def __init__(
        self,
        written_paths: Sequence[Path],
        cleanup_errors: Sequence[RollbackError],
    ) -> None:
        self.written_paths = tuple(written_paths)
        self.cleanup_errors = tuple(cleanup_errors)
        details = "\n".join(f"  - {item}" for item in self.cleanup_errors)
        super().__init__(
            "File transaction committed, but cleanup was incomplete:" + (f"\n{details}" if details else "")
        )


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
        copy_file: Callable[[Path, Path], None] | None = None,
        unlink: Callable[..., None] | None = None,
        mkdir: Callable[[Path], None] | None = None,
        lock_write: Callable[[int, bytes], int] = os.write,
        fsync: Callable[[int], None] = os.fsync,
        lock_timeout: float = 0,
        lock_poll_interval: float = 0.01,
        new_id: Callable[[], str] = lambda: uuid.uuid4().hex,
    ) -> None:
        self.workspace_root = workspace_root.resolve() if workspace_root is not None else None
        self._replace = replace
        self._copy_file = copy_file or _copy_file
        self._unlink = unlink or _unlink
        self._mkdir = mkdir or _mkdir
        self._lock_write = lock_write
        self._fsync = fsync
        self._lock_timeout = lock_timeout
        self._lock_poll_interval = lock_poll_interval
        self._token = new_id()
        self._lock_path: Path | None = None
        self._waiter_path: Path | None = None
        self._lock_directories: tuple[Path, ...] = ()

    def promote(
        self,
        files: Sequence[StagedFile],
        *,
        validate: Callable[[], None] | None = None,
    ) -> tuple[Path, ...]:
        ordered = _last_writers(tuple(files))
        if not ordered:
            return ()
        destinations = tuple(file.destination for file in ordered)
        root = self.workspace_root or _common_root(destinations)
        try:
            self._acquire_lock(root)
        except LockContentionError:
            raise
        except Exception as error:
            release_errors = self._release_lock()
            raise FileTransactionError(error, release_errors) from error

        if validate is not None:
            try:
                validate()
            except Exception as error:
                release_errors = self._release_lock()
                if release_errors:
                    raise FileTransactionError(error, release_errors) from error
                raise

        promotions: list[_Promotion] = []
        promoted: list[_Promotion] = []
        created_directories: list[Path] = []
        try:
            for index, file in enumerate(ordered):
                if _file_hash(file.staged_path) != file.content_hash:
                    raise OSError(f"staged file hash verification failed before promotion: {file.staged_path}")
                _ensure_parent(
                    file.destination.parent,
                    mkdir=self._mkdir,
                    created=created_directories,
                )
                temporary = file.destination.parent / (f".{file.destination.name}.modelable-tmp-{self._token}-{index}")
                backup = (
                    file.destination.parent / f".{file.destination.name}.modelable-backup-{self._token}-{index}"
                    if file.destination.exists()
                    else None
                )
                promotion = _Promotion(file, temporary, backup)
                promotions.append(promotion)
                if backup is not None:
                    self._copy_file(file.destination, backup)
                self._copy_file(file.staged_path, temporary)

            for promotion in promotions:
                self._replace(promotion.temporary, promotion.file.destination)
                promoted.append(promotion)

            for promotion in promotions:
                if _file_hash(promotion.file.destination) != promotion.file.content_hash:
                    raise OSError(f"post-write hash verification failed for {promotion.file.destination}")
        except Exception as error:
            rollback_errors = self._rollback(
                promoted,
                promotions,
                created_directories,
            )
            rollback_errors.extend(self._release_lock())
            raise FileTransactionError(error, rollback_errors) from error

        cleanup_errors = self._dispose_after_commit(promotions)
        cleanup_errors.extend(self._release_lock())
        written_paths = tuple(sorted(destinations))
        if cleanup_errors:
            raise FileTransactionCommittedError(written_paths, cleanup_errors)
        return written_paths

    def _acquire_lock(self, root: Path) -> None:
        lock_path = root / ".modelable" / "locks" / "compilation.lock"
        self._lock_directories = (lock_path.parent, lock_path.parent.parent)
        deadline = time.monotonic() + self._lock_timeout
        waiter_path = lock_path.with_name(f".compilation-waiter-{self._token}-{uuid.uuid4().hex}")
        while True:
            _ensure_parent(lock_path.parent, mkdir=self._mkdir)
            try:
                waiter_descriptor = os.open(
                    waiter_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
                os.close(waiter_descriptor)
                self._waiter_path = waiter_path
                break
            except FileExistsError:
                waiter_path = lock_path.with_name(f".compilation-waiter-{self._token}-{uuid.uuid4().hex}")
            except FileNotFoundError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(self._lock_poll_interval)
        while True:
            try:
                descriptor = os.open(
                    lock_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
                break
            except FileExistsError as exc:
                if time.monotonic() >= deadline:
                    self._remove_waiter()
                    self._cleanup_lock_directories()
                    raise LockContentionError(f"Compilation promotion is already in progress for {root}.") from exc
                time.sleep(self._lock_poll_interval)
            except FileNotFoundError:
                if time.monotonic() >= deadline:
                    self._remove_waiter()
                    self._cleanup_lock_directories()
                    raise
                time.sleep(self._lock_poll_interval)
        self._lock_path = lock_path
        self._remove_waiter()
        try:
            self._lock_write(descriptor, b"locked\n")
            self._fsync(descriptor)
        finally:
            os.close(descriptor)

    def _rollback(
        self,
        promoted: Sequence[_Promotion],
        promotions: Sequence[_Promotion],
        created_directories: Sequence[Path],
    ) -> list[RollbackError]:
        errors: list[RollbackError] = []
        preserved_backups: set[Path] = set()
        for promotion in reversed(promoted):
            try:
                if promotion.backup is None:
                    self._unlink(promotion.file.destination, missing_ok=True)
                else:
                    self._replace(promotion.backup, promotion.file.destination)
            except Exception as error:
                errors.append(RollbackError(promotion.file.destination, error))
                if promotion.backup is not None:
                    preserved_backups.add(promotion.backup)
        self._cleanup_preparation(
            promotions,
            errors,
            preserved=preserved_backups,
        )
        for directory in reversed(tuple(dict.fromkeys(created_directories))):
            try:
                directory.rmdir()
            except FileNotFoundError:
                continue
            except OSError as error:
                if directory.exists() and not any(directory.iterdir()):
                    errors.append(RollbackError(directory, error))
        return errors

    def _cleanup_preparation(
        self,
        promotions: Sequence[_Promotion],
        errors: list[RollbackError],
        *,
        preserved: set[Path] | None = None,
    ) -> None:
        keep = preserved or set()
        for promotion in promotions:
            for path in (promotion.temporary, promotion.backup):
                if path is None or path in keep:
                    continue
                try:
                    self._unlink(path, missing_ok=True)
                except OSError as error:
                    errors.append(RollbackError(path, error))

    def _dispose_after_commit(
        self,
        promotions: Sequence[_Promotion],
    ) -> list[RollbackError]:
        errors: list[RollbackError] = []
        for promotion in promotions:
            if promotion.backup is None:
                continue
            try:
                self._unlink(promotion.backup, missing_ok=True)
            except OSError as error:
                errors.append(RollbackError(promotion.backup, error))
                errors.extend(self._quarantine(promotion.backup))
        return errors

    def _release_lock(self) -> list[RollbackError]:
        errors: list[RollbackError] = []
        self._remove_waiter()
        if self._lock_path is not None:
            lock_path = self._lock_path
            try:
                self._unlink(lock_path, missing_ok=True)
            except OSError:
                released = lock_path.with_name(f".compilation-lock-released-{self._token}")
                try:
                    self._replace(lock_path, released)
                except OSError as release_error:
                    errors.append(RollbackError(lock_path, release_error))
                else:
                    with suppress(OSError):
                        self._unlink(released, missing_ok=True)
            self._lock_path = None
        self._cleanup_lock_directories()
        return errors

    def _remove_waiter(self) -> None:
        if self._waiter_path is None:
            return
        with suppress(OSError):
            self._unlink(self._waiter_path, missing_ok=True)
        self._waiter_path = None

    def _cleanup_lock_directories(self) -> None:
        for directory in self._lock_directories:
            with suppress(FileNotFoundError, OSError):
                directory.rmdir()
        self._lock_directories = ()

    def _quarantine(self, path: Path) -> list[RollbackError]:
        errors: list[RollbackError] = []
        path_id = hashlib.sha256(os.fsencode(path)).hexdigest()[:12]
        quarantine = path.with_name(f".modelable-cleanup-{self._token}-{path_id}")
        try:
            self._replace(path, quarantine)
        except OSError as error:
            errors.append(RollbackError(path, error))
            return errors
        try:
            self._unlink(quarantine, missing_ok=True)
        except OSError as error:
            errors.append(RollbackError(quarantine, error))
        return errors


def _last_writers(files: tuple[StagedFile, ...]) -> tuple[StagedFile, ...]:
    identities = tuple(file.destination.resolve(strict=False) for file in files)
    last_index = {identity: index for index, identity in enumerate(identities)}
    return tuple(file for index, file in enumerate(files) if last_index[identities[index]] == index)


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


def _unlink(path: Path, *, missing_ok: bool = False) -> None:
    path.unlink(missing_ok=missing_ok)


def _mkdir(path: Path) -> None:
    path.mkdir()


def _ensure_parent(
    path: Path,
    *,
    mkdir: Callable[[Path], None],
    created: list[Path] | None = None,
) -> None:
    missing: list[Path] = []
    current = path
    while not current.exists():
        missing.append(current)
        current = current.parent
    for directory in reversed(missing):
        try:
            mkdir(directory)
        except FileExistsError:
            continue
        if created is not None:
            created.append(directory)


def _common_root(destinations: Sequence[Path]) -> Path:
    resolved_parents = [str(path.resolve(strict=False).parent) for path in destinations]
    return Path(os.path.commonpath(resolved_parents))


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
