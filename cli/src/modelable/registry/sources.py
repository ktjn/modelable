from __future__ import annotations

from pathlib import Path
from typing import Protocol

from modelable.compiler.workspace import Workspace, load_workspace


class SourceAdapter(Protocol):
    """Load a resolution source into a validated compiler workspace."""

    def load(self, source: Path) -> Workspace:
        """Load SOURCE; any network access must be explicit in the adapter."""
        ...


class LocalSourceAdapter:
    """Resolve a local Modelable file or directory without network access."""

    def load(self, source: Path) -> Workspace:
        return load_workspace(source)
