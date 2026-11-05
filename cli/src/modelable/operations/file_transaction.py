from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
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


class _JournalError(Exception):
    """The promotion journal was unreadable or could not be fully replayed."""


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
        required_directories: Sequence[Path] = (),
    ) -> tuple[Path, ...]:
        ordered = _last_writers(tuple(files))
        directories = _unique_directories(required_directories)
        if not ordered and not directories:
            return ()
        destinations = tuple(file.destination for file in ordered)
        root = self.workspace_root or _common_root((*destinations, *directories))
        try:
            self._acquire_lock(root)
        except LockContentionError:
            raise
        except Exception as error:
            release_errors = self._release_lock()
            raise FileTransactionError(error, release_errors) from error

        try:
            self._recover_interrupted_promotion()
        except Exception as error:
            recovery_errors = [RollbackError(self._journal_path(), error)] if isinstance(error, _JournalError) else []
            recovery_errors.extend(self._release_lock())
            raise FileTransactionError(error, recovery_errors) from error

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
                    _copy_metadata(file.destination, backup)
                self._copy_file(file.staged_path, temporary)

            for directory in directories:
                _ensure_directory(
                    directory,
                    mkdir=self._mkdir,
                    created=created_directories,
                )

            if validate is not None:
                validate()

            self._write_journal(promotions, created_directories)

            for promotion in promotions:
                metadata_source = (
                    promotion.file.destination if promotion.backup is not None else promotion.file.staged_path
                )
                _copy_permissions(metadata_source, promotion.temporary)
                self._replace(promotion.temporary, promotion.file.destination)
                promoted.append(promotion)

            for promotion in promotions:
                if _file_hash(promotion.file.destination) != promotion.file.content_hash:
                    raise OSError(f"post-write hash verification failed for {promotion.file.destination}")

            # Removing the journal is the commit point: until it is gone, a
            # crash is rolled back by the next transaction.
            self._unlink(self._journal_path(), missing_ok=True)
        except Exception as error:
            rollback_errors = self._rollback(
                promoted,
                promotions,
                created_directories,
            )
            if not rollback_errors:
                with suppress(OSError):
                    self._unlink(self._journal_path(), missing_ok=True)
            rollback_errors.extend(self._release_lock())
            raise FileTransactionError(error, rollback_errors) from error

        cleanup_errors = self._dispose_after_commit(promotions)
        cleanup_errors.extend(self._release_lock())
        written_paths = tuple(sorted(destinations))
        if cleanup_errors:
            raise FileTransactionCommittedError(written_paths, cleanup_errors)
        return written_paths

    def recover(self) -> None:
        """Roll back a promotion interrupted by a dead process, if one left a journal.

        Callers that read workspace state before promoting call this first, so
        they never stage output derived from a half-promoted workspace.
        """
        if self.workspace_root is None:
            raise ValueError("recover() requires workspace_root")
        journal = self.workspace_root / ".modelable" / "locks" / "compilation.journal"
        if not journal.exists():
            return
        self._acquire_lock(self.workspace_root)
        try:
            self._recover_interrupted_promotion()
        except Exception as error:
            recovery_errors = [RollbackError(journal, error)] if isinstance(error, _JournalError) else []
            recovery_errors.extend(self._release_lock())
            raise FileTransactionError(error, recovery_errors) from error
        release_errors = self._release_lock()
        if release_errors:
            raise FileTransactionError(OSError("could not release the workspace lock"), release_errors)

    def _journal_path(self) -> Path:
        assert self._lock_path is not None
        return self._lock_path.with_name("compilation.journal")

    def _write_journal(
        self,
        promotions: Sequence[_Promotion],
        created_directories: Sequence[Path],
    ) -> None:
        journal = {
            "version": 1,
            "entries": [
                {
                    "destination": str(item.file.destination),
                    "temporary": str(item.temporary),
                    "backup": str(item.backup) if item.backup is not None else None,
                    "hash": item.file.content_hash,
                }
                for item in promotions
            ],
            "created_directories": [str(path) for path in dict.fromkeys(created_directories)],
        }
        path = self._journal_path()
        temporary = path.with_name(f"{path.name}.{self._token}.tmp")
        descriptor = os.open(
            temporary,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0),
            0o600,
        )
        try:
            os.write(descriptor, json.dumps(journal).encode())
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, path)

    def _recover_interrupted_promotion(self) -> None:
        """Roll back a promotion whose process died before it committed.

        Runs under the workspace lock. A journal that still exists means the
        commit point was never reached, so every destination is returned to its
        pre-promotion state. A journal that cannot be read blocks the
        transaction and is kept for inspection.
        """
        path = self._journal_path()
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            return
        try:
            journal = json.loads(data)
            entries = [
                (
                    Path(entry["destination"]),
                    Path(entry["temporary"]),
                    Path(entry["backup"]) if entry["backup"] is not None else None,
                    str(entry["hash"]),
                )
                for entry in journal["entries"]
            ]
            created = [Path(item) for item in journal["created_directories"]]
        except (ValueError, KeyError, TypeError) as error:
            raise _JournalError(f"Unreadable compilation journal {path}: {error}") from error

        errors: list[RollbackError] = []
        for destination, temporary, backup, content_hash in reversed(entries):
            try:
                if backup is not None:
                    if backup.exists():
                        self._replace(backup, destination)
                elif destination.exists() and _file_hash(destination) == content_hash:
                    self._unlink(destination, missing_ok=True)
                self._unlink(temporary, missing_ok=True)
            except Exception as error:
                errors.append(RollbackError(destination, error))
        for directory in reversed(created):
            with suppress(OSError):
                directory.rmdir()
        if errors:
            details = os.linesep.join(f"  - {item}" for item in errors)
            raise _JournalError(f"Could not recover interrupted compilation promotion:{os.linesep}{details}")
        self._unlink(path, missing_ok=True)

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
                if self._try_reclaim_stale_lock(lock_path):
                    continue
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
            self._lock_write(descriptor, f"{os.getpid()}\n".encode())
            self._fsync(descriptor)
        finally:
            os.close(descriptor)

    def _try_reclaim_stale_lock(self, lock_path: Path) -> bool:
        """Reclaim a lock whose recorded owner process is provably dead.

        Returns True when the stale lock was removed and the caller should
        retry creation. Returns False when the holder is alive, the lock is
        malformed, or any IO error prevents a safe decision — in all such
        cases the caller falls back to polling until the deadline.
        """
        try:
            data = lock_path.read_bytes()
        except OSError:
            return False
        pid = _parse_lock_pid(data)
        if pid is None or _process_alive(pid):
            return False
        try:
            self._unlink(lock_path, missing_ok=True)
        except OSError:
            return False
        return True

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
            except OSError as error:
                # On Windows, the next waiter can open the lock immediately
                # after unlink succeeds while this release is still
                # returning. A sharing violation then means the path belongs
                # to the successor; never rename it as our fallback cleanup.
                if getattr(error, "winerror", None) == 32:
                    self._lock_path = None
                    self._cleanup_lock_directories()
                    return errors
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


def _unique_directories(directories: Sequence[Path]) -> tuple[Path, ...]:
    by_identity = {directory.resolve(strict=False): directory for directory in directories}
    return tuple(sorted(by_identity.values(), key=lambda path: path.as_posix()))


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


def _copy_metadata(source: Path, destination: Path) -> None:
    shutil.copystat(source, destination)


def _copy_permissions(source: Path, destination: Path) -> None:
    shutil.copymode(source, destination)


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


def _ensure_directory(
    path: Path,
    *,
    mkdir: Callable[[Path], None],
    created: list[Path],
) -> None:
    _ensure_parent(path, mkdir=mkdir, created=created)
    if not path.is_dir():
        raise FileExistsError(f"Required output directory is not a directory: {path}")


def _common_root(destinations: Sequence[Path]) -> Path:
    resolved_parents = [str(path.resolve(strict=False).parent) for path in destinations]
    return Path(os.path.commonpath(resolved_parents))


def _process_alive(pid: int) -> bool:
    """Return True if `pid` is running, conservatively defaulting to True.

    A dead holder (ProcessLookupError) reports False, which lets the lock be
    reclaimed. PermissionError means the process exists under another user, so
    it is treated as alive. Any other OSError is treated as alive so we never
    reclaim a lock when liveness cannot be confirmed.
    """
    if sys.platform == "win32":
        return _windows_process_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


def _windows_process_alive(pid: int) -> bool:
    """Use Windows process state because ``os.kill(pid, 0)`` is unreliable there."""
    import ctypes

    process_query_limited_information = 0x1000
    error_access_denied = 5
    still_active = 259
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined,unused-ignore]
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        last_error = int(ctypes.get_last_error())  # type: ignore[attr-defined,unused-ignore]
        return last_error == error_access_denied

    try:
        exit_code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return True
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def _parse_lock_pid(data: bytes) -> int | None:
    """Parse the leading integer PID from lock file bytes, or None if malformed."""
    try:
        return int(data.split(b"\n", 1)[0].strip())
    except ValueError:
        return None


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
