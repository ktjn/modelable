"""Model version evolution: add-only exact-base evolution (D1) plus remove,
rename, replace, and provenance (D2).

`entity Foo @ N (kind) evolves @ base { ... }` normalizes into a complete
ModelVersion -- a deep copy of the base version's fields with operations
applied in order -- before semantic validation, signatures, or codegen ever
see it. These tests prove: the base-resolution rules (highest existing lower
version, no branching/forward/wrong-kind/missing-base), that add/remove/
rename/replace apply deterministically with source-local diagnostics on
invalid sequences, that provenance reflects the last operation to touch each
field, and that an add-only or mixed-operation delta form is indistinguishable
from an equivalent hand-written complete form at every downstream boundary.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from modelable.compiler.workspace import WorkspaceDocumentSource, load_workspace_from_sources
from modelable.emitters.rust import emit_rust
from modelable.parser.ir import AccessGrant, DecimalType, FieldProvenance
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


# -- D2: remove, rename, replace, and provenance -----------------------------


def test_remove_deletes_the_complete_field():
    # Declared (breaking): D2 does not yet feed explicit remove/rename
    # provenance into compatibility classification (compare_model_versions
    # still diffs by field name) -- that wiring is D4's job. Until then, an
    # explicit `remove` is correctly classified the same way a bare deletion
    # would be.
    source = """
domain orders {
  owner: "orders-team"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    legacyNote?: string
  }
  entity Order @ 2 (breaking) evolves @ 1 {
    remove legacyNote
  }
}
"""
    workspace = _workspace(source)

    assert not workspace.errors
    expanded = next(v for v in workspace.mdl.domains[0].models["Order"] if v.version == 2)
    assert [f.name for f in expanded.fields] == ["orderId"]
    assert expanded.provenance == [FieldProvenance(field_name="orderId", origin="inherited")]


def test_rename_retains_field_position_and_definition():
    # Declared (breaking) for the same reason as test_remove_deletes_the_complete_field.
    source = """
domain orders {
  owner: "orders-team"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    total: decimal(10, 2)
    status: string
  }
  entity Order @ 2 (breaking) evolves @ 1 {
    rename total -> amount
  }
}
"""
    workspace = _workspace(source)

    assert not workspace.errors
    expanded = next(v for v in workspace.mdl.domains[0].models["Order"] if v.version == 2)
    assert [f.name for f in expanded.fields] == ["orderId", "amount", "status"]
    assert expanded.fields[1].type == DecimalType(precision=10, scale=2)
    assert expanded.provenance[1] == FieldProvenance(field_name="amount", origin="rename", renamed_from="total")


def test_replace_retains_position_and_replaces_the_complete_definition():
    source = """
domain orders {
  owner: "orders-team"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    total: decimal(10, 2)
    status: string
  }
  entity Order @ 2 (breaking) evolves @ 1 {
    replace total: decimal(12, 4)
  }
}
"""
    workspace = _workspace(source)

    assert not workspace.errors
    expanded = next(v for v in workspace.mdl.domains[0].models["Order"] if v.version == 2)
    assert [f.name for f in expanded.fields] == ["orderId", "total", "status"]
    assert expanded.fields[1].type == DecimalType(precision=12, scale=4)
    assert expanded.provenance[1] == FieldProvenance(field_name="total", origin="replace")


def test_rename_then_replace_leaves_provenance_reflecting_the_last_operation():
    source = """
domain orders {
  owner: "orders-team"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    total: decimal(10, 2)
  }
  entity Order @ 2 (breaking) evolves @ 1 {
    rename total -> amount
    replace amount: decimal(12, 4)
  }
}
"""
    workspace = _workspace(source)

    assert not workspace.errors
    expanded = next(v for v in workspace.mdl.domains[0].models["Order"] if v.version == 2)
    assert [f.name for f in expanded.fields] == ["orderId", "amount"]
    assert expanded.fields[1].type == DecimalType(precision=12, scale=4)
    assert expanded.provenance[1] == FieldProvenance(field_name="amount", origin="replace")


def test_rename_to_its_own_current_name_is_a_no_op():
    source = """
domain orders {
  owner: "orders-team"
  entity Order @ 1 (additive) { @key orderId: uuid }
  entity Order @ 2 (additive) evolves @ 1 {
    rename orderId -> orderId
  }
}
"""
    workspace = _workspace(source)

    assert not workspace.errors
    expanded = next(v for v in workspace.mdl.domains[0].models["Order"] if v.version == 2)
    assert [f.name for f in expanded.fields] == ["orderId"]


def test_add_only_and_full_forms_with_all_four_operations_produce_identical_output(tmp_path):
    full_source = """
domain orders {
  owner: "orders-team"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    total: decimal(10, 2)
    legacyNote: string
  }
  entity Order @ 2 (breaking) {
    @key orderId: uuid
    amount: decimal(12, 2)
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
    legacyNote: string
  }
  entity Order @ 2 (breaking) evolves @ 1 {
    add note?: string
    remove legacyNote
    rename total -> amount
    replace amount: decimal(12, 2)
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

    full_artifacts = {a.ref: a.content for a in emit_rust(full_ws, tmp_path / "full")}
    delta_artifacts = {a.ref: a.content for a in emit_rust(delta_ws, tmp_path / "delta")}
    assert full_artifacts["orders.Order@2"] == delta_artifacts["orders.Order@2"]


@pytest.mark.parametrize(
    ("operation", "expected_error_snippet"),
    [
        ("rename other -> id", "already occupied by another field"),
        ("replace nosuch: string", "does not match any existing field"),
        ("remove nosuch", "unknown field 'nosuch'"),
        ("rename nosuch -> other", "unknown field 'nosuch'"),
    ],
)
def test_invalid_operation_sequences_are_rejected_at_the_failing_operation(operation, expected_error_snippet):
    source = f"""
domain orders {{
  owner: "orders-team"
  entity Order @ 1 (additive) {{ @key id: uuid other: string }}
  entity Order @ 2 (additive) evolves @ 1 {{
    {operation}
  }}
}}
"""
    workspace = _workspace(source)

    assert any(expected_error_snippet in e.message for e in workspace.errors)


def test_repeated_removal_is_rejected_as_an_unknown_field_on_the_second_attempt():
    source = """
domain orders {
  owner: "orders-team"
  entity Order @ 1 (additive) { @key id: uuid other?: string }
  entity Order @ 2 (additive) evolves @ 1 {
    remove other
    remove other
  }
}
"""
    workspace = _workspace(source)

    assert any("unknown field 'other'" in e.message for e in workspace.errors)


# -- D3: model-level metadata inheritance ------------------------------------


def test_omitted_access_and_annotations_are_inherited_from_the_base():
    source = """
domain orders {
  owner: "orders-team"
  @wire(json.fieldCase: "snake_case")
  entity Order @ 1 (additive) {
    access {
      entity team-a [read]
    }
    @key orderId: uuid
  }
  entity Order @ 2 (additive) evolves @ 1 {
    add note?: string
  }
}
"""
    workspace = _workspace(source)

    assert not workspace.errors
    expanded = next(v for v in workspace.mdl.domains[0].models["Order"] if v.version == 2)
    assert len(expanded.annotations) == 1
    assert expanded.annotations[0].targets["json"].field_case == "snake_case"
    assert expanded.access is not None
    assert expanded.access.entity == [AccessGrant(principal="team-a", permissions=["read"])]


def test_present_access_and_annotations_completely_replace_the_base():
    source = """
domain orders {
  owner: "orders-team"
  @wire(json.fieldCase: "snake_case")
  entity Order @ 1 (additive) {
    access {
      entity team-a [read]
    }
    @key orderId: uuid
  }
  @wire(json.fieldCase: "camelCase")
  entity Order @ 2 (breaking) evolves @ 1 {
    access {
      entity team-b [write]
    }
    add note?: string
  }
}
"""
    workspace = _workspace(source)

    assert not workspace.errors
    expanded = next(v for v in workspace.mdl.domains[0].models["Order"] if v.version == 2)
    assert len(expanded.annotations) == 1
    assert expanded.annotations[0].targets["json"].field_case == "camelCase"
    assert expanded.access is not None
    assert expanded.access.entity == [AccessGrant(principal="team-b", permissions=["write"])]


def test_protobuf_reservations_are_version_local_and_never_inherited():
    source = """
domain orders {
  owner: "orders-team"
  entity Order @ 1 (additive) {
    reserved protobuf {
      numbers: [3]
    }
    @key orderId: uuid
  }
  entity Order @ 2 (additive) evolves @ 1 {
    add note?: string
  }
}
"""
    workspace = _workspace(source)

    assert not workspace.errors
    expanded = next(v for v in workspace.mdl.domains[0].models["Order"] if v.version == 2)
    assert expanded.protobuf_reservations is None


def test_protobuf_reservations_present_on_the_evolves_form_are_used_as_is():
    source = """
domain orders {
  owner: "orders-team"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    legacy?: string
  }
  entity Order @ 2 (breaking) evolves @ 1 {
    remove legacy
    reserved protobuf {
      numbers: [2]
      names: ["legacy"]
    }
  }
}
"""
    workspace = _workspace(source)

    assert not workspace.errors
    expanded = next(v for v in workspace.mdl.domains[0].models["Order"] if v.version == 2)
    assert expanded.protobuf_reservations is not None
    assert expanded.protobuf_reservations.numbers == [2]
    assert expanded.protobuf_reservations.names == ["legacy"]


def test_invalid_wire_annotation_on_the_evolves_form_is_still_caught():
    source = """
domain tracing {
  owner: "test-team"
  entity Span @ 1 (additive) {
    @key spanId: string
  }
  @wire(json.fieldCase: "not_a_real_case")
  entity Span @ 2 (additive) evolves @ 1 {
    add note?: string
  }
}
"""
    workspace = _workspace(source)

    assert any("unsupported json.fieldCase" in e.message for e in workspace.errors)


@pytest.mark.parametrize("model_kind", ["entity", "aggregate", "event", "value"])
def test_evolves_is_supported_for_every_model_kind(model_kind):
    key_field = "@key id: uuid" if model_kind in ("entity", "aggregate") else "id: uuid"
    source = f"""
domain orders {{
  owner: "orders-team"
  {model_kind} Item @ 1 (additive) {{
    {key_field}
  }}
  {model_kind} Item @ 2 (additive) evolves @ 1 {{
    add note?: string
  }}
}}
"""
    workspace = _workspace(source)

    assert not workspace.errors
    expanded = next(v for v in workspace.mdl.domains[0].models["Item"] if v.version == 2)
    assert [f.name for f in expanded.fields] == ["id", "note"]
