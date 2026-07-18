from __future__ import annotations

from modelable.browser.dto import (
    BrowserArtifact,
    BrowserCompileResult,
    BrowserDiagnostic,
    BrowserFormatResult,
    BrowserSource,
    BrowserWorkspaceResult,
)
from modelable.compiler.render import render_mdl
from modelable.compiler.workspace import (
    Workspace,
    WorkspaceDocumentSource,
    load_workspace_from_sources,
)
from modelable.diagnostics.model import Diagnostic
from modelable.emitters.base import render_artifact_text
from modelable.emitters.json_schema import emit_json_schema_artifacts
from modelable.parser.ir import ParseError
from modelable.parser.parse import parse_text_to_ir
from modelable.validation.semantic import validate_diagnostics


class BrowserInputError(ValueError):
    """Raised when a browser compiler request has invalid source metadata."""


def _validate_sources(sources: tuple[BrowserSource, ...]) -> None:
    if not sources:
        raise BrowserInputError("At least one source is required")
    uris = [source.uri for source in sources]
    if len(uris) != len(set(uris)):
        raise BrowserInputError("Source URIs must be unique")
    invalid = [source.uri for source in sources if source.version <= 0]
    if invalid:
        raise BrowserInputError(f"Source versions must be positive: {', '.join(invalid)}")


def _browser_diagnostic(diagnostic: Diagnostic) -> BrowserDiagnostic:
    return BrowserDiagnostic(
        code=diagnostic.code,
        severity=diagnostic.severity,
        message=diagnostic.message,
        uri=diagnostic.path,
        line=diagnostic.line,
        column=diagnostic.column,
        end_line=diagnostic.end_line,
        end_column=diagnostic.end_column,
    )


def _document_sources(sources: tuple[BrowserSource, ...]) -> list[WorkspaceDocumentSource]:
    return [WorkspaceDocumentSource(path=None, uri=source.uri, text=source.text) for source in sources]


def _load_workspace(sources: tuple[BrowserSource, ...]) -> Workspace | BrowserWorkspaceResult:
    documents = _document_sources(sources)
    try:
        return load_workspace_from_sources(documents)
    except ParseError:
        for source, document in zip(sources, documents, strict=True):
            try:
                load_workspace_from_sources([document])
            except ParseError as error:
                return BrowserWorkspaceResult(
                    diagnostics=(_browser_diagnostic(error.diagnostic(source.uri)),),
                    source_hashes={},
                )
        raise


class BrowserCompiler:
    def open_workspace(
        self,
        sources: tuple[BrowserSource, ...],
    ) -> BrowserWorkspaceResult:
        _validate_sources(sources)
        workspace = _load_workspace(sources)
        if isinstance(workspace, BrowserWorkspaceResult):
            return workspace
        return BrowserWorkspaceResult(
            diagnostics=tuple(_browser_diagnostic(error) for error in workspace.errors),
            source_hashes={source.uri: source.content_hash for source in workspace.sources},
        )

    def format_source(self, source: BrowserSource) -> BrowserFormatResult:
        _validate_sources((source,))
        try:
            mdl = parse_text_to_ir(source.text, path=source.uri)
        except ParseError as error:
            return BrowserFormatResult(
                diagnostics=(_browser_diagnostic(error.diagnostic(source.uri)),),
                replacement_text=None,
            )

        diagnostics = tuple(
            _browser_diagnostic(diagnostic) for diagnostic in validate_diagnostics(mdl, path=source.uri)
        )
        replacement_text = (
            None if any(diagnostic.severity == "error" for diagnostic in diagnostics) else render_mdl(mdl)
        )
        return BrowserFormatResult(
            diagnostics=diagnostics,
            replacement_text=replacement_text,
        )

    def compile_json_schema(
        self,
        sources: tuple[BrowserSource, ...],
    ) -> BrowserCompileResult:
        opened = self.open_workspace(sources)
        if any(diagnostic.severity == "error" for diagnostic in opened.diagnostics):
            return BrowserCompileResult(
                diagnostics=opened.diagnostics,
                artifacts=(),
            )

        workspace = load_workspace_from_sources(_document_sources(sources))
        emitted = sorted(
            emit_json_schema_artifacts(workspace),
            key=lambda artifact: artifact.path.as_posix(),
        )
        return BrowserCompileResult(
            diagnostics=opened.diagnostics,
            artifacts=tuple(
                BrowserArtifact(
                    path=artifact.path.as_posix(),
                    media_type="application/schema+json",
                    content=render_artifact_text(artifact),
                    source_refs=(artifact.ref,),
                )
                for artifact in emitted
            ),
        )
