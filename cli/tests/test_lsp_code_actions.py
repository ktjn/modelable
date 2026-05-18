from lsprotocol import types

from modelable.lsp.code_actions import build_code_actions
from modelable.lsp.workspace import LspWorkspaceIndex, WorkspaceDocumentSource


VALID_WORKSPACE_TEXT = """
domain customer {
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""".strip(
    "\n"
)


BROKEN_WORKSPACE_TEXT = """
domain customer {
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
""".strip(
    "\n"
)


def _index() -> LspWorkspaceIndex:
    index = LspWorkspaceIndex()
    uri = "inmemory://workspace.mdl"
    index.upsert_document(uri, VALID_WORKSPACE_TEXT)
    index.documents[uri] = WorkspaceDocumentSource(
        path=None,
        uri=uri,
        text=BROKEN_WORKSPACE_TEXT,
    )
    return index


def test_code_actions_offer_missing_closing_brace_fix_for_parse_errors():
    diagnostic = types.Diagnostic(
        message="Unexpected end-of-input. Expected one of: }",
        range=types.Range(
            start=types.Position(line=4, character=0),
            end=types.Position(line=4, character=0),
        ),
        severity=types.DiagnosticSeverity.Error,
        source="modelable",
        code="PARSE",
    )

    actions = build_code_actions(
        _index(),
        "inmemory://workspace.mdl",
        line=4,
        character=0,
        diagnostics=[diagnostic],
    )

    assert actions is not None
    assert len(actions) == 1
    assert actions[0].title == "Insert missing closing brace"
    assert actions[0].edit is not None
    edits = actions[0].edit.changes["inmemory://workspace.mdl"]
    assert len(edits) == 1
    assert edits[0].new_text == "\n}"
