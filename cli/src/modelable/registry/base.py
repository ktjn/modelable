from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class Registry(ABC):
    """Abstract base class for a Modelable registry."""

    @abstractmethod
    def push(self, registry_path: Path) -> None:
        """Push a registry index to the registry."""
        ...

    @abstractmethod
    def pull(self, dest_path: Path) -> None:
        """Pull a registry index from the registry."""
        ...
