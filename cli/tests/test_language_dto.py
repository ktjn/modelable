from dataclasses import FrozenInstanceError

import pytest

from modelable.language.dto import (
    LanguageLocation,
    LanguagePosition,
    LanguageRange,
    LanguageTextEdit,
    LanguageWorkspaceEdit,
)


def test_locations_sort_by_uri_then_range() -> None:
    later = LanguageLocation("file:///z.mdl", LanguageRange.at(2, 1, 2, 4))
    earlier = LanguageLocation("file:///a.mdl", LanguageRange.at(9, 0, 9, 1))
    assert sorted((later, earlier)) == [earlier, later]


def test_position_is_immutable() -> None:
    position = LanguagePosition(1, 2)

    with pytest.raises(FrozenInstanceError):
        position.line = 3


def test_workspace_edit_rejects_overlapping_ranges() -> None:
    edits = (
        LanguageTextEdit("file:///a.mdl", LanguageRange.at(0, 0, 0, 4), "A", 2, "hash"),
        LanguageTextEdit("file:///a.mdl", LanguageRange.at(0, 3, 0, 5), "B", 2, "hash"),
    )
    with pytest.raises(ValueError, match="overlap"):
        LanguageWorkspaceEdit.from_edits(edits)


def test_workspace_edit_sorts_ranges_descending_within_each_uri() -> None:
    edits = (
        LanguageTextEdit("file:///z.mdl", LanguageRange.at(0, 0, 0, 1), "Z", 1, "z-hash"),
        LanguageTextEdit("file:///a.mdl", LanguageRange.at(1, 0, 1, 1), "A2", 2, "a-hash"),
        LanguageTextEdit("file:///a.mdl", LanguageRange.at(0, 0, 0, 1), "A1", 2, "a-hash"),
    )

    result = LanguageWorkspaceEdit.from_edits(edits)

    assert [(edit.uri, edit.range.start.line) for edit in result.edits] == [
        ("file:///a.mdl", 1),
        ("file:///a.mdl", 0),
        ("file:///z.mdl", 0),
    ]
    assert result.edits[0].expected_version == 2
    assert result.edits[0].expected_hash == "a-hash"


def test_workspace_edit_rejects_invalid_ranges() -> None:
    invalid_range = LanguageRange(LanguagePosition(1, 0), LanguagePosition(0, 0))
    edit = LanguageTextEdit("file:///a.mdl", invalid_range, "A", 2, "hash")

    with pytest.raises(ValueError, match="end"):
        LanguageWorkspaceEdit.from_edits((edit,))


def test_workspace_edit_constructor_canonicalizes_unsorted_edits() -> None:
    edits = (
        LanguageTextEdit("file:///z.mdl", LanguageRange.at(0, 0, 0, 1), "Z", 1, "z-hash"),
        LanguageTextEdit("file:///a.mdl", LanguageRange.at(0, 0, 0, 1), "A1", 2, "a-hash"),
        LanguageTextEdit("file:///a.mdl", LanguageRange.at(1, 0, 1, 1), "A2", 2, "a-hash"),
    )

    result = LanguageWorkspaceEdit(edits)

    assert [(edit.uri, edit.range.start.line) for edit in result.edits] == [
        ("file:///a.mdl", 1),
        ("file:///a.mdl", 0),
        ("file:///z.mdl", 0),
    ]


def test_workspace_edit_constructor_rejects_overlapping_ranges() -> None:
    edits = (
        LanguageTextEdit("file:///a.mdl", LanguageRange.at(0, 0, 0, 4), "A", 2, "hash"),
        LanguageTextEdit("file:///a.mdl", LanguageRange.at(0, 3, 0, 5), "B", 2, "hash"),
    )

    with pytest.raises(ValueError, match="overlap"):
        LanguageWorkspaceEdit(edits)
