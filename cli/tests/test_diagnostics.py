from modelable.compiler.workspace import WorkspaceDocumentSource, load_workspace_from_sources
from modelable.diagnostics.model import Diagnostic, render_diagnostic
from modelable.parser.parse import parse_text
from modelable.validation.semantic import validate_diagnostics
from modelable.parser.ir import ParseError


def test_parse_error_exposes_location():
    try:
        parse_text("domain customer {")
    except ParseError as exc:
        diagnostic = exc.diagnostic(path="customer.mdl")
    else:  # pragma: no cover - defensive
        raise AssertionError("expected ParseError")

    assert diagnostic.code == "PARSE"
    assert diagnostic.path == "customer.mdl"
    assert diagnostic.line is not None
    assert diagnostic.column is not None
    assert "Syntax error" not in diagnostic.message
    assert render_diagnostic(diagnostic).startswith("PARSE: customer.mdl:")


def test_validate_diagnostics_returns_structured_errors():
    workspace = load_workspace_from_sources(
        [
            WorkspaceDocumentSource(
                path=None,
                uri="inmemory://customer.mdl",
                text="""
domain customer {
  entity Customer @ 1 (additive) {
    customerId: uuid
  }
}
""",
            )
        ]
    )

    assert workspace.errors
    assert all(isinstance(diagnostic, Diagnostic) for diagnostic in workspace.errors)
    assert any(diagnostic.code in {"SEM", "COMPAT"} for diagnostic in workspace.errors)


def test_validate_diagnostics_uses_string_wrapper_for_legacy_callers():
    workspace = load_workspace_from_sources(
        [
            WorkspaceDocumentSource(
                path=None,
                uri="inmemory://customer.mdl",
                text="""
domain customer {
  entity Customer @ 1 (additive) {
    customerId: uuid
  }
}
""",
            )
        ]
    )

    messages = validate_diagnostics(workspace.mdl, path="inmemory://customer.mdl")
    assert messages
    assert messages[0].path == "inmemory://customer.mdl"

