from modelable.lsp.definition import build_definition
from modelable.lsp.workspace import LspWorkspaceIndex


PROJECTION_SOURCE_TEXT = """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    status: string
  }
}

domain catalog {
  owner: "test-team"
  projection ProductReply @ 1
    from customer.Customer @ 1 as c
  {
    productId <- c.customerId
    statusText <- c.status
  }
}

domain storefront {
  owner: "test-team"
  projection ProductDisplay @ 1
    from catalog.ProductReply @ 1 as p
  {
    displayId <- p.productId
  }
}
""".strip(
    "\n"
)


def test_definition_on_projection_source_reference_goes_to_model_declaration():
    source = """
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
    lines = source.splitlines()
    index = LspWorkspaceIndex()
    index.upsert_document("inmemory://workspace.mdl", source)

    definition = build_definition(
        index,
        "inmemory://workspace.mdl",
        line=next(i for i, line in enumerate(lines) if "from customer.Customer @ 1 as c" in line),
        character=lines[next(i for i, line in enumerate(lines) if "from customer.Customer @ 1 as c" in line)].index("Customer") + 1,
    )

    assert definition is not None
    assert definition.uri == "inmemory://workspace.mdl"
    assert definition.range.start.line == next(i for i, line in enumerate(lines) if "entity Customer @ 1 (additive)" in line)
    assert definition.range.start.character == 9


def test_definition_on_projection_field_goes_to_its_declaration():
    source = """
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
    lines = source.splitlines()
    index = LspWorkspaceIndex()
    index.upsert_document("inmemory://workspace.mdl", source)

    definition = build_definition(
        index,
        "inmemory://workspace.mdl",
        line=next(i for i, line in enumerate(lines) if "displayEmail = c.email" in line),
        character=lines[next(i for i, line in enumerate(lines) if "displayEmail = c.email" in line)].index("displayEmail") + 2,
    )

    assert definition is not None
    assert definition.uri == "inmemory://workspace.mdl"
    assert definition.range.start.line == next(i for i, line in enumerate(lines) if "displayEmail = c.email" in line)
    assert definition.range.start.character == 4


def test_definition_on_field_reference_goes_to_source_field():
    source = """
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
    lines = source.splitlines()
    index = LspWorkspaceIndex()
    index.upsert_document("inmemory://workspace.mdl", source)

    definition = build_definition(
        index,
        "inmemory://workspace.mdl",
        line=next(i for i, line in enumerate(lines) if "displayEmail = c.email" in line),
        character=lines[next(i for i, line in enumerate(lines) if "displayEmail = c.email" in line)].index("c.email") + 2,
    )

    assert definition is not None
    assert definition.uri == "inmemory://workspace.mdl"
    assert definition.range.start.line == next(i for i, line in enumerate(lines) if "email?: string" in line)
    assert definition.range.start.character == 4


def test_definition_on_projection_in_from_clause_goes_to_projection_declaration():
    lines = PROJECTION_SOURCE_TEXT.splitlines()
    from_line = next(i for i, l in enumerate(lines) if "from catalog.ProductReply @ 1 as p" in l)
    character = lines[from_line].index("ProductReply") + 3  # cursor mid-word on "ProductReply"
    decl_line = next(i for i, l in enumerate(lines) if "projection ProductReply @ 1" in l)

    index = LspWorkspaceIndex()
    index.upsert_document("inmemory://workspace.mdl", PROJECTION_SOURCE_TEXT)

    definition = build_definition(index, "inmemory://workspace.mdl", line=from_line, character=character)

    assert definition is not None
    assert definition.uri == "inmemory://workspace.mdl"
    assert definition.range.start.line == decl_line


def test_definition_on_projection_source_field_reference_goes_to_source_projection_field():
    lines = PROJECTION_SOURCE_TEXT.splitlines()
    usage_line = lines.index("    displayId <- p.productId")
    usage_character = lines[usage_line].index("productId") + 1
    declaration_line = lines.index("    productId <- c.customerId")

    index = LspWorkspaceIndex()
    index.upsert_document("inmemory://workspace.mdl", PROJECTION_SOURCE_TEXT)

    definition = build_definition(index, "inmemory://workspace.mdl", line=usage_line, character=usage_character)

    assert definition is not None
    assert definition.uri == "inmemory://workspace.mdl"
    assert definition.range.start.line == declaration_line
    assert definition.range.start.character == lines[declaration_line].index("productId")


_REF_TYPE_TEXT = """
domain commerce {
  owner: "test-team"
  event Order @ 1 (additive) {
    @key orderId: uuid
    status: string
  }
}

domain shipping {
  owner: "test-team"
  entity Shipment @ 1 (additive) {
    @key shipmentId: uuid
    orderId: ref<commerce.Order>
  }
}
""".strip("\n")


def test_definition_on_ref_type_goes_to_model_declaration():
    lines = _REF_TYPE_TEXT.splitlines()
    ref_line = next(i for i, l in enumerate(lines) if "ref<commerce.Order>" in l)
    ref_char = lines[ref_line].index("commerce") + 3  # cursor on "commerce"

    index = LspWorkspaceIndex()
    index.upsert_document("inmemory://workspace.mdl", _REF_TYPE_TEXT)

    definition = build_definition(index, "inmemory://workspace.mdl", line=ref_line, character=ref_char)

    assert definition is not None
    assert definition.uri == "inmemory://workspace.mdl"
    decl_line = next(i for i, l in enumerate(lines) if "event Order @ 1" in l)
    assert definition.range.start.line == decl_line


def test_definition_on_ref_type_name_part_goes_to_model_declaration():
    lines = _REF_TYPE_TEXT.splitlines()
    ref_line = next(i for i, l in enumerate(lines) if "ref<commerce.Order>" in l)
    ref_char = lines[ref_line].index("Order")  # cursor on "Order"

    index = LspWorkspaceIndex()
    index.upsert_document("inmemory://workspace.mdl", _REF_TYPE_TEXT)

    definition = build_definition(index, "inmemory://workspace.mdl", line=ref_line, character=ref_char)

    assert definition is not None
    decl_line = next(i for i, l in enumerate(lines) if "event Order @ 1" in l)
    assert definition.range.start.line == decl_line


def test_definition_on_ref_type_resolves_latest_version():
    text = """
domain commerce {
  owner: "test-team"
  entity Product @ 1 (additive) {
    @key productId: uuid
  }

  entity Product @ 2 (additive) {
    @key productId: uuid
    name: string
  }
}

domain catalog {
  owner: "test-team"
  entity Listing @ 1 (additive) {
    @key listingId: uuid
    productId: ref<commerce.Product>
  }
}
""".strip("\n")

    lines = text.splitlines()
    ref_line = next(i for i, l in enumerate(lines) if "ref<commerce.Product>" in l)
    ref_char = lines[ref_line].index("Product")

    index = LspWorkspaceIndex()
    index.upsert_document("inmemory://workspace.mdl", text)

    definition = build_definition(index, "inmemory://workspace.mdl", line=ref_line, character=ref_char)

    assert definition is not None
    # Should point to the latest (@ 2) declaration
    decl_line = next(i for i, l in enumerate(lines) if "entity Product @ 2" in l)
    assert definition.range.start.line == decl_line
