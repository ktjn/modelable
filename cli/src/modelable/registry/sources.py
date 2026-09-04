from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Protocol

from modelable.compiler.workspace import (
    Workspace,
    WorkspaceDocumentSource,
    discover_mdl_files,
    load_workspace_from_sources,
)
from modelable.parser.parse import parse_text_to_ir
from modelable.registry.resolver import resolve_declaration
from modelable.registry.signature import compute_version_signature


class SourceAdapter(Protocol):
    """Load a resolution source into a validated compiler workspace."""

    def load(self, source: Path) -> Workspace:
        """Load SOURCE; any network access must be explicit in the adapter."""
        ...


class LocalSourceAdapter:
    """Resolve a local Modelable file or directory without network access."""

    def load(self, source: Path) -> Workspace:
        primary_files = discover_mdl_files(source)
        source_root = source if source.is_dir() else source.parent
        mirror_root = source_root / "mirror"
        mirror_root_resolved = mirror_root.resolve()
        primary_files = [path for path in primary_files if not path.resolve().is_relative_to(mirror_root_resolved)]
        all_files = list(primary_files)
        loaded_registries: set[str] = set()
        index = 0
        while index < len(all_files):
            path = all_files[index]
            imports = {
                imported.registry
                for imported in parse_text_to_ir(path.read_text(encoding="utf-8")).imports
                if imported.registry is not None
            }
            for registry in sorted(imports - loaded_registries):
                loaded_registries.add(registry)
                registry_path = mirror_root / registry
                if not registry_path.is_dir():
                    raise ValueError(f"missing local registry mirror for {registry!r}: {registry_path}")
                all_files.extend(discover_mdl_files(registry_path))
            index += 1

        documents = [_document(path) for path in all_files]
        workspace = load_workspace_from_sources(documents)
        _verify_pinned_imports(workspace)
        return workspace


def _document(path: Path) -> WorkspaceDocumentSource:
    return WorkspaceDocumentSource(
        path=path,
        uri=path.resolve().as_uri(),
        text=path.read_text(encoding="utf-8"),
    )


def _verify_pinned_imports(workspace: Workspace) -> None:
    domains = {domain.name: domain for domain in workspace.mdl.domains}
    for imported in workspace.mdl.imports:
        if imported.pinned_ref is None:
            continue
        if imported.pinned_version is None or imported.pinned_signature is None:
            raise ValueError(f"pinned import for {imported.domain!r} is incomplete")
        qualified_name = imported.pinned_ref
        if "." not in qualified_name:
            raise ValueError(f"pinned import reference must be qualified: {qualified_name!r}")
        domain_name, name = qualified_name.rsplit(".", 1)
        domain = domains.get(domain_name)
        if domain is None:
            raise ValueError(f"pinned import references missing domain {domain_name!r}")
        try:
            resolved = resolve_declaration(
                workspace.mdl,
                qualified_name,
                imported.pinned_version,
                allowed_kinds=frozenset({"model", "projection"}),
            )
        except LookupError:
            raise ValueError(
                f"pinned import references missing contract {qualified_name}@{imported.pinned_version}"
            ) from None
        actual_signature = compute_version_signature(domain_name, name, resolved.version)
        if actual_signature != imported.pinned_signature:
            raise ValueError(
                f"pinned import signature mismatch for {qualified_name}@{imported.pinned_version}: "
                f"expected {imported.pinned_signature}, found {actual_signature}"
            )


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
