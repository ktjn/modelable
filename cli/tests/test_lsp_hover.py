from modelable.lsp.hover import build_hover
from modelable.lsp.workspace import LspWorkspaceIndex


PROJECTION_SOURCE_TEXT = """
domain customer {
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    status: string
  }
}

domain catalog {
  projection ProductReply @ 1
    from customer.Customer @ 1 as c
  {
    productId <- c.customerId
    statusText <- c.status
  }
}

domain storefront {
  projection ProductDisplay @ 1
    from catalog.ProductReply @ 1 as p
  {
    displayId <- p.productId
  }
}
""".strip(
    "\n"
)


def test_hover_on_model_reference_shows_summary():
    index = LspWorkspaceIndex()
    index.upsert_document(
        "inmemory://workspace.mdl",
        """
domain customer {
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    email?: string
  }
}
""",
    )

    hover = build_hover(index, "inmemory://workspace.mdl", line=2, character=11)

    assert hover is not None
    assert "customer.Customer@1" in hover.contents.value
    assert "kind: entity" in hover.contents.value


def test_hover_on_field_reference_shows_source_field():
    index = LspWorkspaceIndex()
    index.upsert_document(
        "inmemory://workspace.mdl",
        """
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
""",
    )

    hover = build_hover(index, "inmemory://workspace.mdl", line=13, character=22)

    assert hover is not None
    assert "customer.Customer@1.email" in hover.contents.value
    assert "type: string" in hover.contents.value


def test_hover_on_projection_field_shows_mapping():
    index = LspWorkspaceIndex()
    index.upsert_document(
        "inmemory://workspace.mdl",
        """
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
""",
    )

    hover = build_hover(index, "inmemory://workspace.mdl", line=13, character=8)

    assert hover is not None
    assert "billing.BillingCustomer@1.displayEmail" in hover.contents.value
    assert "computed c.email" in hover.contents.value


def test_hover_on_projection_source_field_reference_shows_projection_field_summary():
    lines = PROJECTION_SOURCE_TEXT.splitlines()
    usage_line = lines.index("    displayId <- p.productId")
    usage_character = lines[usage_line].index("productId") + 1

    index = LspWorkspaceIndex()
    index.upsert_document("inmemory://workspace.mdl", PROJECTION_SOURCE_TEXT)

    hover = build_hover(index, "inmemory://workspace.mdl", line=usage_line, character=usage_character)

    assert hover is not None
    assert "catalog.ProductReply@1.productId" in hover.contents.value
    assert "mapping: direct c.customerId" in hover.contents.value


def test_hover_on_qualified_ref_in_from_clause_shows_model_summary():
    source = """
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
  }
}
""".strip("\n")
    lines = source.splitlines()
    from_line = next(i for i, l in enumerate(lines) if "from customer.Customer @ 1" in l)
    character = lines[from_line].index("Customer") + 1

    index = LspWorkspaceIndex()
    index.upsert_document("inmemory://workspace.mdl", source)

    hover = build_hover(index, "inmemory://workspace.mdl", line=from_line, character=character)

    assert hover is not None
    assert "customer.Customer@1" in hover.contents.value
    assert "kind: entity" in hover.contents.value


def test_hover_on_field_with_key_and_pii_flags_shows_annotations():
    source = """
domain customer {
  entity Customer @ 1 (additive) {
    @key @pii customerId: uuid
    email?: string
  }
}
""".strip("\n")
    lines = source.splitlines()
    field_line = next(i for i, l in enumerate(lines) if "@key @pii customerId" in l)
    character = lines[field_line].index("customerId") + 1

    index = LspWorkspaceIndex()
    index.upsert_document("inmemory://workspace.mdl", source)

    hover = build_hover(index, "inmemory://workspace.mdl", line=field_line, character=character)

    assert hover is not None
    assert "key" in hover.contents.value
    assert "pii" in hover.contents.value


def test_hover_returns_none_for_unknown_uri():
    index = LspWorkspaceIndex()

    hover = build_hover(index, "inmemory://unknown.mdl", line=0, character=0)

    assert hover is None
