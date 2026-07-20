from lsprotocol import types

from modelable.lsp.completion import build_completion
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


def _line_number(text: str, snippet: str) -> int:
    lines = text.splitlines()
    if snippet == "":
        return next(i for i, line in enumerate(lines) if not line)
    return next(i for i, line in enumerate(lines) if snippet in line)


def test_completion_adapter_maps_neutral_kind_and_replacement_range():
    completion = build_completion(
        _index(),
        "inmemory://workspace.mdl",
        line=_line_number(WORKSPACE_TEXT, "displayEmail = c.email"),
        character=len("    display"),
    )

    assert [item.label for item in completion.items] == ["displayEmail"]
    assert completion.items[0].kind == types.CompletionItemKind.Field
    assert completion.items[0].text_edit == types.TextEdit(
        range=types.Range(
            start=types.Position(
                line=_line_number(WORKSPACE_TEXT, "displayEmail = c.email"),
                character=4,
            ),
            end=types.Position(
                line=_line_number(WORKSPACE_TEXT, "displayEmail = c.email"),
                character=len("    display"),
            ),
        ),
        new_text="displayEmail",
    )
