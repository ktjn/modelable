"""Explicit enum extraction (evolution plan A1, instruction #2's direct-
reference case): converts identically-shaped `enum(...)` field occurrences
into references to a new shared `semantic` enum declaration."""

from __future__ import annotations

from pathlib import Path

from modelable.compiler.workspace import load_workspace
from modelable.refactor.extract_enum import (
    ExtractEnumError,
    ExtractEnumPlan,
    apply_extract_enum,
    extract_enum,
    parse_field_location,
)


def _write(tmp_path: Path, text: str) -> Path:
    source = tmp_path / "a.mdl"
    source.write_text(text, encoding="utf-8")
    return source


_TWO_FIELD_SOURCE = """domain orders {
  owner: "orders-team"

  entity Order @ 1 (additive) {
    @key orderId: uuid
    status: enum(active, blocked, deleted)
  }

  entity OrderHistory @ 1 (additive) {
    @key historyId: uuid
    previousStatus: enum(deleted, blocked, active)
  }
}
"""


def test_extract_enum_preview_rewrites_both_fields_and_inserts_the_declaration(tmp_path: Path) -> None:
    _write(tmp_path, _TWO_FIELD_SOURCE)
    plan = ExtractEnumPlan(
        canonical_name="OrderStatus",
        owning_domain="orders",
        change_kind="additive",
        fields=(
            parse_field_location("orders.Order@1.status"),
            parse_field_location("orders.OrderHistory@1.previousStatus"),
        ),
    )

    result = extract_enum(tmp_path, plan)

    assert result.canonical_members == ("active", "blocked", "deleted")
    assert result.written_paths == (tmp_path / "a.mdl",)
    assert (tmp_path / "a.mdl").read_text(encoding="utf-8") == _TWO_FIELD_SOURCE  # preview does not write
    assert "semantic OrderStatus @ 1 (additive): enum(active, blocked, deleted)" in result.diff_text
    assert "status: OrderStatus @ 1" in result.diff_text
    assert "previousStatus: OrderStatus @ 1" in result.diff_text


def test_apply_writes_files_and_reloads_cleanly(tmp_path: Path) -> None:
    _write(tmp_path, _TWO_FIELD_SOURCE)
    plan = ExtractEnumPlan(
        canonical_name="OrderStatus",
        owning_domain="orders",
        change_kind="additive",
        fields=(
            parse_field_location("orders.Order@1.status"),
            parse_field_location("orders.OrderHistory@1.previousStatus"),
        ),
    )

    apply_extract_enum(tmp_path, plan)

    text = (tmp_path / "a.mdl").read_text(encoding="utf-8")
    assert "semantic OrderStatus @ 1 (additive): enum(active, blocked, deleted)" in text
    assert "status: OrderStatus @ 1" in text
    assert "previousStatus: OrderStatus @ 1" in text

    reloaded = load_workspace(tmp_path)
    assert not reloaded.errors
    assert not reloaded.warnings  # the ENUMSHAPE finding this extraction resolves is gone


def test_preserves_standalone_and_trailing_comments(tmp_path: Path) -> None:
    source = """domain orders {
  owner: "orders-team"

  entity Order @ 1 (additive) {
    @key orderId: uuid
    // status enum documenting lifecycle
    status: enum(active, blocked, deleted) // inline trailing note
  }

  entity OrderHistory @ 1 (additive) {
    @key historyId: uuid
    previousStatus: enum(deleted, blocked, active)
  }
}
"""
    _write(tmp_path, source)
    plan = ExtractEnumPlan(
        canonical_name="OrderStatus",
        owning_domain="orders",
        change_kind="additive",
        fields=(
            parse_field_location("orders.Order@1.status"),
            parse_field_location("orders.OrderHistory@1.previousStatus"),
        ),
    )

    result = extract_enum(tmp_path, plan)

    assert "// status enum documenting lifecycle" in result.diff_text
    assert "status: OrderStatus @ 1 // inline trailing note" in result.diff_text


def test_mismatched_member_sets_are_rejected(tmp_path: Path) -> None:
    source = """domain orders {
  owner: "orders-team"

  entity Order @ 1 (additive) {
    @key orderId: uuid
    status: enum(active, blocked, deleted)
  }

  entity Widget @ 1 (additive) {
    @key widgetId: uuid
    color: enum(red, green, blue)
  }
}
"""
    _write(tmp_path, source)
    plan = ExtractEnumPlan(
        canonical_name="X",
        owning_domain="orders",
        change_kind="additive",
        fields=(parse_field_location("orders.Order@1.status"), parse_field_location("orders.Widget@1.color")),
    )

    try:
        extract_enum(tmp_path, plan)
    except ExtractEnumError as error:
        assert "do not all share the same member set" in str(error)
    else:
        raise AssertionError("expected ExtractEnumError")


def test_evolves_declared_version_is_rejected(tmp_path: Path) -> None:
    source = """domain orders {
  owner: "orders-team"

  entity Order @ 1 (additive) {
    @key orderId: uuid
    status: enum(active, blocked, deleted)
  }
  entity Order @ 2 (additive) evolves @ 1 {
    add note?: string
  }

  entity Other @ 1 (additive) {
    @key otherId: uuid
    status: enum(active, blocked, deleted)
  }
}
"""
    _write(tmp_path, source)
    plan = ExtractEnumPlan(
        canonical_name="OrderStatus",
        owning_domain="orders",
        change_kind="additive",
        fields=(parse_field_location("orders.Order@2.status"), parse_field_location("orders.Other@1.status")),
    )

    try:
        extract_enum(tmp_path, plan)
    except ExtractEnumError as error:
        assert "evolves" in str(error)
    else:
        raise AssertionError("expected ExtractEnumError")


def test_non_enum_field_is_rejected(tmp_path: Path) -> None:
    _write(tmp_path, _TWO_FIELD_SOURCE)
    plan = ExtractEnumPlan(
        canonical_name="X",
        owning_domain="orders",
        change_kind="additive",
        fields=(
            parse_field_location("orders.Order@1.orderId"),
            parse_field_location("orders.OrderHistory@1.historyId"),
        ),
    )

    try:
        extract_enum(tmp_path, plan)
    except ExtractEnumError as error:
        assert "not an anonymous enum" in str(error)
    else:
        raise AssertionError("expected ExtractEnumError")


def test_unknown_owning_domain_is_rejected(tmp_path: Path) -> None:
    _write(tmp_path, _TWO_FIELD_SOURCE)
    plan = ExtractEnumPlan(
        canonical_name="X",
        owning_domain="nope",
        change_kind="additive",
        fields=(
            parse_field_location("orders.Order@1.status"),
            parse_field_location("orders.OrderHistory@1.previousStatus"),
        ),
    )

    try:
        extract_enum(tmp_path, plan)
    except ExtractEnumError as error:
        assert "domain 'nope' not found" in str(error)
    else:
        raise AssertionError("expected ExtractEnumError")


def test_name_collision_with_existing_declaration_is_rejected(tmp_path: Path) -> None:
    source = """domain orders {
  owner: "orders-team"

  value OrderStatus @ 1 (additive) {
    label: string
  }

  entity Order @ 1 (additive) {
    @key orderId: uuid
    status: enum(active, blocked, deleted)
  }

  entity OrderHistory @ 1 (additive) {
    @key historyId: uuid
    previousStatus: enum(deleted, blocked, active)
  }
}
"""
    _write(tmp_path, source)
    plan = ExtractEnumPlan(
        canonical_name="OrderStatus",
        owning_domain="orders",
        change_kind="additive",
        fields=(
            parse_field_location("orders.Order@1.status"),
            parse_field_location("orders.OrderHistory@1.previousStatus"),
        ),
    )

    try:
        extract_enum(tmp_path, plan)
    except ExtractEnumError as error:
        assert "already exists" in str(error)
    else:
        raise AssertionError("expected ExtractEnumError")


def test_fewer_than_two_fields_is_rejected(tmp_path: Path) -> None:
    _write(tmp_path, _TWO_FIELD_SOURCE)
    plan = ExtractEnumPlan(
        canonical_name="OrderStatus",
        owning_domain="orders",
        change_kind="additive",
        fields=(parse_field_location("orders.Order@1.status"),),
    )

    try:
        extract_enum(tmp_path, plan)
    except ExtractEnumError as error:
        assert "at least two" in str(error)
    else:
        raise AssertionError("expected ExtractEnumError")


def test_duplicate_field_selection_is_rejected(tmp_path: Path) -> None:
    _write(tmp_path, _TWO_FIELD_SOURCE)
    plan = ExtractEnumPlan(
        canonical_name="OrderStatus",
        owning_domain="orders",
        change_kind="additive",
        fields=(parse_field_location("orders.Order@1.status"), parse_field_location("orders.Order@1.status")),
    )

    try:
        extract_enum(tmp_path, plan)
    except ExtractEnumError as error:
        assert "duplicate field selection" in str(error)
    else:
        raise AssertionError("expected ExtractEnumError")


def test_nested_object_field_location_is_rejected() -> None:
    try:
        parse_field_location("orders.Order@1.shipping.status")
    except ExtractEnumError as error:
        assert "nested object fields" in str(error)
    else:
        raise AssertionError("expected ExtractEnumError")


def test_apply_rolls_back_on_reload_failure(tmp_path: Path, monkeypatch) -> None:
    """If something goes wrong between writing and reload-validating, the
    original file content must be restored -- not left half-edited."""
    import modelable.refactor.extract_enum as extract_enum_module

    _write(tmp_path, _TWO_FIELD_SOURCE)
    original_text = (tmp_path / "a.mdl").read_text(encoding="utf-8")
    plan = ExtractEnumPlan(
        canonical_name="OrderStatus",
        owning_domain="orders",
        change_kind="additive",
        fields=(
            parse_field_location("orders.Order@1.status"),
            parse_field_location("orders.OrderHistory@1.previousStatus"),
        ),
    )

    real_load_workspace = extract_enum_module.load_workspace
    call_count = {"n": 0}

    def _fails_on_second_call(path):
        call_count["n"] += 1
        if call_count["n"] >= 2:
            raise RuntimeError("simulated reload failure")
        return real_load_workspace(path)

    monkeypatch.setattr(extract_enum_module, "load_workspace", _fails_on_second_call)

    try:
        apply_extract_enum(tmp_path, plan)
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected the simulated failure to propagate")

    assert (tmp_path / "a.mdl").read_text(encoding="utf-8") == original_text
