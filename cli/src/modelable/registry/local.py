from __future__ import annotations

from pathlib import Path
from shutil import copy2

from modelable.registry.base import Registry


class LocalRegistry(Registry):
    """Local file-based registry."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def push(self, registry_path: Path) -> None:
        """Push a registry index to the registry."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if registry_path.resolve() == self.path.resolve():
            return
        copy2(registry_path, self.path)

    def pull(self, dest_path: Path) -> None:
        """Pull a registry index from the registry."""
        if self.path.resolve() == dest_path.resolve():
            return
        copy2(self.path, dest_path)
