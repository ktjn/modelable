from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

class RuntimeAdapter(ABC):
    """Base interface for Modelable runtime adapters."""

    @abstractmethod
    def bootstrap(self, config: dict[str, Any]) -> None:
        """Initialize the target environment."""
        ...

    @abstractmethod
    def materialize(self, projection_plan: dict[str, Any], data: Any) -> None:
        """Stream or update data into the target materialization."""
        ...
