from modelable.lsp.workspace import LspWorkspaceIndex
from modelable.lsp.workspace_symbols import build_workspace_symbols

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


def test_workspace_symbols_filters_by_query():
    index = LspWorkspaceIndex()
    index.upsert_document("inmemory://workspace.mdl", WORKSPACE_TEXT)

    symbols = build_workspace_symbols(index, "billing")

    assert symbols is not None
    names = [symbol.name for symbol in symbols]
    assert "billing" in names
    assert "BillingCustomer" in names
    assert "billingId" in names
    domain_sym = next(s for s in symbols if s.name == "billing")
    projection_sym = next(s for s in symbols if s.name == "BillingCustomer")
    assert domain_sym.container_name is None
    assert projection_sym.container_name == "billing"


def test_workspace_symbols_returns_fields_when_query_matches():
    index = LspWorkspaceIndex()
    index.upsert_document("inmemory://workspace.mdl", WORKSPACE_TEXT)

    symbols = build_workspace_symbols(index, "customerId")

    assert symbols is not None
    assert [symbol.name for symbol in symbols] == ["customerId"]
    assert symbols[0].container_name == "Customer"
