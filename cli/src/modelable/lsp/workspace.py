from __future__ import annotations

from collections.abc import Iterator, Mapping, MutableMapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlparse

from modelable.compiler.workspace import (
    Workspace,
    WorkspaceDocumentSource,
)
from modelable.language.workspace import LanguageDocument, LanguageWorkspace


class _LspDocumentMap(MutableMapping[str, WorkspaceDocumentSource]):
    def __init__(self, index: LspWorkspaceIndex) -> None:
        self._index = index
        self._sources: dict[str, WorkspaceDocumentSource] = {}

    def __getitem__(self, uri: str) -> WorkspaceDocumentSource:
        return self._sources[uri]

    def __iter__(self) -> Iterator[str]:
        return iter(self._sources)

    def __len__(self) -> int:
        return len(self._sources)

    def __setitem__(self, uri: str, source: WorkspaceDocumentSource) -> None:
        self._index._set_document_source(uri, source)

    def __delitem__(self, uri: str) -> None:
        if uri not in self:
            raise KeyError(uri)
        self._index.remove_document(uri)

    def __ior__(
        self,
        other: Mapping[str, WorkspaceDocumentSource],
    ) -> _LspDocumentMap:
        self.update(other)
        return self

    def _store(self, uri: str, source: WorkspaceDocumentSource) -> None:
        self._sources[uri] = source

    def _remove(self, uri: str) -> None:
        del self._sources[uri]


@dataclass
class LspWorkspaceIndex:
    language: LanguageWorkspace = field(default_factory=LanguageWorkspace)
    _revision: int = field(default=0, init=False, repr=False)
    _versions: dict[str, int] = field(default_factory=dict, init=False, repr=False)
    _user_opened: set[str] = field(default_factory=set, init=False, repr=False)
    _documents: _LspDocumentMap = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._documents = _LspDocumentMap(self)

    @property
    def documents(self) -> MutableMapping[str, WorkspaceDocumentSource]:
        return self._documents

    @documents.setter
    def documents(
        self,
        documents: MutableMapping[str, WorkspaceDocumentSource],
    ) -> None:
        if documents is self._documents:
            return
        self._documents.clear()
        self._documents.update(documents)

    @property
    def workspace(self) -> Workspace | None:
        return self.language.workspace

    def upsert_document(self, uri: str, text: str) -> Workspace | None:
        self._user_opened.add(uri)
        current = self.language.current_document(uri)
        if current is not None and current.text == text:
            return self.workspace
        return self._replace_document(uri, text)

    def load_background_document(self, uri: str, text: str) -> None:
        """Load a document from disk without marking it as user-opened."""
        if uri in self._user_opened:
            return
        current = self.language.current_document(uri)
        if current is not None and current.text == text:
            return
        self._replace_document(uri, text)

    def close_document(self, uri: str) -> Workspace | None:
        """Called when the user closes a tab — revert to on-disk content if available."""
        self._user_opened.discard(uri)
        path = uri_to_path(uri)
        if path is not None and path.exists():
            try:
                text = path.read_text(encoding="utf-8")
                current = self.language.current_document(uri)
                if current is not None and current.text == text:
                    return self.workspace
                return self._replace_document(uri, text)
            except Exception:
                pass
        return self.remove_document(uri)

    def remove_document(self, uri: str) -> Workspace | None:
        self._user_opened.discard(uri)
        if uri in self.language.documents:
            self._documents._remove(uri)
            documents = tuple(
                document for document_uri, document in self.language.documents.items() if document_uri != uri
            )
            return self._synchronize(documents)
        return self.workspace

    def rebuild(self) -> Workspace | None:
        return self._synchronize(tuple(self.language.documents.values()))

    def _replace_document(self, uri: str, text: str) -> Workspace | None:
        return self._set_document_source(
            uri,
            WorkspaceDocumentSource(
                path=uri_to_path(uri),
                uri=uri,
                text=text,
            ),
        )

    def _set_document_source(
        self,
        uri: str,
        source: WorkspaceDocumentSource,
    ) -> Workspace | None:
        normalized = WorkspaceDocumentSource(
            path=source.path,
            uri=uri,
            text=source.text,
        )
        current = self.language.current_document(uri)
        if current is not None and current.text == normalized.text:
            self._documents._store(uri, normalized)
            return self.workspace
        version = self._versions.get(uri, 0) + 1
        self._versions[uri] = version
        replacement = LanguageDocument.from_text(uri, normalized.text, version)
        self._documents._store(uri, normalized)
        documents = tuple(
            replacement if document_uri == uri else document
            for document_uri, document in self.language.documents.items()
        )
        if uri not in self.language.documents:
            documents += (replacement,)
        return self._synchronize(documents)

    def _synchronize(
        self,
        documents: tuple[LanguageDocument, ...],
    ) -> Workspace | None:
        self._revision += 1
        self.language.synchronize(self._revision, documents)
        return self.workspace


def uri_to_path(uri: str) -> Path | None:
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return None
    path = unquote(parsed.path)
    if parsed.netloc:
        path = f"//{parsed.netloc}{path}"
    elif len(path) >= 3 and path.startswith("/") and path[2] == ":":
        path = path[1:]
    return Path(path)


def find_workspace_root(file_path: Path) -> Path | None:
    directory = file_path.parent
    while True:
        if (directory / "workspace.mdl").exists():
            return directory
        parent = directory.parent
        if parent == directory:
            return None
        directory = parent
