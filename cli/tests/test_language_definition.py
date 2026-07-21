from modelable.language.definition import definition
from modelable.language.dto import LanguagePosition
from modelable.language.positions import codepoint_to_utf16
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

CROSS_FILE_DECL_URI = "file:///models.mdl"
CROSS_FILE_PROJ_URI = "file:///projections.mdl"
CROSS_FILE_DECL_TEXT = """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    email?: string
  }
}
""".strip("\n")
CROSS_FILE_PROJ_TEXT = """
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

REF_TYPE_TEXT = """
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


def parsed_workspace(text: str = WORKSPACE_TEXT, uri: str = URI) -> LanguageWorkspace:
    state = LanguageWorkspace()
    state.synchronize(1, (LanguageDocument.from_text(uri, text, 1),))
    return state


def cross_file_workspace() -> LanguageWorkspace:
    state = LanguageWorkspace()
    state.synchronize(
        1,
        (
            LanguageDocument.from_text(CROSS_FILE_DECL_URI, CROSS_FILE_DECL_TEXT, 1),
            LanguageDocument.from_text(CROSS_FILE_PROJ_URI, CROSS_FILE_PROJ_TEXT, 1),
        ),
    )
    return state


def position_of(text: str, snippet: str, token: str) -> LanguagePosition:
    lines = text.splitlines()
    line = next(index for index, value in enumerate(lines) if snippet in value)
    codepoint = lines[line].index(token) + 1
    return LanguagePosition(line, codepoint_to_utf16(lines[line], codepoint))


def test_definition_on_qualified_ref_goes_to_declaration() -> None:
    state = parsed_workspace()
    result = definition(
        state,
        URI,
        position_of(WORKSPACE_TEXT, "from customer.Customer @ 1 as c", "Customer"),
    )
    assert result is not None
    assert result.uri == URI
    decl_line = next(i for i, line in enumerate(WORKSPACE_TEXT.splitlines()) if "entity Customer @ 1" in line)
    assert result.range.start.line == decl_line


def test_definition_on_field_reference_goes_to_source_field() -> None:
    state = parsed_workspace()
    result = definition(
        state,
        URI,
        position_of(WORKSPACE_TEXT, "displayEmail = c.email", "c.email"),
    )
    assert result is not None
    assert result.uri == URI
    field_line = next(i for i, line in enumerate(WORKSPACE_TEXT.splitlines()) if "email?: string" in line)
    assert result.range.start.line == field_line


def test_definition_on_projection_field_goes_to_its_declaration() -> None:
    state = parsed_workspace()
    result = definition(
        state,
        URI,
        position_of(WORKSPACE_TEXT, "displayEmail = c.email", "displayEmail"),
    )
    assert result is not None
    assert result.uri == URI
    assert result.range.start.line == next(
        i for i, line in enumerate(WORKSPACE_TEXT.splitlines()) if "displayEmail = c.email" in line
    )


def test_definition_on_ref_type_goes_to_declaration() -> None:
    state = parsed_workspace(REF_TYPE_TEXT)
    result = definition(
        state,
        URI,
        position_of(REF_TYPE_TEXT, "ref<commerce.Order>", "commerce"),
    )
    assert result is not None
    decl_line = next(i for i, line in enumerate(REF_TYPE_TEXT.splitlines()) if "event Order @ 1" in line)
    assert result.range.start.line == decl_line


def test_definition_on_ref_type_resolves_latest_version() -> None:
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
    state = parsed_workspace(text)
    result = definition(state, URI, position_of(text, "ref<commerce.Product>", "Product"))
    assert result is not None
    decl_line = next(i for i, line in enumerate(text.splitlines()) if "entity Product @ 2" in line)
    assert result.range.start.line == decl_line


def test_definition_cross_file_finds_target_in_other_document() -> None:
    state = cross_file_workspace()
    result = definition(
        state,
        CROSS_FILE_PROJ_URI,
        position_of(CROSS_FILE_PROJ_TEXT, "from customer.Customer @ 1 as c", "Customer"),
    )
    assert result is not None
    assert result.uri == CROSS_FILE_DECL_URI
    decl_line = next(i for i, line in enumerate(CROSS_FILE_DECL_TEXT.splitlines()) if "entity Customer @ 1" in line)
    assert result.range.start.line == decl_line


def test_definition_omits_changed_semantic_target() -> None:
    state = cross_file_workspace()
    changed_decl = CROSS_FILE_DECL_TEXT.replace("customerId: uuid", "customerId: string")
    state.synchronize(
        2,
        (
            LanguageDocument.from_text(CROSS_FILE_DECL_URI, changed_decl, 2),
            LanguageDocument.from_text(CROSS_FILE_PROJ_URI, CROSS_FILE_PROJ_TEXT, 1),
        ),
    )
    result = definition(
        state,
        CROSS_FILE_PROJ_URI,
        position_of(CROSS_FILE_PROJ_TEXT, "from customer.Customer @ 1 as c", "Customer"),
    )
    assert result is not None
    assert result.uri == CROSS_FILE_DECL_URI


def test_definition_returns_none_for_unknown_symbol() -> None:
    state = parsed_workspace()
    lines = WORKSPACE_TEXT.splitlines()
    line = next(i for i, line in enumerate(lines) if "owner:" in line)
    result = definition(state, URI, LanguagePosition(line, 4))
    assert result is None


def test_definition_returns_none_for_unknown_uri() -> None:
    state = parsed_workspace()
    result = definition(state, "file:///unknown.mdl", LanguagePosition(0, 0))
    assert result is None


def test_definition_returns_none_without_semantic_workspace() -> None:
    state = LanguageWorkspace()
    state.synchronize(1, (LanguageDocument.from_text(URI, "invalid content {{{", 1),))
    result = definition(state, URI, LanguagePosition(0, 0))
    assert result is None


def test_definition_returns_none_for_out_of_range_position() -> None:
    state = parsed_workspace()
    result = definition(state, URI, LanguagePosition(999, 0))
    assert result is None


def test_definition_with_utf16_position() -> None:
    base_text = """
domain sales {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}

domain billing {
  owner: "test-team"
  projection BillingCustomer @ 1
    from sales.Customer @ 1 as c
  {
    billingId <- c.customerId
  }
}
""".strip("\n")
    edited_text = base_text.replace(
        "    from sales.Customer @ 1 as c",
        "    😀 from sales.Customer @ 1 as c",
    )
    state = parsed_workspace(base_text)
    state.synchronize(2, (LanguageDocument.from_text(URI, edited_text, 2),))
    result = definition(
        state,
        URI,
        position_of(edited_text, "😀 from sales.Customer", "Customer"),
    )
    assert result is not None
    decl_line = next(i for i, line in enumerate(base_text.splitlines()) if "entity Customer @ 1" in line)
    assert result.range.start.line == decl_line
