import pytest

from modelable.language.dto import LanguagePosition
from modelable.language.rename import InvalidRenameError, prepare_rename, rename
from modelable.language.workspace import LanguageDocument, LanguageWorkspace

URI = "file:///workspace.mdl"
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


def parsed_workspace(text: str = WORKSPACE_TEXT, uri: str = URI) -> LanguageWorkspace:
    state = LanguageWorkspace()
    state.synchronize(1, (LanguageDocument.from_text(uri, text, 1),))
    return state


def _line_of(text: str, snippet: str) -> int:
    return next(i for i, line in enumerate(text.splitlines()) if snippet in line)


def _position_of(text: str, snippet: str, token: str) -> LanguagePosition:
    line = _line_of(text, snippet)
    character = text.splitlines()[line].index(token) + 1
    return LanguagePosition(line, character)


def test_prepare_rename_on_model_declaration() -> None:
    state = parsed_workspace()
    result = prepare_rename(
        state,
        URI,
        _position_of(WORKSPACE_TEXT, "entity Customer @ 1", "Customer"),
    )
    assert result is not None
    assert result.placeholder == "Customer"
    assert result.range.start.line == _line_of(WORKSPACE_TEXT, "entity Customer @ 1")


def test_prepare_rename_returns_none_for_unknown_symbol() -> None:
    state = parsed_workspace()
    line = _line_of(WORKSPACE_TEXT, 'owner: "test-team"')
    result = prepare_rename(state, URI, LanguagePosition(line, 4))
    assert result is None


def test_prepare_rename_returns_none_when_not_semantically_current() -> None:
    state = parsed_workspace()
    state.synchronize(2, (LanguageDocument.from_text(URI, "invalid {{{", 2),))
    result = prepare_rename(
        state,
        URI,
        LanguagePosition(0, 1),
    )
    assert result is None


def test_rename_model_declaration_updates_definition_and_references() -> None:
    state = parsed_workspace()
    decl_line = _line_of(WORKSPACE_TEXT, "entity Customer @ 1")
    ref_line = _line_of(WORKSPACE_TEXT, "from customer.Customer @ 1 as c")

    result = rename(
        state,
        URI,
        _position_of(WORKSPACE_TEXT, "entity Customer @ 1", "Customer"),
        "Client",
    )

    edit_lines = sorted(e.range.start.line for e in result.edits)
    assert decl_line in edit_lines
    assert ref_line in edit_lines
    assert all(e.new_text == "Client" for e in result.edits)


def test_rename_model_field_on_reference_updates_definition_and_usage() -> None:
    state = parsed_workspace()
    decl_line = _line_of(WORKSPACE_TEXT, "email?: string")
    ref_line = _line_of(WORKSPACE_TEXT, "displayEmail = c.email")

    result = rename(
        state,
        URI,
        _position_of(WORKSPACE_TEXT, "displayEmail = c.email", "c.email"),
        "contactEmail",
    )

    edit_lines = sorted(e.range.start.line for e in result.edits)
    assert decl_line in edit_lines
    assert ref_line in edit_lines
    assert all(e.new_text == "contactEmail" for e in result.edits)


def test_rename_projection_field_via_alias_finds_declaration() -> None:
    state = parsed_workspace(PROJECTION_SOURCE_TEXT)

    result = rename(
        state,
        URI,
        _position_of(PROJECTION_SOURCE_TEXT, "displayId <- p.productId", "p.productId"),
        "itemId",
    )

    edit_lines = {e.range.start.line for e in result.edits}
    decl_line = _line_of(PROJECTION_SOURCE_TEXT, "productId <- c.customerId")
    assert decl_line in edit_lines


def test_rename_projection_field_updates_downstream_usages() -> None:
    state = parsed_workspace(PROJECTION_SOURCE_TEXT)

    result = rename(
        state,
        URI,
        _position_of(PROJECTION_SOURCE_TEXT, "productId <- c.customerId", "productId"),
        "itemId",
    )

    edit_lines = {e.range.start.line for e in result.edits}
    downstream_line = _line_of(PROJECTION_SOURCE_TEXT, "displayId <- p.productId")
    assert downstream_line in edit_lines


def test_rename_rejects_invalid_identifier() -> None:
    state = parsed_workspace()
    with pytest.raises(InvalidRenameError):
        rename(
            state,
            URI,
            _position_of(WORKSPACE_TEXT, "entity Customer @ 1", "Customer"),
            "invalid-name",
        )


def test_rename_rejects_when_not_semantically_current() -> None:
    state = parsed_workspace()
    state.synchronize(2, (LanguageDocument.from_text(URI, "invalid {{{", 2),))
    with pytest.raises(InvalidRenameError):
        rename(state, URI, LanguagePosition(0, 1), "NewName")


def test_rename_rejects_unknown_symbol() -> None:
    state = parsed_workspace()
    line = _line_of(WORKSPACE_TEXT, 'owner: "test-team"')
    with pytest.raises(InvalidRenameError):
        rename(state, URI, LanguagePosition(line, 4), "NewName")


def test_rename_edits_carry_expected_version_and_hash() -> None:
    state = parsed_workspace()
    result = rename(
        state,
        URI,
        _position_of(WORKSPACE_TEXT, "entity Customer @ 1", "Customer"),
        "Client",
    )
    for edit in result.edits:
        assert edit.expected_version == 1
        assert edit.expected_hash != ""


def test_rename_returns_none_for_unknown_uri() -> None:
    state = parsed_workspace()
    with pytest.raises(InvalidRenameError):
        rename(state, "file:///unknown.mdl", LanguagePosition(0, 0), "NewName")


def test_rename_returns_none_for_out_of_range() -> None:
    state = parsed_workspace()
    with pytest.raises(InvalidRenameError):
        rename(state, URI, LanguagePosition(999, 0), "NewName")


def test_rename_cross_file() -> None:
    decl_uri = "file:///models.mdl"
    proj_uri = "file:///projections.mdl"
    decl_text = """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""".strip("\n")
    proj_text = """
domain billing {
  owner: "test-team"
  projection BillingCustomer @ 1
    from customer.Customer @ 1 as c
  {
    billingId <- c.customerId
  }
}
""".strip("\n")

    state = LanguageWorkspace()
    state.synchronize(
        1,
        (
            LanguageDocument.from_text(decl_uri, decl_text, 1),
            LanguageDocument.from_text(proj_uri, proj_text, 1),
        ),
    )

    result = rename(
        state,
        decl_uri,
        _position_of(decl_text, "entity Customer @ 1", "Customer"),
        "Client",
    )

    edit_uris = {e.uri for e in result.edits}
    assert decl_uri in edit_uris
    assert proj_uri in edit_uris
    assert all(e.new_text == "Client" for e in result.edits)


def test_rename_edits_are_sorted_descending_per_file() -> None:
    state = parsed_workspace()
    result = rename(
        state,
        URI,
        _position_of(WORKSPACE_TEXT, "entity Customer @ 1", "Customer"),
        "Client",
    )
    for i in range(len(result.edits) - 1):
        a, b = result.edits[i], result.edits[i + 1]
        if a.uri == b.uri:
            assert a.range.start >= b.range.start
