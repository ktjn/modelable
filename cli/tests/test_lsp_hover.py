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
