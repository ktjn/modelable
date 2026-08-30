from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Protocol

from modelable.compiler.workspace import Workspace, WorkspaceDocumentSource, load_workspace, load_workspace_from_sources


class SourceAdapter(Protocol):
    """Load a resolution source into a validated compiler workspace."""

    def load(self, source: Path) -> Workspace:
        """Load SOURCE; any network access must be explicit in the adapter."""
        ...


class LocalSourceAdapter:
    """Resolve a local Modelable file or directory without network access."""

    def load(self, source: Path) -> Workspace:
        return load_workspace(source)


class GitSourceError(RuntimeError):
    """A local Git source could not be materialized."""


class GitSourceAdapter:
    """Resolve tracked Modelable files from a local Git repository ref."""

    def __init__(self, repository: Path, ref: str) -> None:
        self.repository = repository.resolve()
        self.ref = ref

    def load(self, source: Path) -> Workspace:
        del source
        if not self.repository.is_dir():
            raise GitSourceError(f"Git repository does not exist: {self.repository}")
        if not self.ref:
            raise GitSourceError("Git ref must not be empty")

        paths = self._git("ls-tree", "-r", "-z", "--name-only", self.ref, "--")
        relative_paths = sorted(item for item in paths.split("\0") if item.endswith(".mdl"))
        if not relative_paths:
            raise GitSourceError(f"No .mdl files found at Git ref {self.ref!r}")

        documents = [
            WorkspaceDocumentSource(
                path=None,
                uri=self._uri(relative_path),
                text=self._git("show", f"{self.ref}:{relative_path}"),
            )
            for relative_path in relative_paths
        ]
        return load_workspace_from_sources(documents)

    def _git(self, *args: str) -> str:
        try:
            result = subprocess.run(
                ["git", "-C", str(self.repository), *args],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            detail = exc.stderr.strip() if isinstance(exc, subprocess.CalledProcessError) else str(exc)
            raise GitSourceError(f"Git source resolution failed for ref {self.ref!r}: {detail}") from exc
        return result.stdout

    def _uri(self, relative_path: str) -> str:
        return f"git+{self.repository.as_uri()}@{self.ref}/{relative_path}"
