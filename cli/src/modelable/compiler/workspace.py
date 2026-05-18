from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path

from modelable.diagnostics.model import Diagnostic
from modelable.expressions.cel import CelContext, parse_cel, validate_cel_expr
from modelable.parser.ir import ComputedMapping, MdlFile
from modelable.parser.parse import parse_text_to_ir
from modelable.planner.planner import expand_auto_projections
from modelable.registry.resolver import resolve_model_ref, validate_references
from modelable.validation.semantic import validate_diagnostics


@dataclass(frozen=True)
class WorkspaceSource:
    path: Path | None
    uri: str
    text: str
    mdl: MdlFile
    errors: list[Diagnostic]
    content_hash: str


@dataclass(frozen=True)
class Workspace:
    sources: list[WorkspaceSource]
    mdl: MdlFile
    errors: list[Diagnostic]


@dataclass(frozen=True)
class WorkspaceDocumentSource:
    path: Path | None
    uri: str
    text: str


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
    sources = [
        WorkspaceDocumentSource(
            path=mdl_path,
            uri=mdl_path.resolve().as_uri(),
            text=mdl_path.read_text(encoding="utf-8"),
        )
        for mdl_path in discover_mdl_files(path)
    ]
    return load_workspace_from_sources(sources)


def load_workspace_from_sources(sources: list[WorkspaceDocumentSource]) -> Workspace:
    workspace_sources: list[WorkspaceSource] = []
    errors: list[Diagnostic] = []
    merged = MdlFile()

    for source in sources:
        source_location = str(source.path) if source.path is not None else source.uri
        mdl = parse_text_to_ir(source.text, path=source_location)
        source_errors = validate_diagnostics(mdl, path=source_location)
        workspace_sources.append(
            WorkspaceSource(
                path=source.path,
                uri=source.uri,
                text=source.text,
                mdl=mdl,
                errors=source_errors,
                content_hash=_content_hash(source.text),
            )
        )
        errors.extend(source_errors)
        merged.domains.extend(mdl.domains)
        merged.bindings.extend(mdl.bindings)
        if mdl.workspace is not None:
            merged.workspace = mdl.workspace

    auto_projection_errors = expand_auto_projections(merged)
    errors.extend(
        Diagnostic(code="SEM", message=error, severity="error", path="<workspace>")
        for error in auto_projection_errors
    )

    errors.extend(_validate_merged_workspace(workspace_sources, merged))
    errors.extend(_validate_cel(merged))
    return Workspace(sources=workspace_sources, mdl=merged, errors=errors)


def _validate_merged_workspace(
    sources: list[WorkspaceSource], merged: MdlFile
) -> list[Diagnostic]:
    errors: list[Diagnostic] = []
    domains: dict[str, Path | None] = {}
    model_versions: dict[tuple[str, str, int], Path | None] = {}
    projection_versions: dict[tuple[str, str, int], Path | None] = {}
    generated_projection_versions: dict[tuple[str, str, int], Path | None] = {}

    for source in sources:
        for domain in source.mdl.domains:
            previous_domain_path = domains.get(domain.name)
            if previous_domain_path is not None:
                errors.append(
                    Diagnostic(
                        code="SEM",
                        message=(
                            f"duplicate domain '{domain.name}' "
                            f"also defined in {previous_domain_path}"
                        ),
                        severity="error",
                        path=str(source.path) if source.path is not None else source.uri,
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
                            Diagnostic(
                                code="SEM",
                                message=(
                                    "duplicate model version "
                                    f"{domain.name}.{model_name}@{version.version} "
                                    f"also defined in {previous_model_path}"
                                ),
                                severity="error",
                                path=str(source.path) if source.path is not None else source.uri,
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
                            Diagnostic(
                                code="SEM",
                                message=(
                                    "duplicate projection version "
                                    f"{domain.name}.{projection_name}@{version.version} "
                                    f"also defined in {previous_projection_path}"
                                ),
                                severity="error",
                                path=str(source.path) if source.path is not None else source.uri,
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
                            Diagnostic(
                                code="SEM",
                                message=(
                                    "generated projection name "
                                    f"{domain.name}.{projection_name}@{auto_projection.version} "
                                    f"conflicts with auto projection declared in "
                                    f"{previous_generated_path}"
                                ),
                                severity="error",
                                path=str(source.path) if source.path is not None else source.uri,
                            )
                        )
                    else:
                        generated_projection_versions[key] = source.path

                    explicit_projection_path = projection_versions.get(key)
                    if explicit_projection_path is not None:
                        errors.append(
                            Diagnostic(
                                code="SEM",
                                message=(
                                    "generated projection name "
                                    f"{domain.name}.{projection_name}@{auto_projection.version} "
                                    f"conflicts with explicit projection declared in "
                                    f"{explicit_projection_path}"
                                ),
                                severity="error",
                                path=str(source.path) if source.path is not None else source.uri,
                            )
                        )

    errors.extend(
        Diagnostic(code="SEM", message=error, severity="error", path="<workspace>")
        for error in validate_references(merged)
    )
    return errors


def _validate_cel(merged: MdlFile) -> list[Diagnostic]:
    """Validate CEL expressions in all projections across the merged workspace."""
    errors: list[Diagnostic] = []

    for domain in merged.domains:
        for projection_name, versions in domain.projections.items():
            for pv in versions:
                fqn = f"{domain.name}.{projection_name}@{pv.version}"

                # Build alias -> set[field_name] from source and all joins
                source_fields: dict[str, set[str]] = {}
                all_sources = [(pv.source.model, pv.source.version, pv.source.alias)]
                for join in pv.joins:
                    all_sources.append((join.model, join.version, join.alias))
                for model_ref, version_spec, alias in all_sources:
                    try:
                        resolved = resolve_model_ref(merged, model_ref, version_spec)
                        source_fields[alias] = {f.name for f in resolved.version.fields}
                    except LookupError:
                        pass

                ctx = CelContext(
                    source_fields=source_fields,
                    has_group_by=bool(pv.group_by),
                    fqn=fqn,
                )

                for proj_field in pv.fields:
                    if not isinstance(proj_field.mapping, ComputedMapping):
                        continue
                    expression = proj_field.mapping.expression
                    ast, parse_errors = parse_cel(expression)
                    for err in parse_errors:
                        errors.append(
                            Diagnostic(
                                code="CEL",
                                message=f"{fqn}.{proj_field.name}: {err}",
                                severity="error",
                                path="<workspace>",
                            )
                        )
                    if ast is not None:
                        result = validate_cel_expr(ast, ctx)
                        for err in result.errors:
                            errors.append(
                                Diagnostic(
                                    code="CEL",
                                    message=f"{proj_field.name}: {err}",
                                    severity="error",
                                    path="<workspace>",
                                )
                            )

                for join in pv.joins:
                    if not join.on:
                        continue
                    ast, parse_errors = parse_cel(join.on)
                    for err in parse_errors:
                        errors.append(
                            Diagnostic(
                                code="CEL",
                                message=f"{fqn} join on: {err}",
                                severity="error",
                                path="<workspace>",
                            )
                        )
                    if ast is not None:
                        result = validate_cel_expr(ast, ctx)
                        for err in result.errors:
                            errors.append(
                                Diagnostic(
                                    code="CEL",
                                    message=f"{fqn} join on: {err}",
                                    severity="error",
                                    path="<workspace>",
                                )
                            )

    return errors


def _generated_projection_name(model_name: str, kind: str) -> str:
    suffixes = {
        "db": "Db",
        "request": "Request",
        "reply": "Reply",
        "event": "Event",
    }
    return f"{model_name}{suffixes[kind]}"


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
