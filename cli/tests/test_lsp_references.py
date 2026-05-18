from modelable.lsp.references import build_references
from modelable.lsp.workspace import LspWorkspaceIndex


WORKSPACE_TEXT = """
domain customer {
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    email?: string
  }
}

domain billing {
  projection BillingCustomer @ 1
    from customer.Customer @ 1 as c
  {
    billingId <- c.customerId
    displayEmail = c.email
  }
}
""".strip(
    "\n"
)


def _index() -> LspWorkspaceIndex:
    index = LspWorkspaceIndex()
    index.upsert_document("inmemory://workspace.mdl", WORKSPACE_TEXT)
    return index


def test_references_for_model_declaration_includes_source_usage():
    references = build_references(
        _index(),
        "inmemory://workspace.mdl",
        line=1,
        character=11,
        include_declaration=False,
    )

    assert references is not None
    assert len(references) == 1
    assert references[0].range.start.line == 9
    assert references[0].range.start.character == 9


def test_references_for_model_field_includes_projection_usage():
    references = build_references(
        _index(),
        "inmemory://workspace.mdl",
        line=3,
        character=6,
        include_declaration=False,
    )

    assert references is not None
    assert len(references) == 1
    assert references[0].range.start.line == 12
    assert references[0].range.start.character == 19
