from lsprotocol import types

from modelable.lsp.code_actions import build_code_actions
from modelable.lsp.workspace import LspWorkspaceIndex, WorkspaceDocumentSource


VALID_WORKSPACE_TEXT = """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""".strip(
    "\n"
)


BROKEN_WORKSPACE_TEXT = """
domain customer {
  owner: "test-team"
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


def test_code_actions_offer_missing_key_fix_for_entity_models():
    broken_source = """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    customerId: uuid
    email?: string
  }
}
    """.strip(
        "\n"
    )
    uri = "inmemory://workspace.mdl"
    index = _index()
    index.documents[uri] = type(index.documents[uri])(
        path=None,
        uri=uri,
        text=broken_source,
    )

    diagnostic = types.Diagnostic(
        message="customer.Customer@1: entity must have exactly one @key field",
        range=types.Range(
            start=types.Position(line=2, character=2),
            end=types.Position(line=2, character=2),
        ),
        severity=types.DiagnosticSeverity.Error,
        source="modelable",
        code="SEM",
    )

    actions = build_code_actions(
        index,
        uri,
        line=2,
        character=2,
        diagnostics=[diagnostic],
    )

    assert actions is not None
    assert len(actions) == 1
    assert actions[0].title == "Insert @key annotation"
    assert actions[0].edit is not None
    edits = actions[0].edit.changes[uri]
    assert len(edits) == 1
    assert edits[0].range.start.line == 3
    assert edits[0].range.start.character == 4
    assert edits[0].new_text == "@key "


def test_code_actions_offer_missing_key_fix_for_aggregate_models():
    broken_source = """
domain customer {
  owner: "test-team"
  aggregate Customer @ 1 (additive) {
    customerId: uuid
    email?: string
  }
}
    """.strip(
        "\n"
    )
    uri = "inmemory://workspace.mdl"
    index = _index()
    index.documents[uri] = type(index.documents[uri])(
        path=None,
        uri=uri,
        text=broken_source,
    )

    diagnostic = types.Diagnostic(
        message="customer.Customer@1: aggregate must have exactly one @key field",
        range=types.Range(
            start=types.Position(line=2, character=2),
            end=types.Position(line=2, character=2),
        ),
        severity=types.DiagnosticSeverity.Error,
        source="modelable",
        code="SEM",
    )

    actions = build_code_actions(
        index,
        uri,
        line=2,
        character=2,
        diagnostics=[diagnostic],
    )

    assert actions is not None
    assert len(actions) == 1
    assert actions[0].title == "Insert @key annotation"
    assert actions[0].edit is not None
    edits = actions[0].edit.changes[uri]
    assert len(edits) == 1
    assert edits[0].range.start.line == 3
    assert edits[0].range.start.character == 4
    assert edits[0].new_text == "@key "


def test_code_actions_offer_missing_owner_fix_for_domains():
    broken_source = """
domain customer {
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
    """.strip(
        "\n"
    )
    uri = "inmemory://workspace.mdl"
    index = _index()
    index.documents[uri] = type(index.documents[uri])(
        path=None,
        uri=uri,
        text=broken_source,
    )

    diagnostic = types.Diagnostic(
        message="domain 'customer' must have an owner attribute",
        range=types.Range(
            start=types.Position(line=0, character=0),
            end=types.Position(line=0, character=0),
        ),
        severity=types.DiagnosticSeverity.Error,
        source="modelable",
        code="SEM",
    )

    actions = build_code_actions(
        index,
        uri,
        line=0,
        character=0,
        diagnostics=[diagnostic],
    )

    assert actions is not None
    assert len(actions) == 1
    assert actions[0].title == 'Insert owner: "required-team"'
    assert actions[0].edit is not None
    edits = actions[0].edit.changes[uri]
    assert len(edits) == 1
    assert edits[0].range.start.line == 1
    assert edits[0].range.start.character == 0
    assert edits[0].new_text == '  owner: "required-team"\n'


def test_code_actions_offer_missing_version_header_fix_for_entities():
    broken_source = """
domain customer {
  owner: "team-a"
  entity Customer {
    @key customerId: uuid
  }
}
    """.strip(
        "\n"
    )
    uri = "inmemory://workspace.mdl"
    index = _index()
    index.documents[uri] = type(index.documents[uri])(
        path=None,
        uri=uri,
        text=broken_source,
    )

    diagnostic = types.Diagnostic(
        message="missing_header.Customer: entity must have a version header (e.g. @ 1 (additive))",
        range=types.Range(
            start=types.Position(line=2, character=2),
            end=types.Position(line=2, character=2),
        ),
        severity=types.DiagnosticSeverity.Error,
        source="modelable",
        code="SEM",
    )

    actions = build_code_actions(
        index,
        uri,
        line=2,
        character=2,
        diagnostics=[diagnostic],
    )

    assert actions is not None
    assert len(actions) == 1
    assert actions[0].title == "Insert @ 1 (additive)"
    assert actions[0].edit is not None
    edits = actions[0].edit.changes[uri]
    assert len(edits) == 1
    assert edits[0].range.start.line == 2
    assert edits[0].range.start.character == 18
    assert edits[0].new_text == "@ 1 (additive) "
