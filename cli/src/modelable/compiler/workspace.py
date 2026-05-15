from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from modelable.parser.ir import MdlFile
from modelable.parser.parse import parse_file_to_ir
from modelable.validation.semantic import validate


@dataclass(frozen=True)
class WorkspaceSource:
    path: Path
    mdl: MdlFile
    errors: list[str]


@dataclass(frozen=True)
class Workspace:
    sources: list[WorkspaceSource]
    mdl: MdlFile
    errors: list[tuple[Path, str]]


def discover_mdl_files(path: str | Path) -> list[Path]:
    """Return .mdl files from a file or directory in deterministic order."""
    root = Path(path)
    if root.is_file():
        if root.suffix != ".mdl":
            raise FileNotFoundError(f"{root} is not a .mdl file")
        return [root]

    files = sorted(root.rglob("*.mdl"), key=lambda item: item.as_posix())
    if not files:
        raise FileNotFoundError(f"No .mdl files found under {root}")
    return files


def load_workspace(path: str | Path) -> Workspace:
    """Parse and validate all local .mdl files under path."""
    sources: list[WorkspaceSource] = []
    errors: list[tuple[Path, str]] = []
    merged = MdlFile()

    for mdl_path in discover_mdl_files(path):
        mdl = parse_file_to_ir(mdl_path)
        source_errors = validate(mdl)
        sources.append(WorkspaceSource(path=mdl_path, mdl=mdl, errors=source_errors))
        errors.extend((mdl_path, error) for error in source_errors)
        merged.domains.extend(mdl.domains)
        merged.bindings.extend(mdl.bindings)
        if mdl.workspace is not None:
            merged.workspace = mdl.workspace

    errors.extend(_validate_merged_workspace(sources))
    return Workspace(sources=sources, mdl=merged, errors=errors)


def _validate_merged_workspace(sources: list[WorkspaceSource]) -> list[tuple[Path, str]]:
    errors: list[tuple[Path, str]] = []
    domains: dict[str, Path] = {}
    model_versions: dict[tuple[str, str, int], Path] = {}
    projection_versions: dict[tuple[str, str, int], Path] = {}

    for source in sources:
        for domain in source.mdl.domains:
            previous_domain_path = domains.get(domain.name)
            if previous_domain_path is not None:
                errors.append(
                    (
                        source.path,
                        f"duplicate domain '{domain.name}' "
                        f"also defined in {previous_domain_path}",
                    )
                )
            else:
                domains[domain.name] = source.path

            for model_name, versions in domain.models.items():
                for version in versions:
                    key = (domain.name, model_name, version.version)
                    previous_model_path = model_versions.get(key)
                    if previous_model_path is not None:
                        errors.append(
                            (
                                source.path,
                                "duplicate model version "
                                f"{domain.name}.{model_name}@{version.version} "
                                f"also defined in {previous_model_path}",
                            )
                        )
                    else:
                        model_versions[key] = source.path

            for projection_name, versions in domain.projections.items():
                for version in versions:
                    key = (domain.name, projection_name, version.version)
                    previous_projection_path = projection_versions.get(key)
                    if previous_projection_path is not None:
                        errors.append(
                            (
                                source.path,
                                "duplicate projection version "
                                f"{domain.name}.{projection_name}@{version.version} "
                                f"also defined in {previous_projection_path}",
                            )
                        )
                    else:
                        projection_versions[key] = source.path

    return errors
