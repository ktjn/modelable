from modelable.lsp.document_symbols import build_document_symbols
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

