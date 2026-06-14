from modelable.lsp.folding import build_folding_ranges
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


def _index() -> LspWorkspaceIndex:
    index = LspWorkspaceIndex()
    index.upsert_document("inmemory://workspace.mdl", WORKSPACE_TEXT)
    return index


def test_folding_ranges_covers_domain_blocks():
    lines = WORKSPACE_TEXT.splitlines()
    customer_start = next(i for i, line in enumerate(lines) if line.startswith("domain customer"))
    customer_end = next(i for i, line in enumerate(lines) if line == "}" and i > customer_start)

    ranges = build_folding_ranges(_index(), "inmemory://workspace.mdl")

    assert ranges is not None
    domain_range = next((r for r in ranges if r.start_line == customer_start), None)
    assert domain_range is not None
    assert domain_range.end_line == customer_end


def test_folding_ranges_covers_model_blocks():
    lines = WORKSPACE_TEXT.splitlines()
    entity_start = next(i for i, line in enumerate(lines) if "entity Customer" in line)
    entity_end = next(i for i, line in enumerate(lines) if line.strip() == "}" and i > entity_start)

    ranges = build_folding_ranges(_index(), "inmemory://workspace.mdl")

    assert ranges is not None
    entity_range = next((r for r in ranges if r.start_line == entity_start), None)
    assert entity_range is not None
    assert entity_range.end_line == entity_end


def test_folding_ranges_returns_none_for_unknown_uri():
    ranges = build_folding_ranges(_index(), "inmemory://unknown.mdl")

    assert ranges is None
