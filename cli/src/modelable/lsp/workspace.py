from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlparse

from modelable.compiler.workspace import Workspace, WorkspaceDocumentSource, load_workspace_from_sources


@dataclass
class LspWorkspaceIndex:
    documents: dict[str, WorkspaceDocumentSource] = field(default_factory=dict)
    workspace: Workspace | None = None
    _user_opened: set[str] = field(default_factory=set, init=False, repr=False)

    def upsert_document(self, uri: str, text: str) -> Workspace | None:
        self._user_opened.add(uri)
        source = WorkspaceDocumentSource(
            path=uri_to_path(uri),
            uri=uri,
            text=text,
        )
        current = self.documents.get(uri)
        if current is not None and current.text == text:
            return self.workspace
        self.documents[uri] = source
        return self.rebuild()

    def load_background_document(self, uri: str, text: str) -> None:
        """Load a document from disk without marking it as user-opened."""
        if uri in self._user_opened:
            return
        source = WorkspaceDocumentSource(path=uri_to_path(uri), uri=uri, text=text)
        current = self.documents.get(uri)
        if current is not None and current.text == text:
            return
        self.documents[uri] = source
        self.rebuild()

    def close_document(self, uri: str) -> Workspace | None:
        """Called when the user closes a tab — revert to on-disk content if available."""
        self._user_opened.discard(uri)
        path = uri_to_path(uri)
        if path is not None and path.exists():
            try:
                text = path.read_text(encoding="utf-8")
                source = WorkspaceDocumentSource(path=path, uri=uri, text=text)
                self.documents[uri] = source
                return self.rebuild()
            except Exception:
                pass
        return self.remove_document(uri)

    def remove_document(self, uri: str) -> Workspace | None:
        self._user_opened.discard(uri)
        if uri in self.documents:
            del self.documents[uri]
            return self.rebuild()
        return self.workspace

    def rebuild(self) -> Workspace | None:
        if not self.documents:
            self.workspace = None
            return None
        ordered_sources = [self.documents[uri] for uri in sorted(self.documents)]
        self.workspace = load_workspace_from_sources(ordered_sources)
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
