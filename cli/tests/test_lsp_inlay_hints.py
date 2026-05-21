from modelable.lsp.inlay_hints import build_inlay_hints
from modelable.lsp.workspace import LspWorkspaceIndex
from lsprotocol import types


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
""".strip("\n")


def _index() -> LspWorkspaceIndex:
    index = LspWorkspaceIndex()
    index.upsert_document("inmemory://workspace.mdl", WORKSPACE_TEXT)
    return index


def _full_range() -> types.Range:
    lines = WORKSPACE_TEXT.splitlines()
    return types.Range(
        start=types.Position(line=0, character=0),
        end=types.Position(line=len(lines) - 1, character=0),
    )


def test_inlay_hint_shows_field_source_type_for_direct_mapping():
    lines = WORKSPACE_TEXT.splitlines()
    direct_line = next(i for i, l in enumerate(lines) if "billingId <- c.customerId" in l)

    hints = build_inlay_hints(_index(), "inmemory://workspace.mdl", _full_range())

    assert hints is not None
    line_hints = [h for h in hints if h.position.line == direct_line]
    assert len(line_hints) == 1
    assert ": uuid" in line_hints[0].label


def test_inlay_hint_skips_computed_mapping():
    lines = WORKSPACE_TEXT.splitlines()
    computed_line = next(i for i, l in enumerate(lines) if "displayEmail = c.email" in l)

    hints = build_inlay_hints(_index(), "inmemory://workspace.mdl", _full_range())

    assert hints is not None
    line_hints = [h for h in hints if h.position.line == computed_line]
    assert len(line_hints) == 0


def test_inlay_hint_shows_model_kind_on_from_line():
    lines = WORKSPACE_TEXT.splitlines()
    from_line = next(i for i, l in enumerate(lines) if "from customer.Customer @ 1 as c" in l)

    hints = build_inlay_hints(_index(), "inmemory://workspace.mdl", _full_range())

    assert hints is not None
    line_hints = [h for h in hints if h.position.line == from_line]
    assert len(line_hints) == 1
    assert "[entity]" in line_hints[0].label


def test_inlay_hint_shows_projection_kind_for_projection_source():
    text = """
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
""".strip("\n")
    index = LspWorkspaceIndex()
    index.upsert_document("inmemory://workspace.mdl", text)
    lines = text.splitlines()
    from_line = next(i for i, l in enumerate(lines) if "from catalog.ProductReply @ 1 as p" in l)
    full_range = types.Range(
        start=types.Position(line=0, character=0),
        end=types.Position(line=len(lines) - 1, character=0),
    )

    hints = build_inlay_hints(index, "inmemory://workspace.mdl", full_range)

    assert hints is not None
    line_hints = [h for h in hints if h.position.line == from_line]
    assert len(line_hints) == 1
    assert "[projection]" in line_hints[0].label
