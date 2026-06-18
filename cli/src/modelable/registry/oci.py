from __future__ import annotations

from pathlib import Path

from modelable.registry.base import Registry


class OCIRegistry(Registry):
    """OCI-compliant registry."""

    def __init__(self, url: str) -> None:
        self.url = url

    def push(self, registry_path: Path) -> None:
        """Push a registry index to the OCI registry."""
        # TODO: Implement OCI push (e.g., skopeo copy)
        print(f"Pushing to {self.url} (not implemented)")

    def pull(self, dest_path: Path) -> None:
        """Pull a registry index from the OCI registry."""
        # TODO: Implement OCI pull (e.g., skopeo copy)
        print(f"Pulling from {self.url} (not implemented)")
