"""Expand an `evolves`-declared model version into its complete, hand-
written-equivalent form for review (evolution plan A2, instruction #2).

Purely an authoring-ergonomics tool: the compiler already normalizes an
`evolves`-declared version into a complete `ModelVersion` before anything
else runs (`compiler/workspace.py::_expand_model_evolutions`) -- this
module renders that already-computed complete version back into source
text and replaces the `evolves` block with it, verifying every implemented
codegen target's output is byte-identical before and after (A2's exit
criteria: "no canonical contract or generated artifact changes").
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path

from modelable.compiler.render import _render_model
from modelable.compiler.workspace import Workspace, WorkspaceDocumentSource, load_workspace, load_workspace_from_sources
from modelable.diagnostics.model import render_diagnostic
from modelable.refactor._model_block import block_contains_comment, find_model_block
from modelable.refactor._target_emitters import TARGET_EMITTERS


class ExpandVersionError(ValueError):
    pass


@dataclass(frozen=True)
class ExpandVersionResult:
    written_path: Path
    diff_text: str
    workspace: Workspace


def expand_version(root: Path, domain: str, model: str, version: int) -> ExpandVersionResult:
    workspace = load_workspace(root)
    error_diagnostics = [d for d in workspace.errors if d.severity == "error"]
    if error_diagnostics:
        rendered = "; ".join(render_diagnostic(d) for d in error_diagnostics)
        raise ExpandVersionError(f"workspace has validation errors: {rendered}")

    domain_def = next((d for d in workspace.mdl.domains if d.name == domain), None)
    if domain_def is None:
        raise ExpandVersionError(f"domain '{domain}' not found")
    expanded_version = next((v for v in domain_def.models.get(model, []) if v.version == version), None)
    if expanded_version is None:
        raise ExpandVersionError(f"{domain}.{model}@{version}: model version not found")

    sources_by_path = {source.path: source.text.splitlines() for source in workspace.sources if source.path is not None}
    span = find_model_block(sources_by_path, domain, model, version)
    if not span.is_evolves:
        raise ExpandVersionError(f"{domain}.{model}@{version}: already declared in full form, nothing to expand")
    if block_contains_comment(sources_by_path[span.path], span):
        raise ExpandVersionError(
            f"{domain}.{model}@{version}: the evolves block contains a comment that would be lost by "
            "expansion -- aborting rather than discard it; remove or relocate the comment first"
        )

    replacement_lines = [f"{span.leading_whitespace}{line}" for line in _render_model(model, expanded_version)]
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
        raise ExpandVersionError(f"expansion would produce an invalid workspace: {rendered}")

    _assert_identical_target_outputs(workspace, candidate_workspace)

    diff_text = _build_diff(span.path, workspace, candidate_text_by_path[span.path])
    return ExpandVersionResult(written_path=span.path, diff_text=diff_text, workspace=candidate_workspace)


def apply_expand_version(root: Path, domain: str, model: str, version: int) -> ExpandVersionResult:
    result = expand_version(root, domain, model, version)
    candidate_text = next(source.text for source in result.workspace.sources if source.path == result.written_path)
    original_bytes = result.written_path.read_bytes()
    try:
        result.written_path.write_text(candidate_text, encoding="utf-8", newline="\n")
        reloaded = load_workspace(root)
        reload_errors = [d for d in reloaded.errors if d.severity == "error"]
        if reload_errors:
            rendered = "; ".join(render_diagnostic(d) for d in reload_errors)
            raise ExpandVersionError(f"reloaded workspace has validation errors: {rendered}")
    except Exception:
        result.written_path.write_bytes(original_bytes)
        raise
    return result


def _assert_identical_target_outputs(original: Workspace, candidate: Workspace) -> None:
    mismatches: list[str] = []
    for target_name, emitter in TARGET_EMITTERS.items():
        out_dir = Path("expand-version-preview")
        try:
            original_artifacts = {a.ref: a for a in emitter(original, out_dir)}  # type: ignore[operator]
            candidate_artifacts = {a.ref: a for a in emitter(candidate, out_dir)}  # type: ignore[operator]
        except Exception as exc:
            raise ExpandVersionError(f"target '{target_name}' failed to generate: {exc}") from exc
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
        raise ExpandVersionError("expansion would change generated output, which A2 forbids: " + "; ".join(mismatches))


def _build_diff(path: Path, original_workspace: Workspace, candidate_text: str) -> str:
    original_text = next(source.text for source in original_workspace.sources if source.path == path)
    diff = difflib.unified_diff(
        original_text.splitlines(keepends=True),
        candidate_text.splitlines(keepends=True),
        fromfile=str(path),
        tofile=str(path),
    )
    return "".join(diff)
