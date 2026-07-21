from __future__ import annotations

from types import MappingProxyType

from modelable.browser.dto import (
    BrowserArtifact,
    BrowserCompileResult,
    BrowserCompletionResult,
    BrowserDefinitionResult,
    BrowserDiagnostic,
    BrowserFormatResult,
    BrowserHoverResult,
    BrowserLanguagePosition,
    BrowserPreparedRenameResult,
    BrowserReferencesResult,
    BrowserRenameResult,
    BrowserSource,
    BrowserWorkspaceResult,
)
from modelable.browser.errors import BrowserLanguageError, BrowserRequestValidationError
from modelable.compiler.render import render_mdl
from modelable.compiler.workspace import (
    Workspace,
    WorkspaceDocumentSource,
    load_workspace_from_sources,
)
from modelable.diagnostics.model import Diagnostic
from modelable.emitters.base import render_artifact_text
from modelable.emitters.json_schema import emit_json_schema_artifacts
from modelable.language.completion import complete
from modelable.language.definition import definition
from modelable.language.dto import LanguagePosition
from modelable.language.hover import hover
from modelable.language.positions import document_lines, utf16_to_codepoint
from modelable.language.references import references
from modelable.language.rename import InvalidRenameError
from modelable.language.rename import prepare_rename as language_prepare_rename
from modelable.language.rename import rename as language_rename
from modelable.language.workspace import LanguageDocument, LanguageWorkspace
from modelable.parser.ir import ParseError
from modelable.parser.parse import parse_text_to_ir
from modelable.validation.semantic import validate_diagnostics


class BrowserInputError(BrowserRequestValidationError):
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


def _load_workspace(sources: tuple[BrowserSource, ...]) -> Workspace | tuple[BrowserDiagnostic, ...]:
    documents = _document_sources(sources)
    try:
        return load_workspace_from_sources(documents)
    except ParseError:
        for source, document in zip(sources, documents, strict=True):
            try:
                load_workspace_from_sources([document])
            except ParseError as error:
                return (_browser_diagnostic(error.diagnostic(source.uri)),)
        raise


class BrowserCompiler:
    def __init__(self) -> None:
        self.language = LanguageWorkspace()

    def open_workspace(
        self,
        workspace_revision: int,
        sources: tuple[BrowserSource, ...],
    ) -> BrowserWorkspaceResult:
        _validate_sources(sources)
        if workspace_revision <= self.language.revision:
            raise BrowserLanguageError("STALE_WORKSPACE")
        synchronization = self.language.synchronize(
            workspace_revision,
            tuple(LanguageDocument.from_text(source.uri, source.text, source.version) for source in sources),
        )
        return BrowserWorkspaceResult(
            workspace_revision=synchronization.revision,
            diagnostics=tuple(_browser_diagnostic(diagnostic) for diagnostic in synchronization.diagnostics),
            source_hashes=MappingProxyType(dict(synchronization.source_hashes)),
        )

    def completion(
        self,
        request: BrowserLanguagePosition,
    ) -> BrowserCompletionResult:
        self._validate_language_request(request)
        if self.language.semantic_workspace() is None:
            raise BrowserLanguageError("LANGUAGE_UNAVAILABLE")
        return BrowserCompletionResult(
            items=complete(
                self.language,
                request.uri,
                LanguagePosition(request.line, request.character),
            )
        )

    def hover(
        self,
        request: BrowserLanguagePosition,
    ) -> BrowserHoverResult:
        self._validate_language_request(request)
        if self.language.semantic_workspace() is None:
            raise BrowserLanguageError("LANGUAGE_UNAVAILABLE")
        return BrowserHoverResult(
            hover=hover(
                self.language,
                request.uri,
                LanguagePosition(request.line, request.character),
            )
        )

    def definition(
        self,
        request: BrowserLanguagePosition,
    ) -> BrowserDefinitionResult:
        self._validate_language_request(request)
        if self.language.semantic_workspace() is None:
            raise BrowserLanguageError("LANGUAGE_UNAVAILABLE")
        return BrowserDefinitionResult(
            location=definition(
                self.language,
                request.uri,
                LanguagePosition(request.line, request.character),
            )
        )

    def references(
        self,
        request: BrowserLanguagePosition,
        include_declaration: bool,
    ) -> BrowserReferencesResult:
        self._validate_language_request(request)
        if self.language.semantic_workspace() is None:
            raise BrowserLanguageError("LANGUAGE_UNAVAILABLE")
        return BrowserReferencesResult(
            locations=references(
                self.language,
                request.uri,
                LanguagePosition(request.line, request.character),
                include_declaration=include_declaration,
            )
        )

    def prepare_rename(
        self,
        request: BrowserLanguagePosition,
    ) -> BrowserPreparedRenameResult:
        self._validate_language_request(request)
        if self.language.semantic_workspace() is None:
            raise BrowserLanguageError("LANGUAGE_UNAVAILABLE")
        return BrowserPreparedRenameResult(
            prepared=language_prepare_rename(
                self.language,
                request.uri,
                LanguagePosition(request.line, request.character),
            )
        )

    def rename(
        self,
        request: BrowserLanguagePosition,
        new_name: str,
    ) -> BrowserRenameResult:
        self._validate_language_request(request)
        if self.language.semantic_workspace() is None:
            raise BrowserLanguageError("LANGUAGE_UNAVAILABLE")
        try:
            result = language_rename(
                self.language,
                request.uri,
                LanguagePosition(request.line, request.character),
                new_name,
            )
        except InvalidRenameError as error:
            raise BrowserLanguageError("INVALID_RENAME") from error
        return BrowserRenameResult(edit=result)

    def _validate_language_request(
        self,
        request: BrowserLanguagePosition,
    ) -> None:
        if request.workspace_revision != self.language.revision:
            raise BrowserLanguageError("STALE_WORKSPACE")
        document = self.language.current_document(request.uri)
        if document is None or request.line < 0 or request.character < 0:
            raise BrowserLanguageError("INVALID_POSITION")
        lines = document_lines(document.text)
        if request.line >= len(lines):
            raise BrowserLanguageError("INVALID_POSITION")
        try:
            utf16_to_codepoint(lines[request.line], request.character)
        except ValueError as error:
            raise BrowserLanguageError("INVALID_POSITION") from error

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
        _validate_sources(sources)
        workspace = _load_workspace(sources)
        if isinstance(workspace, tuple):
            return BrowserCompileResult(
                diagnostics=workspace,
                artifacts=(),
            )
        diagnostics = tuple(_browser_diagnostic(error) for error in workspace.errors)
        if any(diagnostic.severity == "error" for diagnostic in diagnostics):
            return BrowserCompileResult(
                diagnostics=diagnostics,
                artifacts=(),
            )
        emitted = sorted(
            emit_json_schema_artifacts(workspace),
            key=lambda artifact: artifact.path.as_posix(),
        )
        return BrowserCompileResult(
            diagnostics=diagnostics,
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
