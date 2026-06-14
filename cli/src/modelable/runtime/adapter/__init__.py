from __future__ import annotations

from .base import RuntimeAdapter
from .postgres import PostgresAdapter

__all__ = ["RuntimeAdapter", "get_adapter"]

_ADAPTERS = {
    "postgres": PostgresAdapter,
}

def get_adapter(adapter_type: str) -> RuntimeAdapter:
    adapter_class = _ADAPTERS.get(adapter_type)
    if not adapter_class:
        raise ValueError(f"Unknown adapter type: {adapter_type}")
    return adapter_class()
