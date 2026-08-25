"""Compact a full-form model version into `evolves`-delta form against its
base (evolution plan A2, instructions #3-5).

Computes the operation sequence via `compiler/version_delta.py::
compute_delta_operations` (evidence-backed rename detection only, and
`None` when field order can't be reproduced without reordering), renders it
as an `evolves` block, and verifies -- before writing anything -- that every
implemented codegen target's output is byte-identical between the original
and the compacted candidate (A2's exit criteria: "no canonical contract or
generated artifact changes").
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path

from modelable.compiler.render import _render_model_evolution
from modelable.compiler.version_delta import compute_delta_operations
from modelable.compiler.workspace import Workspace, WorkspaceDocumentSource, load_workspace, load_workspace_from_sources
from modelable.diagnostics.model import render_diagnostic
from modelable.parser.ir import EvolutionOperation, ModelEvolutionDecl, ModelVersion
from modelable.refactor._model_block import block_contains_comment, find_model_block
from modelable.refactor._target_emitters import TARGET_EMITTERS


class CompactVersionError(ValueError):
    pass


@dataclass(frozen=True)
class CompactVersionResult:
    written_path: Path
    base_version: int
    operations: tuple[EvolutionOperation, ...]
    diff_text: str
    workspace: Workspace


def compact_version(root: Path, domain: str, model: str, version: int) -> CompactVersionResult:
    workspace = load_workspace(root)
    error_diagnostics = [d for d in workspace.errors if d.severity == "error"]
    if error_diagnostics:
        rendered = "; ".join(render_diagnostic(d) for d in error_diagnostics)
        raise CompactVersionError(f"workspace has validation errors: {rendered}")

    domain_def = next((d for d in workspace.mdl.domains if d.name == domain), None)
    if domain_def is None:
        raise CompactVersionError(f"domain '{domain}' not found")
    versions = domain_def.models.get(model, [])
    target_version = next((v for v in versions if v.version == version), None)
    if target_version is None:
        raise CompactVersionError(f"{domain}.{model}@{version}: model version not found")

    lower_versions = [v for v in versions if v.version < version]
    base_version = max(lower_versions, key=lambda v: v.version, default=None)
    if base_version is None:
        raise CompactVersionError(
            f"{domain}.{model}@{version}: no prior version of '{model}' exists to compact against"
        )
    if base_version.model_kind != target_version.model_kind:
        raise CompactVersionError(
            f"{domain}.{model}@{version}: base @ {base_version.version} is a "
            f"{base_version.model_kind.value}, but this version is {target_version.model_kind.value}"
        )

    sources_by_path = {source.path: source.text.splitlines() for source in workspace.sources if source.path is not None}
    span = find_model_block(sources_by_path, domain, model, version)
    if span.is_evolves:
        raise CompactVersionError(f"{domain}.{model}@{version}: already declared via evolves, nothing to compact")
    if block_contains_comment(sources_by_path[span.path], span):
        raise CompactVersionError(
            f"{domain}.{model}@{version}: the field block contains a comment that would be lost by "
            "compaction -- aborting rather than discard it; remove or relocate the comment first"
        )

    operations = compute_delta_operations(base_version, target_version)
    if operations is None:
        raise CompactVersionError(
            f"{domain}.{model}@{version}: cannot compact without reordering fields relative to "
            f"base @ {base_version.version} (evolves-declared fields can only be inherited-in-place, "
            "renamed-in-place, replaced-in-place, removed, or newly added at the end) -- reordering "
            "would change generated field/column order in every codegen target, which A2 forbids"
        )

    decl = _build_evolution_decl(base_version, target_version, operations)
    if decl is None:
        raise CompactVersionError(
            f"{domain}.{model}@{version}: cannot express this version's model-level metadata as a delta -- "
            "an evolves declaration can only inherit model-level @wire annotations or an access block "
            "whole, or replace them whole; it has no syntax for 'explicitly none' when the base has some"
        )

    replacement_lines = [f"{span.leading_whitespace}{line}" for line in _render_model_evolution(model, decl)]
    lines = sources_by_path[span.path]
    sources_by_path[span.path] = lines[: span.start_index] + replacement_lines + lines[span.end_index + 1 :]
    candidate_text_by_path = {path: "\n".join(lines_) + "\n" for path, lines_ in sources_by_path.items()}

    candidate_sources = [
        WorkspaceDocumentSource(path=path, uri=path.resolve().as_uri(), text=candidate_text_by_path[path])
        for path in sorted(candidate_text_by_path)
    ]
    candidate_workspace = load_workspace_from_sources(candidate_sources)
    candidate_errors = [d for d in candidate_workspace.errors if d.severity == "error"]
    if candidate_errors:
        rendered = "; ".join(render_diagnostic(d) for d in candidate_errors)
        raise CompactVersionError(f"compaction would produce an invalid workspace: {rendered}")

    _assert_identical_target_outputs(workspace, candidate_workspace)

    diff_text = _build_diff(span.path, workspace, candidate_text_by_path[span.path])
    return CompactVersionResult(
        written_path=span.path,
        base_version=base_version.version,
        operations=tuple(operations),
        diff_text=diff_text,
        workspace=candidate_workspace,
    )


def apply_compact_version(root: Path, domain: str, model: str, version: int) -> CompactVersionResult:
    result = compact_version(root, domain, model, version)
    candidate_text = next(source.text for source in result.workspace.sources if source.path == result.written_path)
    original_bytes = result.written_path.read_bytes()
    try:
        result.written_path.write_text(candidate_text, encoding="utf-8", newline="\n")
        reloaded = load_workspace(root)
        reload_errors = [d for d in reloaded.errors if d.severity == "error"]
        if reload_errors:
            rendered = "; ".join(render_diagnostic(d) for d in reload_errors)
            raise CompactVersionError(f"reloaded workspace has validation errors: {rendered}")
    except Exception:
        result.written_path.write_bytes(original_bytes)
        raise
    return result


def _build_evolution_decl(
    base: ModelVersion,
    target: ModelVersion,
    operations: list[EvolutionOperation],
) -> ModelEvolutionDecl | None:
    if not target.annotations and base.annotations:
        return None
    if target.access is None and base.access is not None:
        return None
    return ModelEvolutionDecl(
        model_kind=target.model_kind,
        name="",  # unused by _render_model_evolution, which takes model_name separately
        version=target.version,
        change_kind=target.change_kind,
        has_change_kind=target.has_change_kind,
        base_version=base.version,
        operations=operations,
        annotations=target.annotations,
        access=target.access,
        protobuf_reservations=target.protobuf_reservations,
    )


def _assert_identical_target_outputs(original: Workspace, candidate: Workspace) -> None:
    mismatches: list[str] = []
    for target_name, emitter in TARGET_EMITTERS.items():
        out_dir = Path("compact-version-preview")
        try:
            original_artifacts = {a.ref: a for a in emitter(original, out_dir)}  # type: ignore[operator]
            candidate_artifacts = {a.ref: a for a in emitter(candidate, out_dir)}  # type: ignore[operator]
        except Exception as exc:
            raise CompactVersionError(f"target '{target_name}' failed to generate: {exc}") from exc
        if original_artifacts.keys() != candidate_artifacts.keys():
            mismatches.append(f"{target_name}: artifact set changed")
            continue
        for ref, original_artifact in original_artifacts.items():
            candidate_artifact = candidate_artifacts[ref]
            if original_artifact.content != candidate_artifact.content:
                mismatches.append(f"{target_name}:{ref} content differs")
            if original_artifact.warnings != candidate_artifact.warnings:
                mismatches.append(f"{target_name}:{ref} warnings differ")
    if mismatches:
        raise CompactVersionError(
            "compaction would change generated output, which A2 forbids: " + "; ".join(mismatches)
        )


def _build_diff(path: Path, original_workspace: Workspace, candidate_text: str) -> str:
    original_text = next(source.text for source in original_workspace.sources if source.path == path)
    diff = difflib.unified_diff(
        original_text.splitlines(keepends=True),
        candidate_text.splitlines(keepends=True),
        fromfile=str(path),
        tofile=str(path),
    )
    return "".join(diff)
