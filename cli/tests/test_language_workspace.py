from hashlib import sha256

import pytest

from modelable.language.dto import LanguageLocation, LanguageRange
from modelable.language.workspace import LanguageDocument, LanguageWorkspace

VALID_MODEL = """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""".strip()


def _hash(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def test_invalid_sync_advances_documents_but_keeps_last_parseable_workspace() -> None:
    state = LanguageWorkspace()
    valid = LanguageDocument.from_text("file:///a.mdl", VALID_MODEL, 1)
    first = state.synchronize(1, (valid,))
    invalid = LanguageDocument.from_text("file:///a.mdl", "domain broken {", 2)
    second = state.synchronize(2, (invalid,))

    assert first.revision == 1
    assert second.revision == 2
    assert second.diagnostics[0].severity == "error"
    assert second.diagnostics[0].path == "file:///a.mdl"
    assert state.current_document("file:///a.mdl") == invalid
    assert state.semantic_revision == 1
    assert state.workspace is not None
    assert state.semantic_workspace() is state.workspace
    assert not state.is_semantically_current()


def test_synchronize_orders_documents_by_uri() -> None:
    state = LanguageWorkspace()
    second = LanguageDocument.from_text("file:///b.mdl", VALID_MODEL, 1)
    first = LanguageDocument.from_text(
        "file:///a.mdl",
        VALID_MODEL.replace("customer", "orders"),
        1,
    )

    state.synchronize(1, (second, first))

    assert tuple(state.documents) == ("file:///a.mdl", "file:///b.mdl")
    assert state.workspace is not None
    assert [source.uri for source in state.workspace.sources] == [
        "file:///a.mdl",
        "file:///b.mdl",
    ]


def test_synchronize_rejects_duplicate_uris() -> None:
    state = LanguageWorkspace()
    first = LanguageDocument.from_text("file:///a.mdl", VALID_MODEL, 1)
    duplicate = LanguageDocument.from_text("file:///a.mdl", VALID_MODEL, 2)

    with pytest.raises(ValueError, match="unique"):
        state.synchronize(1, (first, duplicate))


@pytest.mark.parametrize("version", [0, -1])
def test_synchronize_rejects_non_positive_document_versions(version: int) -> None:
    state = LanguageWorkspace()
    document = LanguageDocument.from_text("file:///a.mdl", VALID_MODEL, version)

    with pytest.raises(ValueError, match="positive"):
        state.synchronize(1, (document,))


def test_synchronize_rejects_non_increasing_revisions_without_mutating_state() -> None:
    state = LanguageWorkspace()
    document = LanguageDocument.from_text("file:///a.mdl", VALID_MODEL, 1)
    state.synchronize(1, (document,))

    with pytest.raises(ValueError, match="increase"):
        state.synchronize(1, (document,))

    assert state.revision == 1
    assert state.current_document(document.uri) == document


def test_parse_failure_reports_current_source_hashes_for_all_documents() -> None:
    state = LanguageWorkspace()
    valid_text = VALID_MODEL.replace("customer", "orders")
    invalid_text = "domain broken {"
    valid = LanguageDocument.from_text("file:///a.mdl", valid_text, 1)
    invalid = LanguageDocument.from_text("file:///b.mdl", invalid_text, 1)

    synchronization = state.synchronize(1, (invalid, valid))

    assert synchronization.diagnostics[0].path == "file:///b.mdl"
    assert synchronization.source_hashes == {
        "file:///a.mdl": _hash(valid_text),
        "file:///b.mdl": _hash(invalid_text),
    }
    assert state.workspace is None
    assert state.semantic_revision is None


def test_semantic_diagnostics_advance_the_semantic_snapshot() -> None:
    state = LanguageWorkspace()
    duplicate_domain = LanguageDocument.from_text(
        "file:///b.mdl",
        VALID_MODEL,
        1,
    )
    first = LanguageDocument.from_text("file:///a.mdl", VALID_MODEL, 1)

    synchronization = state.synchronize(1, (duplicate_domain, first))

    assert any(diagnostic.code == "SEM" for diagnostic in synchronization.diagnostics)
    assert state.semantic_revision == 1
    assert state.is_semantically_current()
    assert state.semantic_hashes == synchronization.source_hashes


def test_location_is_current_only_when_its_document_matches_semantic_hash() -> None:
    state = LanguageWorkspace()
    first = LanguageDocument.from_text("file:///a.mdl", VALID_MODEL, 1)
    second = LanguageDocument.from_text(
        "file:///b.mdl",
        VALID_MODEL.replace("customer", "orders"),
        1,
    )
    state.synchronize(1, (first, second))
    state.synchronize(
        2,
        (
            LanguageDocument.from_text("file:///a.mdl", "domain broken {", 2),
            second,
        ),
    )
    range_ = LanguageRange.at(0, 0, 0, 0)

    assert not state.is_location_current(LanguageLocation("file:///a.mdl", range_))
    assert state.is_location_current(LanguageLocation("file:///b.mdl", range_))
    assert not state.is_location_current(LanguageLocation("file:///missing.mdl", range_))
