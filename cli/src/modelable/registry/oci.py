from __future__ import annotations

from pathlib import Path

from modelable.registry.base import Registry


class OCIRegistryError(RuntimeError):
    """Raised when OCI registry operations cannot be completed."""


class OCIRegistry(Registry):
    """OCI-compliant registry."""

    def __init__(self, url: str) -> None:
        self.url = url

    def push(self, registry_path: Path) -> None:
        """Push a registry index to the OCI registry."""
        raise OCIRegistryError(
            f"OCI registry support is not implemented for {self.url}; "
            "use a local registry path or Apicurio artifact publishing instead."
        )

    def pull(self, dest_path: Path) -> None:
        """Pull a registry index from the OCI registry."""
        raise OCIRegistryError(
            f"OCI registry support is not implemented for {self.url}; "
            "use a local registry path or Apicurio artifact publishing instead."
        )
