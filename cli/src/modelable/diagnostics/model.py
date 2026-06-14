from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

DiagnosticSeverity = Literal["error", "warning", "information"]


@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str
    severity: DiagnosticSeverity
    path: str
    line: int | None = None
    column: int | None = None
    end_line: int | None = None
    end_column: int | None = None


def render_diagnostic(diagnostic: Diagnostic) -> str:
    location = diagnostic.path
    if diagnostic.line is not None:
        location += f":{diagnostic.line}"
        if diagnostic.column is not None:
            location += f":{diagnostic.column}"
    return f"{diagnostic.code}: {location}: {diagnostic.message}"
