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


ENUM_WORKSPACE_TEXT = """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
  enum projection PublicStatus @ 1 (additive)
    from OrderStatus @ 1
    pick(active, done)
  entity Order @ 1 (additive) {
    @key orderId: uuid
    status: orders.OrderStatus @ 1
  }
}
""".strip("\n")


def test_document_symbols_includes_semantic_and_enum_projection_declarations():
    """Evolution plan E11: `semantic` and `enum projection` declarations
    previously had no outline entry at all -- worse, extending _DECL_PATTERN
    naively to include `semantic` (which has no `{}` body in the common
    case) would make _block_end_line swallow the rest of the document, since
    it assumes every declaration eventually closes a brace."""
    index = LspWorkspaceIndex()
    index.upsert_document("inmemory://orders.mdl", ENUM_WORKSPACE_TEXT)

    symbols = build_document_symbols(index, "inmemory://orders.mdl")

    assert symbols is not None
    orders_domain = symbols[0]
    assert [child.name for child in orders_domain.children] == [
        "OrderStatus",
        "PublicStatus",
        "Order",
    ]

    order_status, public_status, order = orders_domain.children
    assert order_status.detail == "semantic @1"
    assert public_status.detail == "enum projection @1"
    assert order.detail == "entity @1"


def test_document_symbols_semantic_declaration_range_does_not_swallow_rest_of_document():
    index = LspWorkspaceIndex()
    index.upsert_document("inmemory://orders.mdl", ENUM_WORKSPACE_TEXT)
    lines = ENUM_WORKSPACE_TEXT.splitlines()

    symbols = build_document_symbols(index, "inmemory://orders.mdl")

    assert symbols is not None
    order_status = symbols[0].children[0]
    semantic_line = lines.index("  semantic OrderStatus @ 1 (additive): enum(pending, active, done)")
    assert order_status.range.start.line == semantic_line
    assert order_status.range.end.line == semantic_line

    order = symbols[0].children[2]
    entity_line = lines.index("  entity Order @ 1 (additive) {")
    assert order.range.start.line == entity_line


def test_document_symbols_enum_projection_range_ends_at_its_pick_clause():
    index = LspWorkspaceIndex()
    index.upsert_document("inmemory://orders.mdl", ENUM_WORKSPACE_TEXT)
    lines = ENUM_WORKSPACE_TEXT.splitlines()

    symbols = build_document_symbols(index, "inmemory://orders.mdl")

    assert symbols is not None
    public_status = symbols[0].children[1]
    header_line = lines.index("  enum projection PublicStatus @ 1 (additive)")
    pick_line = lines.index("    pick(active, done)")
    assert public_status.range.start.line == header_line
    assert public_status.range.end.line == pick_line


def test_document_symbols_semantic_declaration_with_body_uses_brace_matching():
    text = """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done) {
    registry: true
  }
  entity Order @ 1 (additive) {
    @key orderId: uuid
  }
}
""".strip("\n")
    index = LspWorkspaceIndex()
    index.upsert_document("inmemory://orders.mdl", text)
    lines = text.splitlines()

    symbols = build_document_symbols(index, "inmemory://orders.mdl")

    assert symbols is not None
    order_status = symbols[0].children[0]
    header_line = lines.index("  semantic OrderStatus @ 1 (additive): enum(pending, active, done) {")
    body_close_line = lines.index("  }")
    assert order_status.range.start.line == header_line
    assert order_status.range.end.line == body_close_line

    order = symbols[0].children[1]
    entity_line = lines.index("  entity Order @ 1 (additive) {")
    assert order.range.start.line == entity_line
