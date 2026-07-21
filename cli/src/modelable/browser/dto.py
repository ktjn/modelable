from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from modelable.language.dto import (
    LanguageCompletion,
    LanguageHover,
    LanguageLocation,
    LanguagePreparedRename,
    LanguageWorkspaceEdit,
)


@dataclass(frozen=True)
class BrowserSource:
    uri: str
    text: str
    version: int


@dataclass(frozen=True)
class BrowserDiagnostic:
    code: str
    severity: str
    message: str
    uri: str
    line: int | None
    column: int | None
    end_line: int | None
    end_column: int | None


@dataclass(frozen=True)
class BrowserArtifact:
    path: str
    media_type: str
    content: str
    source_refs: tuple[str, ...]


@dataclass(frozen=True)
class BrowserWorkspaceResult:
    workspace_revision: int
    diagnostics: tuple[BrowserDiagnostic, ...]
    source_hashes: Mapping[str, str]


@dataclass(frozen=True)
class BrowserLanguagePosition:
    workspace_revision: int
    uri: str
    line: int
    character: int


@dataclass(frozen=True)
class BrowserCompletionResult:
    items: tuple[LanguageCompletion, ...]


@dataclass(frozen=True)
class BrowserHoverResult:
    hover: LanguageHover | None


@dataclass(frozen=True)
class BrowserFormatResult:
    diagnostics: tuple[BrowserDiagnostic, ...]
    replacement_text: str | None


@dataclass(frozen=True)
class BrowserDefinitionResult:
    location: LanguageLocation | None


@dataclass(frozen=True)
class BrowserReferencesResult:
    locations: tuple[LanguageLocation, ...]


@dataclass(frozen=True)
class BrowserPreparedRenameResult:
    prepared: LanguagePreparedRename | None


@dataclass(frozen=True)
class BrowserRenameResult:
    edit: LanguageWorkspaceEdit


@dataclass(frozen=True)
class BrowserCompileResult:
    diagnostics: tuple[BrowserDiagnostic, ...]
    artifacts: tuple[BrowserArtifact, ...]


@dataclass(frozen=True)
class BrowserSourceRange:
    uri: str
    start_line: int
    start_character: int
    end_line: int
    end_character: int


@dataclass(frozen=True)
class BrowserGraphNode:
    id: str
    kind: str
    label: str
    metadata: dict[str, Any] = field(default_factory=dict)
    source_range: BrowserSourceRange | None = None


@dataclass(frozen=True)
class BrowserGraphEdge:
    id: str
    source: str
    target: str
    kind: str
    label: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BrowserGraph:
    schema_version: int
    nodes: tuple[BrowserGraphNode, ...]
    edges: tuple[BrowserGraphEdge, ...]


@dataclass(frozen=True)
class BrowserGraphResult:
    workspace_revision: int
    mode: str
    graph: BrowserGraph
