from dataclasses import dataclass

import pytest

from modelable.language.completion import complete
from modelable.language.dto import LanguagePosition, LanguageRange
from modelable.language.workspace import LanguageDocument, LanguageWorkspace

URI = "file:///projection.mdl"
WORKSPACE_TEXT = """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    customer_name: string
    status: string
  }
}

domain billing {
  owner: "test-team"
  projection BillingCustomer @ 1
    from customer.Customer @ 1 as c
  {
    billingId <- c.customerId
    displayEmail = c.customer_name
  }
}
""".strip("\n")


@dataclass(frozen=True)
class _Catalog:
    def domain_names(self) -> tuple[str, ...]:
        return ("remote",)

    def references(self) -> tuple[tuple[str, str], ...]:
        return (("remote", "RemoteCustomer"),)

    def model_versions(self) -> tuple[tuple[str, str, int], ...]:
        return (("remote", "RemoteCustomer", 2), ("remote", "RemoteCustomer", 12))

    def field_names(self, domain: str, name: str, version: int) -> tuple[str, ...]:
        if (domain, name, version) == ("remote", "RemoteCustomer", 2):
            return ("remoteId", "remoteName")
        return ()


def parsed_language_workspace(text: str = WORKSPACE_TEXT) -> LanguageWorkspace:
    state = LanguageWorkspace()
    state.synchronize(1, (LanguageDocument.from_text(URI, text, 1),))
    return state


def replace_document(state: LanguageWorkspace, uri: str, text: str) -> tuple[LanguageDocument, ...]:
    return tuple(
        LanguageDocument.from_text(uri, text, document.version + 1) if document_uri == uri else document
        for document_uri, document in state.documents.items()
    )


def _complete_line(
    line_text: str,
    *,
    catalog: _Catalog | None = None,
) -> tuple:
    text = WORKSPACE_TEXT + "\n" + line_text
    state = parsed_language_workspace()
    state.synchronize(2, replace_document(state, URI, text))
    return complete(
        state,
        URI,
        LanguagePosition(len(text.splitlines()) - 1, len(line_text)),
        catalog,
    )


def test_completion_suggests_keywords_with_neutral_kinds_and_ordering() -> None:
    result = complete(parsed_language_workspace(), URI, LanguagePosition(0, 0))

    assert [item.label for item in result[:4]] == ["domain", "entity", "aggregate", "event"]
    assert all(item.kind == "keyword" for item in result)
    assert [item.sort_text for item in result[:3]] == ["0000", "0001", "0002"]


def test_completion_suggests_annotations_after_at_symbol() -> None:
    result = _complete_line("@")

    assert "@classification" in [item.label for item in result]
    assert all(item.kind == "annotation" for item in result)
    assert result[0].replacement == LanguageRange.at(18, 0, 18, 1)


def test_completion_suggests_local_domains_and_declarations() -> None:
    domains = _complete_line("import domain ")
    declarations = _complete_line("from ")

    assert [item.label for item in domains] == ["billing", "customer"]
    assert all(item.kind == "module" for item in domains)
    assert [item.label for item in declarations] == [
        "customer.Customer",
        "billing.BillingCustomer",
    ]
    assert all(item.kind == "class" for item in declarations)


def test_completion_suggests_catalog_versions_and_import_models() -> None:
    versions = _complete_line("from remote.RemoteCustomer @1", catalog=_Catalog())
    models = _complete_line(
        'import domain remote from registry "peer" at remote.R',
        catalog=_Catalog(),
    )

    assert [item.label for item in versions] == ["12"]
    assert versions[0].kind == "value"
    assert [item.label for item in models] == ["RemoteCustomer"]
    assert models[0].kind == "class"


def test_completion_suggests_model_and_projection_fields() -> None:
    state = parsed_language_workspace()
    model_line = WORKSPACE_TEXT.splitlines().index("    customer_name: string")
    projection_line = WORKSPACE_TEXT.splitlines().index("    billingId <- c.customerId")

    model = complete(state, URI, LanguagePosition(model_line, 4))
    projection = complete(state, URI, LanguagePosition(projection_line, 4))

    assert [item.label for item in model] == ["customerId", "customer_name", "status"]
    assert [item.label for item in projection] == ["billingId", "displayEmail"]
    assert all(item.kind == "property" for item in (*model, *projection))


def test_completion_suggests_local_and_catalog_alias_fields() -> None:
    local = _complete_line("    c.customer_")
    remote_text = WORKSPACE_TEXT.replace(
        "    from customer.Customer @ 1 as c",
        "    from remote.RemoteCustomer @ 2 as r",
    ).replace("    billingId <- c.customerId", "    r.remote")
    state = parsed_language_workspace()
    state.synchronize(2, replace_document(state, URI, remote_text))
    line = remote_text.splitlines().index("    r.remote")
    remote = complete(state, URI, LanguagePosition(line, len("    r.remote")), _Catalog())

    assert [item.label for item in local] == ["customer_name"]
    assert [item.label for item in remote] == ["remoteId", "remoteName"]


def test_completion_uses_current_prefix_with_last_parseable_semantics() -> None:
    state = parsed_language_workspace()
    current = WORKSPACE_TEXT.replace("    customer_name: string", "    customer_na")
    state.synchronize(2, replace_document(state, URI, current))
    line = current.splitlines().index("    customer_na")

    result = complete(state, URI, LanguagePosition(line, len("    customer_na")))

    assert [item.label for item in result] == ["customer_name"]
    assert result[0].kind == "property"
    assert result[0].replacement == LanguageRange.at(line, 4, line, 15)


def test_completion_converts_codepoint_prefix_span_to_utf16_range() -> None:
    state = parsed_language_workspace()
    current = WORKSPACE_TEXT.replace("    customer_name: string", "😀 customer_")
    state.synchronize(2, replace_document(state, URI, current))
    line = current.splitlines().index("😀 customer_")

    result = complete(state, URI, LanguagePosition(line, 12))

    assert [item.label for item in result] == ["customer_name"]
    assert result[0].replacement == LanguageRange.at(line, 3, line, 12)


def test_completion_deduplicates_catalog_candidates_deterministically() -> None:
    result = _complete_line("domain ", catalog=_Catalog())

    assert [item.label for item in result] == ["billing", "customer", "remote"]
    assert [item.sort_text for item in result] == ["0000", "0001", "0002"]


@pytest.mark.parametrize(
    ("uri", "position"),
    [
        ("file:///missing.mdl", LanguagePosition(0, 0)),
        (URI, LanguagePosition(-1, 0)),
        (URI, LanguagePosition(500, 0)),
        (URI, LanguagePosition(0, -1)),
        (URI, LanguagePosition(0, 500)),
    ],
)
def test_completion_returns_empty_for_invalid_uri_or_position(
    uri: str,
    position: LanguagePosition,
) -> None:
    assert complete(parsed_language_workspace(), uri, position) == ()


def test_completion_returns_empty_without_semantics() -> None:
    state = LanguageWorkspace()
    state.synchronize(1, (LanguageDocument.from_text(URI, "domain broken {", 1),))

    assert complete(state, URI, LanguagePosition(0, 0)) == ()


def test_completion_does_not_expose_catalog_candidates_without_catalog() -> None:
    assert "remote" not in [item.label for item in _complete_line("domain ")]
    assert _complete_line("from remote.RemoteCustomer @") == ()
