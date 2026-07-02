from __future__ import annotations

from pathlib import Path

from modelable.registry.base import Registry
from modelable.registry.local import LocalRegistry


def get_registry(registry_path: str | Path) -> Registry:
    """Return a Registry instance based on the registry path."""
    registry_location = registry_path.as_posix() if isinstance(registry_path, Path) else registry_path
    if registry_location.startswith("oci://"):
        from modelable.registry.oci import OCIRegistry

        return OCIRegistry(registry_location)

    return LocalRegistry(Path(registry_location))
