"""Expand/compact tooling for version deltas (evolution plan A2): converting
between an evolves-form and a full-form declaration of the same model
version, with a proven equivalence gate -- every implemented codegen
target's output must be byte-identical, or the tool aborts rather than
silently changing generated output."""

from __future__ import annotations

from pathlib import Path

from modelable.compiler.version_delta import compute_delta_operations
from modelable.compiler.workspace import WorkspaceDocumentSource, load_workspace, load_workspace_from_sources
from modelable.refactor.compact_version import CompactVersionError, apply_compact_version, compact_version
from modelable.refactor.expand_version import ExpandVersionError, apply_expand_version, expand_version


def _write(tmp_path: Path, text: str) -> Path:
    source = tmp_path / "a.mdl"
    source.write_text(text, encoding="utf-8")
    return source


def _workspace(source: str):
    return load_workspace_from_sources([WorkspaceDocumentSource(path=Path("a.mdl"), uri="file:///a.mdl", text=source)])


# -- compute_delta_operations (compiler-owned diff) --------------------------


def test_no_evidence_keeps_remove_and_add_separate() -> None:
    source = """
domain orders {
  owner: "orders-team"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    total: decimal(10, 2)
  }
  entity Order @ 2 (breaking) {
    @key orderId: uuid
    amount: decimal(12, 2)
  }
}
"""
    workspace = _workspace(source)
    assert not workspace.errors
    domain = workspace.mdl.domains[0]
    v1 = next(v for v in domain.models["Order"] if v.version == 1)
    v2 = next(v for v in domain.models["Order"] if v.version == 2)

    ops = compute_delta_operations(v1, v2)

    assert ops is not None
    assert [op.kind for op in ops] == ["remove", "add"]


def test_deprecated_replaced_by_evidence_produces_rename() -> None:
    source = """
domain orders {
  owner: "orders-team"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    @deprecated(replacedBy: "amount")
    total: decimal(10, 2)
  }
  entity Order @ 2 (breaking) {
    @key orderId: uuid
    amount: decimal(12, 2)
  }
}
"""
    workspace = _workspace(source)
    assert not workspace.errors
    domain = workspace.mdl.domains[0]
    v1 = next(v for v in domain.models["Order"] if v.version == 1)
    v2 = next(v for v in domain.models["Order"] if v.version == 2)

    ops = compute_delta_operations(v1, v2)

    assert ops is not None
    assert [op.kind for op in ops] == ["rename", "replace"]
    assert ops[0].old_name == "total"
    assert ops[0].new_name == "amount"


def test_field_reorder_returns_none() -> None:
    source = """
domain orders {
  owner: "orders-team"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    total: decimal(10, 2)
  }
  entity Order @ 2 (additive) {
    @key orderId: uuid
    note?: string
    total: decimal(10, 2)
  }
}
"""
    workspace = _workspace(source)
    assert not workspace.errors
    domain = workspace.mdl.domains[0]
    v1 = next(v for v in domain.models["Order"] if v.version == 1)
    v2 = next(v for v in domain.models["Order"] if v.version == 2)

    assert compute_delta_operations(v1, v2) is None


# -- expand_version -----------------------------------------------------------


_EVOLVES_SOURCE = """domain orders {
  owner: "orders-team"

  entity Order @ 1 (additive) {
    @key orderId: uuid
    total: decimal(10, 2)
    legacyNote: string
  }
  entity Order @ 2 (breaking) evolves @ 1 {
    remove legacyNote
    rename total -> amount
    replace amount: decimal(12, 2)
    add note?: string
  }
}
"""


def test_expand_renders_the_complete_declaration(tmp_path: Path) -> None:
    _write(tmp_path, _EVOLVES_SOURCE)

    result = expand_version(tmp_path, "orders", "Order", 2)

    assert "entity Order @ 2 (breaking) {" in result.diff_text
    assert "amount: decimal(12, 2)" in result.diff_text
    assert "note?: string" in result.diff_text


def test_apply_expand_writes_and_reloads_cleanly(tmp_path: Path) -> None:
    _write(tmp_path, _EVOLVES_SOURCE)

    apply_expand_version(tmp_path, "orders", "Order", 2)

    text = (tmp_path / "a.mdl").read_text(encoding="utf-8")
    assert "evolves" not in text
    assert "amount: decimal(12, 2)" in text
    assert "note?: string" in text

    reloaded = load_workspace(tmp_path)
    assert not reloaded.errors
    assert not reloaded.warnings


def test_expand_already_full_form_is_rejected(tmp_path: Path) -> None:
    _write(tmp_path, _EVOLVES_SOURCE)

    try:
        expand_version(tmp_path, "orders", "Order", 1)
    except ExpandVersionError as error:
        assert "nothing to expand" in str(error)
    else:
        raise AssertionError("expected ExpandVersionError")


def test_expand_aborts_on_comment_in_evolves_block(tmp_path: Path) -> None:
    source = _EVOLVES_SOURCE.replace("remove legacyNote", "// dropping legacy field\n    remove legacyNote")
    _write(tmp_path, source)

    try:
        expand_version(tmp_path, "orders", "Order", 2)
    except ExpandVersionError as error:
        assert "comment" in str(error)
    else:
        raise AssertionError("expected ExpandVersionError")


# -- compact_version -----------------------------------------------------------


_FULL_FORM_SOURCE = """domain orders {
  owner: "orders-team"

  entity Order @ 1 (additive) {
    @key orderId: uuid
    total: decimal(10, 2)
  }
  entity Order @ 2 (additive) {
    @key orderId: uuid
    total: decimal(10, 2)
    note?: string
  }
}
"""


def test_compact_renders_the_evolves_form(tmp_path: Path) -> None:
    _write(tmp_path, _FULL_FORM_SOURCE)

    result = compact_version(tmp_path, "orders", "Order", 2)

    assert result.base_version == 1
    assert [op.kind for op in result.operations] == ["add"]
    assert "evolves @ 1" in result.diff_text
    assert "add note?: string" in result.diff_text


def test_apply_compact_writes_and_reloads_cleanly(tmp_path: Path) -> None:
    _write(tmp_path, _FULL_FORM_SOURCE)

    apply_compact_version(tmp_path, "orders", "Order", 2)

    text = (tmp_path / "a.mdl").read_text(encoding="utf-8")
    assert "evolves @ 1" in text
    assert "add note?: string" in text

    reloaded = load_workspace(tmp_path)
    assert not reloaded.errors
    assert not reloaded.warnings


def test_compact_round_trips_through_expand_byte_identical(tmp_path: Path) -> None:
    """Compacting then expanding back must reproduce the exact original
    full-form declaration -- the whole point of the equivalence gate."""
    _write(tmp_path, _FULL_FORM_SOURCE)
    original_text = (tmp_path / "a.mdl").read_text(encoding="utf-8")

    apply_compact_version(tmp_path, "orders", "Order", 2)
    apply_expand_version(tmp_path, "orders", "Order", 2)

    assert (tmp_path / "a.mdl").read_text(encoding="utf-8") == original_text


def test_compact_already_evolves_form_is_rejected(tmp_path: Path) -> None:
    _write(tmp_path, _EVOLVES_SOURCE)

    try:
        compact_version(tmp_path, "orders", "Order", 2)
    except CompactVersionError as error:
        assert "nothing to compact" in str(error)
    else:
        raise AssertionError("expected CompactVersionError")


def test_compact_with_no_prior_version_is_rejected(tmp_path: Path) -> None:
    _write(tmp_path, _FULL_FORM_SOURCE)

    try:
        compact_version(tmp_path, "orders", "Order", 1)
    except CompactVersionError as error:
        assert "no prior version" in str(error)
    else:
        raise AssertionError("expected CompactVersionError")


def test_compact_aborts_on_field_reorder(tmp_path: Path) -> None:
    source = """domain orders {
  owner: "orders-team"

  entity Order @ 1 (additive) {
    @key orderId: uuid
    total: decimal(10, 2)
  }
  entity Order @ 2 (additive) {
    @key orderId: uuid
    note?: string
    total: decimal(10, 2)
  }
}
"""
    _write(tmp_path, source)

    try:
        compact_version(tmp_path, "orders", "Order", 2)
    except CompactVersionError as error:
        assert "reordering" in str(error)
    else:
        raise AssertionError("expected CompactVersionError")


def test_compact_aborts_on_comment_in_field_block(tmp_path: Path) -> None:
    source = _FULL_FORM_SOURCE.replace("note?: string", "// user-facing note\n    note?: string")
    _write(tmp_path, source)

    try:
        compact_version(tmp_path, "orders", "Order", 2)
    except CompactVersionError as error:
        assert "comment" in str(error)
    else:
        raise AssertionError("expected CompactVersionError")


def test_compact_aborts_when_access_would_be_silently_dropped(tmp_path: Path) -> None:
    source = """domain orders {
  owner: "orders-team"

  entity Order @ 1 (additive) {
    access {
      entity team-a [read]
    }
    @key orderId: uuid
    total: decimal(10, 2)
  }
  entity Order @ 2 (breaking) {
    @key orderId: uuid
    total: decimal(10, 2)
    note?: string
  }
}
"""
    _write(tmp_path, source)

    try:
        compact_version(tmp_path, "orders", "Order", 2)
    except CompactVersionError as error:
        assert "model-level metadata" in str(error)
    else:
        raise AssertionError("expected CompactVersionError")


def test_compact_apply_rolls_back_on_reload_failure(tmp_path: Path, monkeypatch) -> None:
    import modelable.refactor.compact_version as compact_version_module

    _write(tmp_path, _FULL_FORM_SOURCE)
    original_text = (tmp_path / "a.mdl").read_text(encoding="utf-8")
    real_load_workspace = compact_version_module.load_workspace
    call_count = {"n": 0}

    def _fails_on_second_call(path):
        call_count["n"] += 1
        if call_count["n"] >= 2:
            raise RuntimeError("simulated reload failure")
        return real_load_workspace(path)

    monkeypatch.setattr(compact_version_module, "load_workspace", _fails_on_second_call)

    try:
        apply_compact_version(tmp_path, "orders", "Order", 2)
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected the simulated failure to propagate")

    assert (tmp_path / "a.mdl").read_text(encoding="utf-8") == original_text
