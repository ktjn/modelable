from modelable.lsp.workspace_symbols import build_workspace_symbols
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


def test_workspace_symbols_filters_by_query():
    index = LspWorkspaceIndex()
    index.upsert_document("inmemory://workspace.mdl", WORKSPACE_TEXT)

    symbols = build_workspace_symbols(index, "billing")

    assert symbols is not None
    assert [symbol.name for symbol in symbols] == ["billing", "BillingCustomer"]
    assert symbols[0].container_name is None
    assert symbols[1].container_name == "billing"


def test_workspace_symbols_returns_fields_when_query_matches():
    index = LspWorkspaceIndex()
    index.upsert_document("inmemory://workspace.mdl", WORKSPACE_TEXT)

    symbols = build_workspace_symbols(index, "customerId")

    assert symbols is not None
    assert [symbol.name for symbol in symbols] == ["customerId"]
    assert symbols[0].container_name == "Customer"

