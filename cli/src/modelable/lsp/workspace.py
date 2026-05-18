from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlparse

from modelable.compiler.workspace import Workspace, WorkspaceDocumentSource, load_workspace_from_sources


@dataclass
class LspWorkspaceIndex:
    documents: dict[str, WorkspaceDocumentSource] = field(default_factory=dict)
    workspace: Workspace | None = None

    def upsert_document(self, uri: str, text: str) -> Workspace | None:
        source = WorkspaceDocumentSource(
            path=_uri_to_path(uri),
            uri=uri,
            text=text,
        )
        current = self.documents.get(uri)
        if current is not None and current.text == text:
            return self.workspace
        self.documents[uri] = source
        return self.rebuild()

    def remove_document(self, uri: str) -> Workspace | None:
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


def _uri_to_path(uri: str) -> Path | None:
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return None
    path = unquote(parsed.path)
    if parsed.netloc:
        path = f"//{parsed.netloc}{path}"
    elif len(path) >= 3 and path.startswith("/") and path[2] == ":":
        path = path[1:]
    return Path(path)
