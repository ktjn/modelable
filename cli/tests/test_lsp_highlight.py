from modelable.lsp.highlight import build_document_highlight
from modelable.lsp.workspace import LspWorkspaceIndex
from lsprotocol import types


WORKSPACE_TEXT = """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    email?: string
  }
}

domain billing {
  owner: "test-team"
  projection BillingCustomer @ 1
    from customer.Customer @ 1 as c
  {
    billingId <- c.customerId
    displayEmail = c.email
  }
}
""".strip("\n")


def _index() -> LspWorkspaceIndex:
    index = LspWorkspaceIndex()
    index.upsert_document("inmemory://workspace.mdl", WORKSPACE_TEXT)
    return index


def test_document_highlight_on_model_declaration_returns_declaration_and_reference():
    lines = WORKSPACE_TEXT.splitlines()
    decl_line = next(i for i, l in enumerate(lines) if "entity Customer" in l)

    highlights = build_document_highlight(_index(), "inmemory://workspace.mdl", line=decl_line, character=11)

    assert highlights is not None
    assert len(highlights) == 2
    highlight_lines = {h.range.start.line for h in highlights}
    ref_line = next(i for i, l in enumerate(lines) if "from customer.Customer @ 1 as c" in l)
    assert decl_line in highlight_lines
    assert ref_line in highlight_lines


def test_document_highlight_declaration_has_write_kind():
    lines = WORKSPACE_TEXT.splitlines()
    decl_line = next(i for i, l in enumerate(lines) if "entity Customer" in l)

    highlights = build_document_highlight(_index(), "inmemory://workspace.mdl", line=decl_line, character=11)

    assert highlights is not None
    decl_highlights = [h for h in highlights if h.range.start.line == decl_line]
    assert len(decl_highlights) == 1
    assert decl_highlights[0].kind == types.DocumentHighlightKind.Write


def test_document_highlight_usages_have_read_kind():
    lines = WORKSPACE_TEXT.splitlines()
    decl_line = next(i for i, l in enumerate(lines) if "entity Customer" in l)
    ref_line = next(i for i, l in enumerate(lines) if "from customer.Customer @ 1 as c" in l)

    highlights = build_document_highlight(_index(), "inmemory://workspace.mdl", line=decl_line, character=11)

    assert highlights is not None
    ref_highlights = [h for h in highlights if h.range.start.line == ref_line]
    assert len(ref_highlights) == 1
    assert ref_highlights[0].kind == types.DocumentHighlightKind.Read


def test_document_highlight_returns_none_for_unknown_position():
    highlights = build_document_highlight(_index(), "inmemory://workspace.mdl", line=0, character=0)

    assert highlights is None
