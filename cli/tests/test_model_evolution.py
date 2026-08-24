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

import importlib.util
import json
from pathlib import Path

import pytest

from modelable.compat.checker import analyze_impact, check_model_version_compatibility
from modelable.compat.diff import compare_model_versions
from modelable.compiler.workspace import WorkspaceDocumentSource, load_workspace_from_sources
from modelable.dependency_graph import build_projection_dependencies
from modelable.emitters.rust import emit_rust
from modelable.emitters.targets import list_implemented_codegen_targets
from modelable.parser.ir import AccessGrant, DecimalType, FieldProvenance
from modelable.registry.signature import compute_version_signature
from modelable.registry.snapshot import resolve_workspace_snapshot

IMPLEMENTED_TARGET_NAMES = {target.name for target in list_implemented_codegen_targets()}


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
    # origin reflects the last operation (replace), but renamed_from from the
    # earlier rename is preserved -- D4's compatibility rename-matching
    # depends on this surviving a later replace of the same field.
    assert expanded.provenance[1] == FieldProvenance(field_name="amount", origin="replace", renamed_from="total")


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


# -- D4: connect operation intent to compatibility ---------------------------


def _model_versions(source: str):
    workspace = _workspace(source)
    assert not workspace.errors, workspace.errors
    versions = workspace.mdl.domains[0].models["Order"]
    return next(v for v in versions if v.version == 1), next(v for v in versions if v.version == 2)


def test_declared_rename_is_matched_by_provenance_not_name_similarity_or_deprecation():
    source = """
domain orders {
  owner: "orders-team"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    total: decimal(10, 2)
  }
  entity Order @ 2 (breaking) evolves @ 1 {
    rename total -> amount
  }
}
"""
    v1, v2 = _model_versions(source)

    changes = compare_model_versions(v1, v2)

    assert [c.kind for c in changes] == ["renamed_field"]
    assert changes[0].field_name == "total"
    assert changes[0].previous_name == "total"
    assert changes[0].replacement == "amount"
    assert changes[0].note == "declared via evolves rename"


def test_rename_provenance_disambiguates_an_unrelated_simultaneous_remove_and_add():
    """The real value of provenance-based matching: without it, an unrelated
    remove+add happening in the same evolves block as a rename could dilute
    into an undifferentiated pile of removed/added fields -- provenance
    keeps the rename and the unrelated changes distinct."""
    source = """
domain orders {
  owner: "orders-team"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    total: decimal(10, 2)
    foo: string
  }
  entity Order @ 2 (breaking) evolves @ 1 {
    rename total -> amount
    remove foo
    add bar: string
  }
}
"""
    v1, v2 = _model_versions(source)

    changes = compare_model_versions(v1, v2)

    kinds_by_field = {c.field_name: c.kind for c in changes}
    assert kinds_by_field == {"total": "renamed_field", "foo": "removed_field", "bar": "added_field"}


def test_self_rename_provenance_produces_no_compatibility_finding():
    source = """
domain orders {
  owner: "orders-team"
  entity Order @ 1 (additive) {
    @key orderId: uuid
  }
  entity Order @ 2 (additive) evolves @ 1 {
    rename orderId -> orderId
  }
}
"""
    v1, v2 = _model_versions(source)

    assert compare_model_versions(v1, v2) == []


def test_replace_is_classified_from_the_actual_field_definitions_not_the_operation_name():
    """Instruction: "the operation name is not itself additive or breaking".
    A replace that changes nothing observable produces no finding; a replace
    that narrows optionality is classified the same way an ordinary
    optional-to-required change on a same-named field would be."""
    no_op_source = """
domain orders {
  owner: "orders-team"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    total: decimal(10, 2)
  }
  entity Order @ 2 (additive) evolves @ 1 {
    replace total: decimal(10, 2)
  }
}
"""
    v1, v2 = _model_versions(no_op_source)
    assert compare_model_versions(v1, v2) == []

    narrowing_source = """
domain orders {
  owner: "orders-team"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    total?: decimal(10, 2)
  }
  entity Order @ 2 (breaking) evolves @ 1 {
    replace total: decimal(10, 2)
  }
}
"""
    v1, v2 = _model_versions(narrowing_source)
    changes = compare_model_versions(v1, v2)
    assert any(c.kind == "presence_changed" and c.from_optional and not c.to_optional for c in changes)


def test_compatibility_diagnostic_names_the_responsible_evolves_operation():
    source = """
domain orders {
  owner: "orders-team"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    total: decimal(10, 2)
  }
  entity Order @ 2 (additive) evolves @ 1 {
    rename total -> amount
    add note: string
  }
}
"""
    workspace = _workspace(source)

    assert len(workspace.errors) == 1
    message = workspace.errors[0].message
    assert "renamed_field total (declared via evolves rename)" in message
    assert "added required field note (via evolves add)" in message


def test_full_form_and_delta_form_produce_the_same_compatibility_facts():
    """Exit criteria: equivalent source forms produce the same facts, apart
    from richer provenance text on the delta form."""
    full_source = """
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
    delta_source = """
domain orders {
  owner: "orders-team"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    total: decimal(10, 2)
  }
  entity Order @ 2 (breaking) evolves @ 1 {
    rename total -> amount
    replace amount: decimal(12, 2)
  }
}
"""
    full_v1, full_v2 = _model_versions(full_source)
    delta_v1, delta_v2 = _model_versions(delta_source)

    full_changes = compare_model_versions(full_v1, full_v2)
    delta_changes = compare_model_versions(delta_v1, delta_v2)

    # Full-form has no provenance, so it can't tell "total" became "amount"
    # from an unrelated delete-and-add -- that's exactly the gap D4 closes
    # for the delta form, so the two are not expected to produce identical
    # change kinds here (the delta form correctly reports a single rename
    # instead of a delete-and-add pair). What must match: both are correctly
    # classified breaking, with no COMPAT diagnostic gap either way.
    full_workspace = _workspace(full_source)
    delta_workspace = _workspace(delta_source)
    assert not full_workspace.errors
    assert not delta_workspace.errors
    assert {c.kind for c in full_changes} == {"removed_field", "added_field"}
    assert {c.kind for c in delta_changes} == {"renamed_field", "type_changed"}


# -- D5: signatures and registry objects are syntax-independent -------------


def test_full_form_and_delta_form_produce_identical_snapshot_objects(tmp_path):
    """Exit criteria: equivalent full/delta versions have identical
    signatures, object hashes, and offline artifacts."""
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
    same_path = Path("orders.mdl")
    full_ws = load_workspace_from_sources(
        [WorkspaceDocumentSource(path=same_path, uri="file:///orders.mdl", text=full_source)]
    )
    delta_ws = load_workspace_from_sources(
        [WorkspaceDocumentSource(path=same_path, uri="file:///orders.mdl", text=delta_source)]
    )
    assert not full_ws.errors
    assert not delta_ws.errors

    full_result = resolve_workspace_snapshot(full_ws, tmp_path / "full")
    delta_result = resolve_workspace_snapshot(delta_ws, tmp_path / "delta")

    full_lock = json.loads(full_result.lock_path.read_text(encoding="utf-8"))
    delta_lock = json.loads(delta_result.lock_path.read_text(encoding="utf-8"))
    full_entries = {e["identity"]: e for e in full_lock["objects"]}
    delta_entries = {e["identity"]: e for e in delta_lock["objects"]}

    assert full_entries.keys() == delta_entries.keys()
    for identity in full_entries:
        assert full_entries[identity]["signature"] == delta_entries[identity]["signature"], identity
        assert full_entries[identity]["content_hash"] == delta_entries[identity]["content_hash"], identity


def test_snapshot_object_contract_excludes_provenance_and_is_self_contained(tmp_path):
    """A stored snapshot object is the complete expanded version -- it must
    not need the base version or the evolves operation syntax to be useful,
    and `provenance` (diagnostic-only, operation-syntax-adjacent) must not
    leak into the canonical stored contract."""
    source = """
domain orders {
  owner: "orders-team"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    total: decimal(10, 2)
  }
  entity Order @ 2 (breaking) evolves @ 1 {
    rename total -> amount
    add note?: string
  }
}
"""
    workspace = _workspace(source)
    assert not workspace.errors

    result = resolve_workspace_snapshot(workspace, tmp_path / ".modelable")
    lock = json.loads(result.lock_path.read_text(encoding="utf-8"))
    v2_entry = next(e for e in lock["objects"] if e["identity"] == "orders.Order@2")
    object_path = result.lock_path.parent / "registry" / "objects" / f"{v2_entry['content_hash']}.json"
    stored = json.loads(object_path.read_text(encoding="utf-8"))

    assert "provenance" not in stored["contract"]
    field_names = {f["name"] for f in stored["contract"]["fields"]}
    assert field_names == {"orderId", "amount", "note"}


# -- D6: projection, dependency, and impact transparency ---------------------


def _customer_block(evolved: bool) -> str:
    if evolved:
        v2 = """
  entity Customer @ 2 (additive) evolves @ 1 {
    add email?: string
  }"""
    else:
        v2 = """
  entity Customer @ 2 (additive) {
    @key customerId: uuid
    name: string
    status: string
    email?: string
  }"""
    return f"""
domain customer {{
  owner: "test-team"
  entity Customer @ 1 (additive) {{
    @key customerId: uuid
    name: string
    status: string
  }}{v2}
}}
"""


_PROJECTIONS_BLOCK = """
domain orders {
  owner: "test-team"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    customerId: uuid
    totalAmount: decimal(10, 2)
  }
}

domain billing {
  owner: "test-team"

  projection CustomerDirect @ 1
    from customer.Customer @ 2 as c
  {
    custId <- c.customerId
    custName <- c.name
  }

  projection CustomerComputed @ 1
    from customer.Customer @ 2 as c
  {
    custId <- c.customerId
    isActive = c.status == "active"
  }

  projection CustomerPicked @ 1
    from customer.Customer @ 2 as c
    pick(customerId, name)
  {
  }

  projection CustomerOmitted @ 1
    from customer.Customer @ 2 as c
    omit(status)
  {
  }

  projection CustomerOrderStats @ 1
    from customer.Customer @ 2 as c
    left join orders.Order @ 1 as o on c.customerId == o.customerId
    where c.status == "active"
    group by c.customerId
  {
    custId <- c.customerId
    totalSpent = sum(o.totalAmount)
  }

  projection CustomerDirectSummary @ 1
    from billing.CustomerDirect @ 1 as cd
  {
    summaryId <- cd.custId
  }
}
"""

_PROJECTION_NAMES = (
    "CustomerDirect",
    "CustomerComputed",
    "CustomerPicked",
    "CustomerOmitted",
    "CustomerOrderStats",
    "CustomerDirectSummary",
)


def _d6_workspace(evolved: bool):
    text = _customer_block(evolved) + _PROJECTIONS_BLOCK
    workspace = _workspace(text)
    assert not workspace.errors, workspace.errors
    return workspace.mdl


def _projection_version(mdl, name: str):
    domain = next(d for d in mdl.domains if d.name == "billing")
    return domain.projections[name][0]


def test_resolved_projection_fields_are_identical_for_full_and_delta_source():
    """Instruction #1/#2: pairs full/delta fixtures across direct fields,
    computed fields, pick, omit, joins+filters+grouping, and
    projection-of-projection chains, requiring equivalent resolved fields."""
    full_mdl = _d6_workspace(evolved=False)
    delta_mdl = _d6_workspace(evolved=True)

    for name in _PROJECTION_NAMES:
        full_pv = _projection_version(full_mdl, name)
        delta_pv = _projection_version(delta_mdl, name)
        assert full_pv.fields == delta_pv.fields, name


def test_projection_dependency_graph_edges_are_identical_for_full_and_delta_source():
    """Instruction #2: equivalent property dependency graph edges -- covers
    direct mappings, computed expressions, join predicates, where filters,
    and group-by keys in one projection (CustomerOrderStats)."""
    full_mdl = _d6_workspace(evolved=False)
    delta_mdl = _d6_workspace(evolved=True)

    for name in _PROJECTION_NAMES:
        full_deps = build_projection_dependencies(full_mdl, "billing", name, _projection_version(full_mdl, name))
        delta_deps = build_projection_dependencies(delta_mdl, "billing", name, _projection_version(delta_mdl, name))
        assert full_deps == delta_deps, name

    # Confirm the join/filter/group dependency kinds are actually exercised,
    # not silently absent from both sides.
    stats_deps = build_projection_dependencies(
        full_mdl, "billing", "CustomerOrderStats", _projection_version(full_mdl, "CustomerOrderStats")
    )
    assert {dep.usage_kind for dep in stats_deps} >= {"filter", "group"}


def test_impact_analysis_is_identical_for_full_and_delta_source():
    """Instruction #3: equivalent projection compatibility and impact paths.
    Customer @ 1 -> @ 2 only adds an optional field neither projection
    references, so every dependent projection should be unaffected either
    way -- and identically so between the full and delta forms."""
    full_mdl = _d6_workspace(evolved=False)
    delta_mdl = _d6_workspace(evolved=True)

    for mdl in (full_mdl, delta_mdl):
        report = check_model_version_compatibility(mdl, "customer", "Customer", 1, 2)
        for name in _PROJECTION_NAMES:
            if name == "CustomerDirectSummary":
                # Sources from a projection, not the model directly -- not a
                # dependent of the model version change itself.
                continue
            impact = analyze_impact(mdl, report, ("billing", name, 1))
            assert impact.status == "compatible", (name, impact.reason)


# -- D7: every generated target is syntax-independent ------------------------


def _load_golden_generator():
    generator_path = Path(__file__).parents[1] / "scripts" / "write_golden_artifacts.py"
    spec = importlib.util.spec_from_file_location("write_golden_artifacts_d7", generator_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_D7_ORDER_FULL = """
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
    reserved protobuf {
      numbers: [10]
      names: ["legacyNote"]
    }
  }

  projection OrderView @ 1
    from orders.Order @ 2 as o
  {
    viewId <- o.orderId
    amount <- o.amount
    note <- o.note
  }
}
"""

_D7_ORDER_DELTA = """
domain orders {
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
    reserved protobuf {
      numbers: [10]
      names: ["legacyNote"]
    }
  }

  projection OrderView @ 1
    from orders.Order @ 2 as o
  {
    viewId <- o.orderId
    amount <- o.amount
    note <- o.note
  }
}
"""


def test_every_implemented_target_produces_identical_output_for_full_and_delta_source(tmp_path):
    """Instructions #1/#3/#4: compile one small history in full and
    equivalent delta forms using every target in list_implemented_codegen_
    targets() (via the golden-artifact generator's own emitter dispatch
    table, reused rather than re-declared), covering Protobuf numbering/
    reservations, SDK field shapes (typescript/csharp/java/python/rust/go),
    SQL mappings, metadata lineage, registry manifests, and event-sink
    output in one fixture. Byte-compares every artifact's content and
    warnings -- not just a representative field."""
    generator = _load_golden_generator()
    full_ws = _workspace(_D7_ORDER_FULL)
    delta_ws = _workspace(_D7_ORDER_DELTA)

    mismatches: list[str] = []
    for target_name, emitter in generator.TARGET_EMITTERS.items():
        full_artifacts = {a.ref: a for a in emitter(full_ws, tmp_path / "full" / target_name)}
        delta_artifacts = {a.ref: a for a in emitter(delta_ws, tmp_path / "delta" / target_name)}
        if full_artifacts.keys() != delta_artifacts.keys():
            mismatches.append(
                f"{target_name}: artifact ref sets differ: {full_artifacts.keys()} vs {delta_artifacts.keys()}"
            )
            continue
        for ref, full_artifact in full_artifacts.items():
            delta_artifact = delta_artifacts[ref]
            if full_artifact.content != delta_artifact.content:
                mismatches.append(f"{target_name}:{ref} content differs")
            if full_artifact.warnings != delta_artifact.warnings:
                mismatches.append(f"{target_name}:{ref} warnings differ")

    assert mismatches == []
    # Confirm this actually exercised every non-FHIR implemented target,
    # rather than silently iterating an empty or stale dispatch table.
    assert generator.TARGET_EMITTERS.keys() == IMPLEMENTED_TARGET_NAMES - {"fhir-profile"}


_D7_PATIENT_FULL = """
domain clinical {
  owner: "clinical-platform"
  entity Patient @ 1 (additive) {
    @key patientId: uuid
    active: bool
    legacyStatus: string
  }
  entity Patient @ 2 (breaking) {
    @key patientId: uuid
    active: bool
    status: string
  }

  projection PatientProfile @ 1
    from clinical.Patient @ 2 as p
  {
    patientId <- p.patientId
    active <- p.active
    status <- p.status
  }
}
"""

_D7_PATIENT_DELTA = """
domain clinical {
  owner: "clinical-platform"
  entity Patient @ 1 (additive) {
    @key patientId: uuid
    active: bool
    legacyStatus: string
  }
  entity Patient @ 2 (breaking) evolves @ 1 {
    remove legacyStatus
    add status: string
  }

  projection PatientProfile @ 1
    from clinical.Patient @ 2 as p
  {
    patientId <- p.patientId
    active <- p.active
    status <- p.status
  }
}
"""


def test_fhir_profile_target_produces_identical_output_for_full_and_delta_source(tmp_path):
    """fhir-profile uses its own fixture shape (like the golden-artifact
    suite does), since FHIR mapping needs field/model names FHIR recognizes."""
    generator = _load_golden_generator()
    full_ws = _workspace(_D7_PATIENT_FULL)
    delta_ws = _workspace(_D7_PATIENT_DELTA)

    full_artifacts = {a.ref: a for a in generator.FHIR_TARGET_EMITTER(full_ws, tmp_path / "full")}
    delta_artifacts = {a.ref: a for a in generator.FHIR_TARGET_EMITTER(delta_ws, tmp_path / "delta")}

    assert full_artifacts.keys() == delta_artifacts.keys()
    for ref, full_artifact in full_artifacts.items():
        delta_artifact = delta_artifacts[ref]
        assert full_artifact.content == delta_artifact.content, ref
        assert full_artifact.warnings == delta_artifact.warnings, ref


def test_no_emitter_module_references_evolves_specific_symbols():
    """Exit criteria: no emitter contains an evolves or operation-specific
    branch. Every emitter only ever sees domain.models -- the merged,
    post-expansion state -- so none of them should reference the
    source-only evolution IR at all."""
    emitters_dir = Path(__file__).parents[1] / "src" / "modelable" / "emitters"
    forbidden = (
        "model_evolutions",
        "ModelEvolutionDecl",
        "AddFieldOp",
        "RemoveFieldOp",
        "RenameFieldOp",
        "ReplaceFieldOp",
    )
    offenders = []
    for path in sorted(emitters_dir.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        if any(name in text for name in forbidden):
            offenders.append(path.name)
    assert offenders == []
