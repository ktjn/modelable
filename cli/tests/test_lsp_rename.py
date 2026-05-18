from modelable.lsp.rename import build_prepare_rename, build_rename
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


def test_prepare_rename_on_model_declaration_returns_identifier_range():
    rename_range = build_prepare_rename(_index(), "inmemory://workspace.mdl", line=1, character=11)

    assert rename_range is not None
    assert rename_range.start.line == 1
    assert rename_range.start.character == 9
    assert rename_range.end.line == 1
    assert rename_range.end.character == 17


def test_rename_model_declaration_updates_definition_and_references():
    edit = build_rename(_index(), "inmemory://workspace.mdl", line=1, character=11, new_name="Client")

    assert edit is not None
    changes = sorted(edit.changes["inmemory://workspace.mdl"], key=lambda item: (item.range.start.line, item.range.start.character))
    assert len(changes) == 2
    assert changes[0].range.start.line == 1
    assert changes[0].new_text == "Client"
    assert changes[1].range.start.line == 9
    assert changes[1].new_text == "Client"


def test_rename_model_field_on_reference_updates_definition_and_usage():
    edit = build_rename(_index(), "inmemory://workspace.mdl", line=11, character=21, new_name="customerKey")

    assert edit is not None
    changes = sorted(edit.changes["inmemory://workspace.mdl"], key=lambda item: (item.range.start.line, item.range.start.character))
    assert len(changes) == 2
    assert changes[0].range.start.line == 2
    assert changes[0].new_text == "customerKey"
    assert changes[1].range.start.line == 11
    assert changes[1].new_text == "customerKey"

