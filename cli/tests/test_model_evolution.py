"""Add-only exact-base model version evolution (evolution plan D1).

`entity Foo @ N (kind) evolves @ base { add ... }` normalizes into a
complete ModelVersion -- a deep copy of the base version's fields with the
`add` operations appended in order -- before semantic validation, signatures,
or codegen ever see it. These tests prove: the base-resolution rules (highest
existing lower version, no branching/forward/wrong-kind/missing-base), and
that the add-only form is indistinguishable from an equivalent hand-written
complete form at every downstream boundary.
"""

from __future__ import annotations

from pathlib import Path

from modelable.compiler.workspace import WorkspaceDocumentSource, load_workspace_from_sources
from modelable.emitters.rust import emit_rust
from modelable.registry.signature import compute_version_signature


def _workspace(source: str):
    return load_workspace_from_sources([WorkspaceDocumentSource(path=Path("a.mdl"), uri="file:///a.mdl", text=source)])


def test_add_only_evolution_expands_into_a_complete_model_version():
    source = """
domain orders {
  owner: "orders-team"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    total: decimal(10, 2)
  }
  entity Order @ 2 (additive) evolves @ 1 {
    add note?: string
  }
}
"""
    workspace = _workspace(source)

    assert not workspace.errors
    versions = workspace.mdl.domains[0].models["Order"]
    assert [v.version for v in versions] == [1, 2]
    expanded = versions[1]
    assert [f.name for f in expanded.fields] == ["orderId", "total", "note"]
    assert expanded.has_version_header is True
    assert expanded.change_kind.value == "additive"


def test_add_only_and_full_forms_produce_identical_fields_and_signature():
    full_source = """
domain orders {
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
    delta_source = """
domain orders {
  owner: "orders-team"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    total: decimal(10, 2)
  }
  entity Order @ 2 (additive) evolves @ 1 {
    add note?: string
  }
}
"""
    full_ws = _workspace(full_source)
    delta_ws = _workspace(delta_source)
    assert not full_ws.errors
    assert not delta_ws.errors

    full_v2 = next(v for v in full_ws.mdl.domains[0].models["Order"] if v.version == 2)
    delta_v2 = next(v for v in delta_ws.mdl.domains[0].models["Order"] if v.version == 2)

    assert full_v2.fields == delta_v2.fields
    assert compute_version_signature("orders", "Order", full_v2) == compute_version_signature(
        "orders", "Order", delta_v2
    )


def test_add_only_and_full_forms_produce_identical_rust_output(tmp_path):
    full_source = """
domain orders {
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
    delta_source = full_source.replace(
        """  entity Order @ 2 (additive) {
    @key orderId: uuid
    total: decimal(10, 2)
    note?: string
  }""",
        """  entity Order @ 2 (additive) evolves @ 1 {
    add note?: string
  }""",
    )
    full_ws = _workspace(full_source)
    delta_ws = _workspace(delta_source)

    full_artifacts = {a.ref: a.content for a in emit_rust(full_ws, tmp_path / "full")}
    delta_artifacts = {a.ref: a.content for a in emit_rust(delta_ws, tmp_path / "delta")}

    assert full_artifacts["orders.Order@2"] == delta_artifacts["orders.Order@2"]


def test_evolves_rejects_first_version_with_no_prior_base():
    source = """
domain orders {
  owner: "orders-team"
  entity Order @ 2 (additive) evolves @ 1 {
    add note?: string
  }
}
"""
    workspace = _workspace(source)

    assert any("no prior version" in e.message for e in workspace.errors)


def test_evolves_rejects_branching_from_a_superseded_version():
    source = """
domain orders {
  owner: "orders-team"
  entity Order @ 1 (additive) { @key orderId: uuid }
  entity Order @ 2 (additive) { @key orderId: uuid note2?: string }
  entity Order @ 3 (additive) evolves @ 1 {
    add note?: string
  }
}
"""
    workspace = _workspace(source)

    assert any("cannot branch from a superseded version" in e.message for e in workspace.errors)


def test_evolves_rejects_a_forward_or_missing_base():
    source = """
domain orders {
  owner: "orders-team"
  entity Order @ 3 (additive) { @key orderId: uuid }
  entity Order @ 2 (additive) evolves @ 1 {
    add note?: string
  }
}
"""
    workspace = _workspace(source)

    assert any("is not before version" in e.message for e in workspace.errors)


def test_evolves_rejects_a_kind_mismatch_against_the_base():
    source = """
domain orders {
  owner: "orders-team"
  entity Order @ 1 (additive) { @key orderId: uuid }
  value Order @ 2 (additive) evolves @ 1 {
    add note?: string
  }
}
"""
    workspace = _workspace(source)

    assert any("is a entity, but this declaration is value" in e.message for e in workspace.errors)


def test_evolves_rejects_a_duplicate_field_on_add():
    source = """
domain orders {
  owner: "orders-team"
  entity Order @ 1 (additive) { @key orderId: uuid }
  entity Order @ 2 (additive) evolves @ 1 {
    add orderId?: string
  }
}
"""
    workspace = _workspace(source)

    assert any("duplicate field 'orderId'" in e.message for e in workspace.errors)


def test_evolves_still_classifies_breaking_changes_against_an_additive_declaration():
    source = """
domain orders {
  owner: "orders-team"
  entity Order @ 1 (additive) { @key orderId: uuid }
  entity Order @ 2 (additive) evolves @ 1 {
    add note: string
  }
}
"""
    workspace = _workspace(source)

    assert any(
        "additive declaration includes incompatible changes" in e.message and "note" in e.message
        for e in workspace.errors
    )


def test_evolves_allows_numeric_gaps_between_base_and_new_version():
    source = """
domain orders {
  owner: "orders-team"
  entity Order @ 1 (additive) { @key orderId: uuid }
  entity Order @ 5 (additive) evolves @ 1 {
    add note?: string
  }
}
"""
    workspace = _workspace(source)

    assert not workspace.errors
    versions = {v.version for v in workspace.mdl.domains[0].models["Order"]}
    assert versions == {1, 5}
