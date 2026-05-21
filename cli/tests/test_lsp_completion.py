from modelable.lsp.completion import build_completion
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


def _index() -> LspWorkspaceIndex:
    index = LspWorkspaceIndex()
    index.upsert_document("inmemory://workspace.mdl", WORKSPACE_TEXT)
    return index


def test_completion_suggests_keywords_at_top_level():
    completion = build_completion(_index(), "inmemory://workspace.mdl", line=0, character=0)

    labels = [item.label for item in completion.items]

    assert labels[:4] == ["domain", "entity", "aggregate", "event"]


def test_completion_suggests_annotations_after_at_symbol():
    completion = build_completion(_index(), "inmemory://workspace.mdl", line=2, character=5)

    labels = [item.label for item in completion.items]

    assert "@classification" in labels
    assert "@server" in labels


def test_completion_suggests_workspace_names_after_from_clause():
    completion = build_completion(_index(), "inmemory://workspace.mdl", line=9, character=9)

    labels = [item.label for item in completion.items]

    assert "customer.Customer" in labels
    assert "billing.BillingCustomer" in labels


def test_completion_suggests_active_projection_fields_inside_body():
    completion = build_completion(_index(), "inmemory://workspace.mdl", line=11, character=4)

    labels = [item.label for item in completion.items]

    assert labels == ["billingId", "displayEmail"]


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
""".strip("\n")


def test_completion_suggests_projection_source_fields_for_alias():
    index = LspWorkspaceIndex()
    index.upsert_document("inmemory://workspace.mdl", PROJECTION_SOURCE_TEXT)
    lines = PROJECTION_SOURCE_TEXT.splitlines()
    line_no = next(i for i, l in enumerate(lines) if "displayId <- p." in l)
    # Position cursor right after "p." to simulate typing before a field name
    character = lines[line_no].index("p.") + 2

    completion = build_completion(index, "inmemory://workspace.mdl", line=line_no, character=character)

    labels = [item.label for item in completion.items]
    assert "productId" in labels
    assert "statusText" in labels

