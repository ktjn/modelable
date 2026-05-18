from modelable.lsp.completion import build_completion
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


def test_completion_suggests_keywords_at_top_level():
    completion = build_completion(_index(), "inmemory://workspace.mdl", line=0, character=0)

    labels = [item.label for item in completion.items]

    assert labels[:4] == ["domain", "entity", "aggregate", "event"]


def test_completion_suggests_annotations_after_at_symbol():
    completion = build_completion(_index(), "inmemory://workspace.mdl", line=2, character=5)

    labels = [item.label for item in completion.items]

    assert "@classification" in labels
    assert "@server" in labels


def test_completion_suggests_workspace_names_after_from_clause():
    completion = build_completion(_index(), "inmemory://workspace.mdl", line=9, character=9)

    labels = [item.label for item in completion.items]

    assert "customer.Customer" in labels
    assert "billing.BillingCustomer" in labels


def test_completion_suggests_active_projection_fields_inside_body():
    completion = build_completion(_index(), "inmemory://workspace.mdl", line=11, character=4)

    labels = [item.label for item in completion.items]

    assert labels == ["billingId", "displayEmail"]

