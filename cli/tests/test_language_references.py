from modelable.language.dto import LanguagePosition
from modelable.language.positions import codepoint_to_utf16
from modelable.language.references import references
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

DECL_URI = "file:///models.mdl"
PROJ_URI = "file:///projections.mdl"
DECL_TEXT = """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    email?: string
  }
}
""".strip("\n")
PROJ_TEXT = """
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


def parsed_workspace(text: str = WORKSPACE_TEXT, uri: str = URI) -> LanguageWorkspace:
    state = LanguageWorkspace()
    state.synchronize(1, (LanguageDocument.from_text(uri, text, 1),))
    return state


def cross_file_workspace() -> LanguageWorkspace:
    state = LanguageWorkspace()
    state.synchronize(
        1,
        (
            LanguageDocument.from_text(DECL_URI, DECL_TEXT, 1),
            LanguageDocument.from_text(PROJ_URI, PROJ_TEXT, 1),
        ),
    )
    return state


def position_of(text: str, snippet: str, token: str) -> LanguagePosition:
    lines = text.splitlines()
    line = next(index for index, value in enumerate(lines) if snippet in value)
    codepoint = lines[line].index(token) + 1
    return LanguagePosition(line, codepoint_to_utf16(lines[line], codepoint))


def test_references_on_qualified_ref_includes_declaration_and_usages() -> None:
    state = parsed_workspace()
    result = references(
        state,
        URI,
        position_of(WORKSPACE_TEXT, "entity Customer @ 1", "Customer"),
        include_declaration=True,
    )
    assert len(result) >= 2
    uris = {loc.uri for loc in result}
    assert URI in uris


def test_references_without_declaration_excludes_it() -> None:
    state = parsed_workspace()
    decl_pos = position_of(WORKSPACE_TEXT, "entity Customer @ 1", "Customer")
    with_decl = references(state, URI, decl_pos, include_declaration=True)
    without_decl = references(state, URI, decl_pos, include_declaration=False)
    assert len(with_decl) > len(without_decl)


def test_references_are_sorted() -> None:
    state = parsed_workspace()
    result = references(
        state,
        URI,
        position_of(WORKSPACE_TEXT, "entity Customer @ 1", "Customer"),
        include_declaration=True,
    )
    assert result == tuple(sorted(result))


def test_references_cross_file_finds_usages_in_other_document() -> None:
    state = cross_file_workspace()
    result = references(
        state,
        DECL_URI,
        position_of(DECL_TEXT, "entity Customer @ 1", "Customer"),
        include_declaration=True,
    )
    assert any(loc.uri == PROJ_URI for loc in result)
    assert any(loc.uri == DECL_URI for loc in result)


def test_references_exclude_stale_file() -> None:
    state = cross_file_workspace()
    changed_proj = PROJ_TEXT.replace("customer.Customer @ 1", "customer.Customer @ 2")
    state.synchronize(
        2,
        (
            LanguageDocument.from_text(DECL_URI, DECL_TEXT, 1),
            LanguageDocument.from_text(PROJ_URI, changed_proj, 2),
        ),
    )
    result = references(
        state,
        DECL_URI,
        position_of(DECL_TEXT, "entity Customer @ 1", "Customer"),
        include_declaration=True,
    )
    for loc in result:
        if loc.uri == PROJ_URI:
            assert state.is_location_current(loc)


def test_references_on_field_includes_projection_usage() -> None:
    state = parsed_workspace()
    result = references(
        state,
        URI,
        position_of(WORKSPACE_TEXT, "customerId: uuid", "customerId"),
        include_declaration=True,
    )
    assert len(result) >= 2


def test_references_returns_empty_for_unknown_symbol() -> None:
    state = parsed_workspace()
    lines = WORKSPACE_TEXT.splitlines()
    line = next(i for i, line in enumerate(lines) if "owner:" in line)
    result = references(state, URI, LanguagePosition(line, 4), include_declaration=True)
    assert result == ()


def test_references_returns_empty_for_unknown_uri() -> None:
    state = parsed_workspace()
    result = references(state, "file:///unknown.mdl", LanguagePosition(0, 0), include_declaration=True)
    assert result == ()


def test_references_returns_empty_without_semantic_workspace() -> None:
    state = LanguageWorkspace()
    state.synchronize(1, (LanguageDocument.from_text(URI, "invalid content {{{", 1),))
    result = references(state, URI, LanguagePosition(0, 0), include_declaration=True)
    assert result == ()


def test_references_returns_empty_for_out_of_range() -> None:
    state = parsed_workspace()
    result = references(state, URI, LanguagePosition(999, 0), include_declaration=True)
    assert result == ()


def test_references_with_utf16_position() -> None:
    decl_uri = "file:///models.mdl"
    decl_text = """
domain sales {
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
    from sales.Customer @ 1 as c
  {
    billingId <- c.customerId
  }
}
""".strip("\n")
    proj_uri = "file:///projections.mdl"
    edited_proj = proj_text.replace(
        "    from sales.Customer @ 1 as c",
        "    😀 from sales.Customer @ 1 as c",
    )
    state = LanguageWorkspace()
    state.synchronize(
        1,
        (
            LanguageDocument.from_text(decl_uri, decl_text, 1),
            LanguageDocument.from_text(proj_uri, proj_text, 1),
        ),
    )
    state.synchronize(
        2,
        (
            LanguageDocument.from_text(decl_uri, decl_text, 1),
            LanguageDocument.from_text(proj_uri, edited_proj, 2),
        ),
    )
    result = references(
        state,
        proj_uri,
        position_of(edited_proj, "😀 from sales.Customer", "Customer"),
        include_declaration=True,
    )
    assert len(result) >= 1
