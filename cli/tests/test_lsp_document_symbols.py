from modelable.lsp.document_symbols import build_document_symbols
from modelable.lsp.workspace import LspWorkspaceIndex

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


def test_document_symbols_builds_domain_outline():
    index = LspWorkspaceIndex()
    index.upsert_document("inmemory://workspace.mdl", WORKSPACE_TEXT)

    symbols = build_document_symbols(index, "inmemory://workspace.mdl")

    assert symbols is not None
    assert [symbol.name for symbol in symbols] == ["customer", "billing"]
    assert [symbol.name for symbol in symbols[0].children] == ["Customer"]
    assert [symbol.name for symbol in symbols[0].children[0].children] == [
        "customerId",
        "email",
    ]
    assert [symbol.name for symbol in symbols[1].children] == ["BillingCustomer"]


def test_document_symbols_includes_projection_fields():
    index = LspWorkspaceIndex()
    index.upsert_document("inmemory://workspace.mdl", WORKSPACE_TEXT)

    symbols = build_document_symbols(index, "inmemory://workspace.mdl")

    assert symbols is not None
    billing_domain = next(s for s in symbols if s.name == "billing")
    billing_customer = billing_domain.children[0]
    assert billing_customer.name == "BillingCustomer"
    field_names = [s.name for s in billing_customer.children]
    assert "billingId" in field_names
    assert "displayEmail" in field_names
