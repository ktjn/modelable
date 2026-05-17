from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from modelable.parser.ir import MdlFile
from modelable.parser.parse import parse_file_to_ir
from modelable.planner.planner import expand_auto_projections
from modelable.registry.resolver import validate_references
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

    # Expand auto projections before merged validation so that explicit
    # projections can reference generated projection versions.
    auto_projection_errors = expand_auto_projections(merged)
    errors.extend((Path("<workspace>"), error) for error in auto_projection_errors)

    errors.extend(_validate_merged_workspace(sources, merged))
    return Workspace(sources=sources, mdl=merged, errors=errors)


def _validate_merged_workspace(
    sources: list[WorkspaceSource], merged: MdlFile
) -> list[tuple[Path, str]]:
    errors: list[tuple[Path, str]] = []
    domains: dict[str, Path] = {}
    model_versions: dict[tuple[str, str, int], Path] = {}
    projection_versions: dict[tuple[str, str, int], Path] = {}
    generated_projection_versions: dict[tuple[str, str, int], Path] = {}

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
                    # Skip auto-generated projections when checking for explicit
                    # projection conflicts — they are validated separately.
                    if version.auto_generated:
                        continue
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

            for auto_projection in domain.auto_projections:
                for target in auto_projection.targets:
                    projection_name = _generated_projection_name(
                        auto_projection.model, target.kind
                    )
                    key = (domain.name, projection_name, auto_projection.version)

                    previous_generated_path = generated_projection_versions.get(key)
                    if previous_generated_path is not None:
                        errors.append(
                            (
                                source.path,
                                "generated projection name "
                                f"{domain.name}.{projection_name}@{auto_projection.version} "
                                f"conflicts with auto projection declared in "
                                f"{previous_generated_path}",
                            )
                        )
                    else:
                        generated_projection_versions[key] = source.path

                    explicit_projection_path = projection_versions.get(key)
                    if explicit_projection_path is not None:
                        errors.append(
                            (
                                source.path,
                                "generated projection name "
                                f"{domain.name}.{projection_name}@{auto_projection.version} "
                                f"conflicts with explicit projection declared in "
                                f"{explicit_projection_path}",
                            )
                        )

    errors.extend((Path("<workspace>"), error) for error in validate_references(merged))
    return errors


def _generated_projection_name(model_name: str, kind: str) -> str:
    suffixes = {
        "db": "Db",
        "request": "Request",
        "reply": "Reply",
        "event": "Event",
    }
    return f"{model_name}{suffixes[kind]}"
