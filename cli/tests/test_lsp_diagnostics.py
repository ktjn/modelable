from modelable.diagnostics.model import Diagnostic
from modelable.lsp.diagnostics import to_lsp_diagnostic


def test_lsp_diagnostic_conversion_maps_severity_and_range():
    diagnostic = Diagnostic(
        code="SEM",
        message="missing key",
        severity="error",
        path="customer.mdl",
        line=3,
        column=5,
        end_line=3,
        end_column=12,
    )

    lsp_diagnostic = to_lsp_diagnostic(diagnostic)

    assert lsp_diagnostic.message == "missing key"
    assert lsp_diagnostic.source == "modelable"
    assert lsp_diagnostic.code == "SEM"
    assert lsp_diagnostic.severity.name == "Error"
    assert lsp_diagnostic.range.start.line == 2
    assert lsp_diagnostic.range.start.character == 4
