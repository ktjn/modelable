from modelable.lsp.references import build_references
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
""".strip("\n")


def _index() -> LspWorkspaceIndex:
    index = LspWorkspaceIndex()
    index.upsert_document("inmemory://workspace.mdl", WORKSPACE_TEXT)
    return index


def _projection_index() -> LspWorkspaceIndex:
    index = LspWorkspaceIndex()
    index.upsert_document("inmemory://workspace.mdl", PROJECTION_SOURCE_TEXT)
    return index


def _line_number(lines: list[str], snippet: str) -> int:
    return next(i for i, line in enumerate(lines) if snippet in line)


def test_references_for_model_declaration_includes_source_usage():
    lines = WORKSPACE_TEXT.splitlines()
    references = build_references(
        _index(),
        "inmemory://workspace.mdl",
        line=next(i for i, line in enumerate(lines) if "entity Customer @ 1 (additive)" in line),
        character=11,
        include_declaration=False,
    )

    assert references is not None
    assert len(references) == 1
    assert references[0].range.start.line == _line_number(lines, "from customer.Customer @ 1 as c")
    assert references[0].range.start.character == 9


def test_references_for_model_field_includes_projection_usage():
    lines = WORKSPACE_TEXT.splitlines()
    references = build_references(
        _index(),
        "inmemory://workspace.mdl",
        line=next(i for i, line in enumerate(lines) if "email?: string" in line),
        character=6,
        include_declaration=False,
    )

    assert references is not None
    assert len(references) == 1
    assert references[0].range.start.line == _line_number(lines, "displayEmail = c.email")
    assert references[0].range.start.character == 19


def test_references_for_projection_field_includes_downstream_usage_and_declaration():
    lines = PROJECTION_SOURCE_TEXT.splitlines()
    declaration_line = lines.index("    productId <- c.customerId")
    declaration_character = lines[declaration_line].index("productId") + 1

    references = build_references(
        _projection_index(),
        "inmemory://workspace.mdl",
        line=declaration_line,
        character=declaration_character,
        include_declaration=True,
    )

    assert references is not None
    assert len(references) == 2
    assert {(location.range.start.line, location.range.start.character) for location in references} == {
        (declaration_line, lines[declaration_line].index("productId")),
        (
            lines.index("    displayId <- p.productId"),
            lines[lines.index("    displayId <- p.productId")].index("p.productId"),
        ),
    }
