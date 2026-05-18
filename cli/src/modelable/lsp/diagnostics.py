from __future__ import annotations

from modelable.diagnostics.model import Diagnostic
from lsprotocol import types


def to_lsp_diagnostic(diagnostic: Diagnostic) -> types.Diagnostic:
    severity_map = {
        "error": types.DiagnosticSeverity.Error,
        "warning": types.DiagnosticSeverity.Warning,
        "information": types.DiagnosticSeverity.Information,
    }
    line = max((diagnostic.line or 1) - 1, 0)
    column = max((diagnostic.column or 1) - 1, 0)
    end_line = max((diagnostic.end_line or diagnostic.line or 1) - 1, 0)
    end_column = max((diagnostic.end_column or diagnostic.column or 1) - 1, 0)
    return types.Diagnostic(
        message=diagnostic.message,
        severity=severity_map[diagnostic.severity],
        source="modelable",
        code=diagnostic.code,
        range=types.Range(
            start=types.Position(line=line, character=column),
            end=types.Position(line=end_line, character=end_column),
        ),
    )


def to_lsp_diagnostics(diagnostics: list[Diagnostic]) -> list[types.Diagnostic]:
    return [to_lsp_diagnostic(diagnostic) for diagnostic in diagnostics]

