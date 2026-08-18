from __future__ import annotations

import json
import os
import sys
import time
import uuid
from contextlib import suppress
from pathlib import Path
from typing import cast

from modelable.parser.ir import MdlFile, latest_semantic_types


class RegistryIdLockContentionError(Exception):
    """Another process is updating the registry ID ledger."""


class RegistryIdLock:
    """A small cross-process lock protecting one registry ID ledger."""

    def __init__(self, ledger_path: Path, *, timeout: float = 30, poll_interval: float = 0.01) -> None:
        self.ledger_path = ledger_path.resolve(strict=False)
        self.lock_path = self.ledger_path.with_name(f".{self.ledger_path.name}.lock")
        self.timeout = timeout
        self.poll_interval = poll_interval
        self._owned = False

    def __enter__(self) -> RegistryIdLock:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                descriptor = os.open(
                    self.lock_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
            except FileExistsError as error:
                if self._reclaim_stale_lock():
                    continue
                if time.monotonic() >= deadline:
                    raise RegistryIdLockContentionError(
                        f"Registry ID allocation is already in progress for {self.ledger_path}."
                    ) from error
                time.sleep(self.poll_interval)
            else:
                try:
                    os.write(descriptor, f"{os.getpid()}\n".encode())
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                self._owned = True
                return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        if self._owned:
            for _ in range(20):
                try:
                    self.lock_path.unlink(missing_ok=True)
                except PermissionError:
                    time.sleep(0.01)
                except OSError:
                    break
                else:
                    self._owned = False
                    return
            released = self.lock_path.with_name(f"{self.lock_path.name}.released-{uuid.uuid4().hex}")
            with suppress(OSError):
                os.replace(self.lock_path, released)
                released.unlink(missing_ok=True)
            self._owned = False

    def _reclaim_stale_lock(self) -> bool:
        try:
            pid = int(self.lock_path.read_text(encoding="utf-8").splitlines()[0])
        except OSError, ValueError, IndexError:
            return False
        if _process_alive(pid):
            return False
        try:
            self.lock_path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            return False
        return True


def _process_alive(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5
        try:
            exit_code = ctypes.c_ulong()
            if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return True
            return exit_code.value == 259
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _qualified_registry_names(mdl: MdlFile) -> list[str]:
    return sorted(
        f"{domain.name}.{decl.name}"
        for domain in mdl.domains
        for decl in latest_semantic_types(domain)
        if decl.registry
    )


def allocate_registry_ids(
    mdl: MdlFile,
    existing: dict[str, int],
    *,
    allow_orphaned: bool = False,
) -> dict[str, int]:
    """Allocate deterministic small-integer ids for every `registry: true`
    semantic type, never reassigning or reusing an id already in `existing`.
    """
    declared = set(_qualified_registry_names(mdl))
    orphaned = sorted(name for name in existing if name not in declared)
    if orphaned and not allow_orphaned:
        joined = ", ".join(orphaned)
        raise ValueError(
            f"registry-ids.lock has {len(orphaned)} orphaned id(s) with no matching "
            f"'registry: true' semantic type declaration: {joined}. Pass "
            "--allow-orphaned-registry-ids to keep them reserved (they are never reused)."
        )

    updated = dict(existing)
    next_id = max(existing.values(), default=0) + 1
    for name in sorted(declared - existing.keys()):
        updated[name] = next_id
        next_id += 1
    return updated


def read_lock_file(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    return cast(dict[str, int], json.loads(path.read_text(encoding="utf-8")))


def write_lock_file(path: Path, ids: dict[str, int]) -> None:
    ordered = dict(sorted(ids.items(), key=lambda item: item[1]))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(ordered, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
