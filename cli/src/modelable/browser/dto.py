from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


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
    diagnostics: tuple[BrowserDiagnostic, ...]
    source_hashes: Mapping[str, str]


@dataclass(frozen=True)
class BrowserFormatResult:
    diagnostics: tuple[BrowserDiagnostic, ...]
    replacement_text: str | None


@dataclass(frozen=True)
class BrowserCompileResult:
    diagnostics: tuple[BrowserDiagnostic, ...]
    artifacts: tuple[BrowserArtifact, ...]
