from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from types import MappingProxyType

from modelable.browser.compatibility import build_browser_compatibility
from modelable.browser.dto import (
    BrowserArtifact,
    BrowserCompatibilityResult,
    BrowserCompileResult,
    BrowserCompletionResult,
    BrowserDefinitionResult,
    BrowserDiagnostic,
    BrowserFacetDocument,
    BrowserFormatResult,
    BrowserGovernanceResult,
    BrowserGraphResult,
    BrowserHoverResult,
    BrowserLanguagePosition,
    BrowserLineageResult,
    BrowserPlanResult,
    BrowserPreparedRenameResult,
    BrowserReferencesResult,
    BrowserRenameResult,
    BrowserSource,
    BrowserWorkspaceResult,
)
from modelable.browser.errors import BrowserLanguageError, BrowserRequestValidationError
from modelable.browser.governance import build_browser_governance
from modelable.browser.graph import build_browser_graph
from modelable.browser.lineage import build_browser_lineage
from modelable.compiler.render import render_mdl
from modelable.compiler.workspace import (
    Workspace,
    WorkspaceDocumentSource,
    load_workspace_from_sources,
)
from modelable.diagnostics.model import Diagnostic
from modelable.emitters.base import render_artifact_text
from modelable.emitters.csharp import emit_csharp
from modelable.emitters.go import emit_go
from modelable.emitters.java import emit_java
from modelable.emitters.json_schema import emit_json_schema_artifacts
from modelable.emitters.markdown import emit_markdown
from modelable.emitters.protobuf import emit_protobuf
from modelable.emitters.python import emit_python
from modelable.emitters.rust import emit_rust
from modelable.emitters.sql import emit_sql
from modelable.emitters.targets import get_codegen_target
from modelable.emitters.typescript import emit_typescript
from modelable.extensions import ExtensionDescriptorError, validate_extension_admission
from modelable.facets import FacetSubject, FacetSubjectKind, facets_for_subject
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
from modelable.planner.plans import build_plan_documents
from modelable.planner.protocol import PLAN_V1_SCHEMA, facet_documents, serialize_plan
from modelable.validation.semantic import validate_diagnostics


class BrowserInputError(BrowserRequestValidationError):
    """Raised when a browser compiler request has invalid source metadata."""


_BROWSER_GRAPH_SUBJECT_KINDS: tuple[tuple[str, FacetSubjectKind], ...] = (
    ("model_version:", "declaration"),
    ("field:", "field"),
    ("projection_version:", "projection"),
    ("projection_field:", "projection_field"),
)


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


def _browser_facet_document(
    facet_document: BrowserFacetDocument | None,
) -> tuple[dict[str, object] | None, str | None]:
    if facet_document is None:
        return None, None
    if not isinstance(facet_document.document, Mapping):
        raise BrowserInputError("Facet document must be an object")
    try:
        serialized = json.dumps(facet_document.document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as error:
        raise BrowserInputError("Facet document must be JSON") from error
    value = json.loads(serialized)
    if not isinstance(value, dict):
        raise BrowserInputError("Facet document must be an object")
    return value, serialized


def _load_workspace(
    sources: tuple[BrowserSource, ...],
    *,
    facets_document: dict[str, object] | None = None,
) -> Workspace | tuple[BrowserDiagnostic, ...]:
    documents = _document_sources(sources)
    try:
        return load_workspace_from_sources(documents, facets_document=facets_document)
    except ParseError:
        for source, document in zip(sources, documents, strict=True):
            try:
                load_workspace_from_sources([document])
            except ParseError as error:
                return (_browser_diagnostic(error.diagnostic(source.uri)),)
        raise


def _with_browser_graph_facets(result: BrowserGraphResult, workspace: Workspace) -> BrowserGraphResult:
    nodes = []
    for node in result.graph.nodes:
        subject = _browser_graph_subject(node.id)
        if subject is None:
            nodes.append(node)
            continue
        facets = facet_documents(facets_for_subject(workspace, subject))
        nodes.append(replace(node, metadata={**node.metadata, "facets": facets}))
    return replace(result, graph=replace(result.graph, nodes=tuple(nodes)))


def _browser_graph_subject(node_id: str) -> FacetSubject | None:
    for prefix, kind in _BROWSER_GRAPH_SUBJECT_KINDS:
        if node_id.startswith(prefix):
            return FacetSubject(kind, node_id.removeprefix(prefix))
    return None


class BrowserCompiler:
    def __init__(self) -> None:
        self.language = LanguageWorkspace()
        self._sources: tuple[BrowserSource, ...] = ()
        self._facet_document_fingerprint: str | None = None
        self._last_workspace_result: BrowserWorkspaceResult | None = None

    @property
    def sources(self) -> tuple[BrowserSource, ...]:
        return self._sources

    def open_workspace(
        self,
        workspace_revision: int,
        sources: tuple[BrowserSource, ...],
        *,
        facet_document: BrowserFacetDocument | None = None,
    ) -> BrowserWorkspaceResult:
        _validate_sources(sources)
        facet_document_value, facet_document_fingerprint = _browser_facet_document(facet_document)
        if workspace_revision < self.language.revision:
            raise BrowserLanguageError("STALE_WORKSPACE")
        if workspace_revision == self.language.revision:
            return self._reopen_current_workspace(sources, facet_document_fingerprint)
        synchronization = self.language.synchronize(
            workspace_revision,
            tuple(LanguageDocument.from_text(source.uri, source.text, source.version) for source in sources),
        )
        self._sources = sources
        self._facet_document_fingerprint = facet_document_fingerprint
        diagnostics = synchronization.diagnostics
        if facet_document_value is not None and self.language.semantic_workspace() is not None:
            workspace = _load_workspace(sources, facets_document=facet_document_value)
            if isinstance(workspace, Workspace):
                self.language.workspace = workspace
                diagnostics = (*workspace.errors, *workspace.warnings)
        result = BrowserWorkspaceResult(
            workspace_revision=synchronization.revision,
            diagnostics=tuple(_browser_diagnostic(diagnostic) for diagnostic in diagnostics),
            source_hashes=MappingProxyType(dict(synchronization.source_hashes)),
        )
        self._last_workspace_result = result
        return result

    def _reopen_current_workspace(
        self,
        sources: tuple[BrowserSource, ...],
        facet_document_fingerprint: str | None,
    ) -> BrowserWorkspaceResult:
        incoming_hashes = {
            source.uri: LanguageDocument.from_text(source.uri, source.text, source.version).content_hash
            for source in sources
        }
        if (
            incoming_hashes != dict(self.language.current_hashes())
            or facet_document_fingerprint != self._facet_document_fingerprint
        ):
            raise BrowserLanguageError("STALE_WORKSPACE")
        result = self._last_workspace_result
        if result is None:
            raise BrowserLanguageError("STALE_WORKSPACE")
        return result

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

    def graph(
        self,
        workspace_revision: int,
        mode: str,
    ) -> BrowserGraphResult:
        if workspace_revision != self.language.revision:
            raise BrowserLanguageError("STALE_WORKSPACE")
        semantic = self.language.semantic_workspace()
        if semantic is None:
            raise BrowserLanguageError("LANGUAGE_UNAVAILABLE")
        return _with_browser_graph_facets(build_browser_graph(semantic, mode, workspace_revision), semantic)

    def lineage(
        self,
        workspace_revision: int,
    ) -> BrowserLineageResult:
        if workspace_revision != self.language.revision:
            raise BrowserLanguageError("STALE_WORKSPACE")
        semantic = self.language.semantic_workspace()
        if semantic is None:
            raise BrowserLanguageError("LANGUAGE_UNAVAILABLE")
        return build_browser_lineage(semantic, workspace_revision)

    def query(self, workspace_revision: int, request: object) -> dict[str, object]:
        if workspace_revision != self.language.revision:
            raise BrowserLanguageError("STALE_WORKSPACE")
        semantic = self.language.semantic_workspace()
        if semantic is None:
            raise BrowserLanguageError("LANGUAGE_UNAVAILABLE")
        from modelable.query_service import WorkspaceQueryProtocolService

        try:
            return WorkspaceQueryProtocolService(semantic).execute(request)
        except ValueError as error:
            raise BrowserRequestValidationError(str(error)) from error

    def plans(self, workspace_revision: int) -> BrowserPlanResult:
        if workspace_revision != self.language.revision:
            raise BrowserLanguageError("STALE_WORKSPACE")
        semantic = self.language.semantic_workspace()
        if semantic is None:
            raise BrowserLanguageError("LANGUAGE_UNAVAILABLE")
        return BrowserPlanResult(
            workspace_revision=workspace_revision,
            plans=tuple(serialize_plan(plan) for plan in build_plan_documents(semantic, schema=PLAN_V1_SCHEMA)),
        )

    def compatibility(
        self,
        workspace_revision: int,
    ) -> BrowserCompatibilityResult:
        if workspace_revision != self.language.revision:
            raise BrowserLanguageError("STALE_WORKSPACE")
        semantic = self.language.semantic_workspace()
        if semantic is None:
            raise BrowserLanguageError("LANGUAGE_UNAVAILABLE")
        return build_browser_compatibility(semantic, workspace_revision)

    def governance(
        self,
        workspace_revision: int,
    ) -> BrowserGovernanceResult:
        if workspace_revision != self.language.revision:
            raise BrowserLanguageError("STALE_WORKSPACE")
        semantic = self.language.semantic_workspace()
        if semantic is None:
            raise BrowserLanguageError("LANGUAGE_UNAVAILABLE")
        return build_browser_governance(semantic, workspace_revision)

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
        return self.compile(sources, "jsonSchema")

    def compile(
        self,
        sources: tuple[BrowserSource, ...],
        target: str,
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

        from pathlib import Path

        out = Path(".")
        media_type = "text/plain"
        target_name = "json-schema" if target == "jsonSchema" else target
        try:
            target_descriptor = get_codegen_target(target_name).extension_descriptor()
        except KeyError as error:
            raise BrowserRequestValidationError(f"Unknown compile target: {target}") from error
        try:
            validate_extension_admission(target_descriptor, workspace.mdl, plan_version=PLAN_V1_SCHEMA)
        except ExtensionDescriptorError as error:
            return BrowserCompileResult(
                diagnostics=(
                    BrowserDiagnostic(
                        code="EXT",
                        severity="error",
                        message=str(error),
                        uri=sources[0].uri,
                        line=None,
                        column=None,
                        end_line=None,
                        end_column=None,
                    ),
                ),
                artifacts=(),
            )

        if target == "jsonSchema":
            emitted = emit_json_schema_artifacts(workspace)
            media_type = "application/schema+json"
        elif target == "typescript":
            emitted = emit_typescript(workspace, out)
            media_type = "application/typescript"
        elif target == "sql-postgres":
            emitted = emit_sql(workspace, out, "postgres")
            media_type = "application/sql"
        elif target == "sql-clickhouse":
            emitted = emit_sql(workspace, out, "clickhouse")
            media_type = "application/sql"
        elif target == "protobuf":
            emitted = emit_protobuf(workspace, out)
            media_type = "text/x-protobuf"
        elif target == "rust":
            emitted = emit_rust(workspace, out)
            media_type = "text/x-rust"
        elif target == "java":
            emitted = emit_java(workspace, out)
            media_type = "text/x-java-source"
        elif target == "go":
            emitted = emit_go(workspace, out)
            media_type = "text/x-go"
        elif target == "csharp":
            emitted = emit_csharp(workspace, out)
            media_type = "text/x-csharp"
        elif target == "markdown":
            emitted = emit_markdown(workspace, out)
            media_type = "text/markdown"
        elif target == "python":
            emitted = emit_python(workspace, out)
            media_type = "text/x-python"
        else:
            raise BrowserRequestValidationError(f"Unknown compile target: {target}")

        emitted = sorted(
            emitted,
            key=lambda artifact: artifact.path.as_posix(),
        )

        return BrowserCompileResult(
            diagnostics=diagnostics,
            artifacts=tuple(
                BrowserArtifact(
                    path=artifact.path.as_posix(),
                    media_type=media_type,
                    content=render_artifact_text(artifact),
                    source_refs=(artifact.ref,),
                    warnings=tuple(artifact.warnings),
                )
                for artifact in emitted
            ),
        )
