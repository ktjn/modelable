from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Self

from modelable.compiler.workspace import (
    Workspace,
    WorkspaceDocumentSource,
    load_workspace_from_sources,
)
from modelable.diagnostics.model import Diagnostic
from modelable.language.dto import LanguageLocation
from modelable.parser.ir import ParseError


@dataclass(frozen=True)
class LanguageDocument:
    uri: str
    text: str
    version: int
    content_hash: str

    @classmethod
    def from_text(cls, uri: str, text: str, version: int) -> Self:
        return cls(
            uri=uri,
            text=text,
            version=version,
            content_hash=sha256(text.encode("utf-8")).hexdigest(),
        )


@dataclass(frozen=True)
class LanguageSynchronization:
    revision: int
    diagnostics: tuple[Diagnostic, ...]
    source_hashes: dict[str, str]


@dataclass
class LanguageWorkspace:
    revision: int = 0
    documents: dict[str, LanguageDocument] = field(default_factory=dict)
    semantic_revision: int | None = None
    semantic_hashes: dict[str, str] = field(default_factory=dict)
    workspace: Workspace | None = None

    def synchronize(
        self,
        revision: int,
        documents: tuple[LanguageDocument, ...],
    ) -> LanguageSynchronization:
        self._validate_snapshot(revision, documents)
        ordered_documents = sorted(documents, key=lambda document: document.uri)
        self.revision = revision
        self.documents = {document.uri: document for document in ordered_documents}

        if not ordered_documents:
            self.workspace = None
            self.semantic_revision = revision
            self.semantic_hashes = {}
            return LanguageSynchronization(
                revision=revision,
                diagnostics=(),
                source_hashes={},
            )

        try:
            workspace = load_workspace_from_sources(self._sources())
        except ParseError:
            return self._parse_failure()

        self.workspace = workspace
        self.semantic_revision = revision
        self.semantic_hashes = self.current_hashes()
        return LanguageSynchronization(
            revision=revision,
            diagnostics=tuple(workspace.errors),
            source_hashes=self.current_hashes(),
        )

    def current_document(self, uri: str) -> LanguageDocument | None:
        return self.documents.get(uri)

    def current_hashes(self) -> dict[str, str]:
        return {uri: document.content_hash for uri, document in self.documents.items()}

    def semantic_workspace(self) -> Workspace | None:
        return self.workspace

    def is_semantically_current(self) -> bool:
        return self.semantic_revision == self.revision

    def is_location_current(self, location: LanguageLocation) -> bool:
        document = self.current_document(location.uri)
        return document is not None and document.content_hash == self.semantic_hashes.get(location.uri)

    def _validate_snapshot(
        self,
        revision: int,
        documents: tuple[LanguageDocument, ...],
    ) -> None:
        if revision <= self.revision:
            raise ValueError("Workspace revision must increase")
        uris = [document.uri for document in documents]
        if len(uris) != len(set(uris)):
            raise ValueError("Document URIs must be unique")
        invalid_versions = [document.uri for document in documents if document.version <= 0]
        if invalid_versions:
            raise ValueError("Document versions must be positive: " + ", ".join(sorted(invalid_versions)))

    def _sources(self) -> list[WorkspaceDocumentSource]:
        return [
            WorkspaceDocumentSource(path=None, uri=document.uri, text=document.text)
            for document in self.documents.values()
        ]

    def _parse_failure(self) -> LanguageSynchronization:
        diagnostics: list[Diagnostic] = []
        for source in self._sources():
            try:
                load_workspace_from_sources([source])
            except ParseError as error:
                diagnostics.append(error.diagnostic(source.uri))
        if not diagnostics:
            raise RuntimeError("Workspace parsing failed without a document parse error")
        return LanguageSynchronization(
            revision=self.revision,
            diagnostics=tuple(diagnostics),
            source_hashes=self.current_hashes(),
        )
