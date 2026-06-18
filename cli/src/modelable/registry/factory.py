from __future__ import annotations

from pathlib import Path

from modelable.registry.base import Registry
from modelable.registry.local import LocalRegistry


def get_registry(registry_path: Path) -> Registry:
    """Return a Registry instance based on the registry path."""
    # If path is a file, return LocalRegistry
    # If path looks like an OCI URL (e.g., oci://), return OCIRegistry
    if registry_path.as_posix().startswith("oci://"):
        from modelable.registry.oci import OCIRegistry

        return OCIRegistry(registry_path.as_posix())

    return LocalRegistry(registry_path)
