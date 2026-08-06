"""Tests for projection `pick(...)`/`omit(...)` clauses (Slice H1).

Design: docs/superpowers/specs/2026-08-03-projection-pick-omit-design.md
"""

from __future__ import annotations

from pathlib import Path

import pytest

from modelable.compat.checker import check_projection_version_compatibility
from modelable.compiler.render import render_mdl
from modelable.compiler.workspace import load_workspace
from modelable.dependency_graph import build_projection_dependencies
from modelable.parser.ir import ParseError
from modelable.parser.parse import parse_text_to_ir
from modelable.planner.planner import expand_projection_selections
from modelable.registry.signature import compute_version_signature


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _expanded_fields(mdl_text: str, projection_name: str = "BillingCustomer"):
    mdl = parse_text_to_ir(mdl_text)
    errors = expand_projection_selections(mdl)
    assert errors == [], errors
    return mdl.domains[0].projections[projection_name][0].fields


def test_unqualified_pick_single_source():
    fields = _expanded_fields(
        """
        domain billing {
          owner: "test-team"
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            legalName: string
            email: string
          }
          projection BillingCustomer @ 1
            from billing.Customer @ 1 as c
            pick(customerId, legalName)
          { }
        }
        """
    )
    names = [f.name for f in fields]
    assert names == ["customerId", "legalName"]
    assert fields[0].mapping.source_alias == "c"
    assert fields[0].mapping.source_field == "customerId"


def test_unqualified_omit_single_source():
    fields = _expanded_fields(
        """
        domain billing {
          owner: "test-team"
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            legalName: string
            @pii phoneNumber?: string
          }
          projection BillingCustomer @ 1
            from billing.Customer @ 1 as c
            omit(phoneNumber)
          { }
        }
        """
    )
    names = {f.name for f in fields}
    assert names == {"customerId", "legalName"}


def test_qualified_pick_across_join():
    fields = _expanded_fields(
        """
        domain billing {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            customerId: uuid
          }
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            legalName: string
          }
          projection BillingCustomer @ 1
            from billing.Order @ 1 as o
            join billing.Customer @ 1 as c on o.customerId == c.customerId
            pick(o.orderId, c.legalName)
          { }
        }
        """
    )
    assert [(f.name, f.mapping.source_alias) for f in fields] == [
        ("orderId", "o"),
        ("legalName", "c"),
    ]


def test_qualified_omit_across_join():
    fields = _expanded_fields(
        """
        domain billing {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            customerId: uuid
          }
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            @pii phoneNumber?: string
            legalName: string
          }
          projection BillingCustomer @ 1
            from billing.Order @ 1 as o
            join billing.Customer @ 1 as c on o.customerId == c.customerId
            omit(o.customerId, c.customerId, c.phoneNumber)
          { }
        }
        """
    )
    names = {f.name for f in fields}
    assert names == {"orderId", "legalName"}


def test_annotation_filter_pick_matches_across_sources():
    fields = _expanded_fields(
        """
        domain billing {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            @pii shippingAddress: string
          }
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            @pii email: string
            legalName: string
          }
          projection BillingCustomer @ 1
            from billing.Order @ 1 as o
            join billing.Customer @ 1 as c on true
            pick(@pii)
          { }
        }
        """
    )
    names = {f.name for f in fields}
    assert names == {"shippingAddress", "email"}
    assert all(f.is_pii for f in fields)


def test_annotation_filter_omit():
    fields = _expanded_fields(
        """
        domain billing {
          owner: "test-team"
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            @classification("secret") ssn: string
            legalName: string
          }
          projection BillingCustomer @ 1
            from billing.Customer @ 1 as c
            omit(@classification("secret"))
          { }
        }
        """
    )
    names = {f.name for f in fields}
    assert names == {"customerId", "legalName"}


def test_combined_field_name_and_annotation_selectors():
    fields = _expanded_fields(
        """
        domain billing {
          owner: "test-team"
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            legalName: string
            @pii email: string
          }
          projection BillingCustomer @ 1
            from billing.Customer @ 1 as c
            pick(customerId, @pii)
          { }
        }
        """
    )
    names = {f.name for f in fields}
    assert names == {"customerId", "email"}


def test_body_can_add_computed_field_alongside_pick():
    fields = _expanded_fields(
        """
        domain billing {
          owner: "test-team"
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            status: string
          }
          projection BillingCustomer @ 1
            from billing.Customer @ 1 as c
            pick(customerId)
          {
            isActive = c.status == "active"
          }
        }
        """
    )
    names = [f.name for f in fields]
    assert names == ["customerId", "isActive"]
    assert fields[1].mapping.kind == "computed"


def test_pick_and_omit_together_is_a_parse_error():
    with pytest.raises(ParseError):
        parse_text_to_ir(
            """
            domain billing {
              owner: "test-team"
              entity Customer @ 1 (additive) { @key customerId: uuid legalName: string }
              projection BillingCustomer @ 1
                from billing.Customer @ 1 as c
                pick(customerId) omit(legalName)
              { }
            }
            """
        )


def test_empty_pick_is_a_parse_error():
    with pytest.raises(ParseError):
        parse_text_to_ir(
            """
            domain billing {
              owner: "test-team"
              entity Customer @ 1 (additive) { @key customerId: uuid }
              projection BillingCustomer @ 1
                from billing.Customer @ 1 as c
                pick()
              { }
            }
            """
        )


def test_error_unknown_field_selector(tmp_path: Path):
    _write(
        tmp_path / "test.mdl",
        """
        domain billing {
          owner: "test-team"
          entity Customer @ 1 (additive) { @key customerId: uuid }
          projection BillingCustomer @ 1
            from billing.Customer @ 1 as c
            pick(customerId, nonExistentField)
          { }
        }
        """,
    )
    workspace = load_workspace(tmp_path)
    messages = [d.message for d in workspace.errors]
    assert any("nonExistentField" in m and "does not resolve to a known field" in m for m in messages)


def test_error_unknown_alias_selector(tmp_path: Path):
    _write(
        tmp_path / "test.mdl",
        """
        domain billing {
          owner: "test-team"
          entity Customer @ 1 (additive) { @key customerId: uuid }
          projection BillingCustomer @ 1
            from billing.Customer @ 1 as c
            pick(bogus.customerId)
          { }
        }
        """,
    )
    workspace = load_workspace(tmp_path)
    messages = [d.message for d in workspace.errors]
    assert any("bogus.customerId" in m for m in messages)


def test_error_body_redeclares_a_picked_field(tmp_path: Path):
    _write(
        tmp_path / "test.mdl",
        """
        domain billing {
          owner: "test-team"
          entity Customer @ 1 (additive) { @key customerId: uuid legalName: string }
          projection BillingCustomer @ 1
            from billing.Customer @ 1 as c
            pick(customerId, legalName)
          {
            legalName = c.legalName
          }
        }
        """,
    )
    workspace = load_workspace(tmp_path)
    messages = [d.message for d in workspace.errors]
    assert any("legalName" in m and "declared in the projection body" in m for m in messages)


def test_error_ambiguous_unqualified_selector_across_join(tmp_path: Path):
    _write(
        tmp_path / "test.mdl",
        """
        domain billing {
          owner: "test-team"
          entity Order @ 1 (additive) { @key orderId: uuid status: string }
          entity Customer @ 1 (additive) { @key customerId: uuid status: string }
          projection BillingCustomer @ 1
            from billing.Order @ 1 as o
            join billing.Customer @ 1 as c on true
            pick(orderId, status)
          { }
        }
        """,
    )
    workspace = load_workspace(tmp_path)
    messages = [d.message for d in workspace.errors]
    assert any("status" in m and "ambiguous" in m for m in messages)


def test_error_cross_alias_name_collision_in_omit(tmp_path: Path):
    _write(
        tmp_path / "test.mdl",
        """
        domain billing {
          owner: "test-team"
          entity Order @ 1 (additive) { @key orderId: uuid customerId: uuid }
          entity Customer @ 1 (additive) { @key customerId: uuid legalName: string }
          projection BillingCustomer @ 1
            from billing.Order @ 1 as o
            join billing.Customer @ 1 as c on o.customerId == c.customerId
            omit(c.legalName)
          { }
        }
        """,
    )
    workspace = load_workspace(tmp_path)
    messages = [d.message for d in workspace.errors]
    assert any("customerId" in m and "selected from both" in m for m in messages)


def test_formatter_round_trips_the_pick_clause():
    text = (
        "domain billing {\n"
        '  owner: "test-team"\n\n'
        "  entity Customer @ 1 (additive) {\n"
        "    @key customerId: uuid\n"
        "    legalName: string\n"
        "    email: string\n"
        "  }\n\n"
        "  projection BillingCustomer @ 1\n"
        "    from billing.Customer @ 1 as c\n"
        "    pick(customerId, legalName)\n"
        "  {\n"
        '    isBillable = c.email != ""\n'
        "  }\n"
        "}\n"
    )
    mdl = parse_text_to_ir(text)
    rendered = render_mdl(mdl)
    assert "pick(customerId, legalName)" in rendered
    assert rendered == render_mdl(parse_text_to_ir(rendered))


def test_dependency_graph_treats_picked_fields_like_hand_written(tmp_path: Path):
    _write(
        tmp_path / "picked.mdl",
        """
        domain billing {
          owner: "test-team"
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            legalName: string
          }
          projection BillingCustomer @ 1
            from billing.Customer @ 1 as c
            pick(customerId, legalName)
          { }
        }
        """,
    )
    picked_workspace = load_workspace(tmp_path)
    picked_pv = picked_workspace.mdl.domains[0].projections["BillingCustomer"][0]
    picked_deps = build_projection_dependencies(picked_workspace.mdl, "billing", "BillingCustomer", picked_pv)

    hand_path = tmp_path / "picked.mdl"
    _write(
        hand_path,
        """
        domain billing {
          owner: "test-team"
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            legalName: string
          }
          projection BillingCustomer @ 1
            from billing.Customer @ 1 as c
          {
            customerId <- c.customerId
            legalName <- c.legalName
          }
        }
        """,
    )
    hand_workspace = load_workspace(tmp_path)
    hand_pv = hand_workspace.mdl.domains[0].projections["BillingCustomer"][0]
    hand_deps = build_projection_dependencies(hand_workspace.mdl, "billing", "BillingCustomer", hand_pv)

    picked_shape = [(d.target_property, d.usage_kind, d.source_property) for d in picked_deps]
    hand_shape = [(d.target_property, d.usage_kind, d.source_property) for d in hand_deps]
    assert picked_shape == hand_shape


def test_projection_compatibility_treats_pick_expansion_like_hand_written(tmp_path: Path):
    _write(
        tmp_path / "test.mdl",
        """
        domain billing {
          owner: "test-team"
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            legalName: string
            email: string
          }
          projection BillingCustomer @ 1
            from billing.Customer @ 1 as c
          {
            customerId <- c.customerId
            legalName <- c.legalName
          }
          projection BillingCustomer @ 2
            from billing.Customer @ 1 as c
            pick(customerId, legalName, email)
          { }
        }
        """,
    )
    workspace = load_workspace(tmp_path)
    assert workspace.errors == []
    report = check_projection_version_compatibility(workspace.mdl, "billing", "BillingCustomer", 1, 2)
    assert report.status == "compatible"
    assert any(change.kind == "field_added" and change.field_name == "email" for change in report.changes)


def test_canonical_signature_matches_equivalent_hand_written_projection(tmp_path: Path):
    picked_path = tmp_path / "picked.mdl"
    _write(
        picked_path,
        """
        domain billing {
          owner: "test-team"
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            legalName: string
          }
          projection BillingCustomer @ 1
            from billing.Customer @ 1 as c
            pick(customerId, legalName)
          { }
        }
        """,
    )
    picked_workspace = load_workspace(tmp_path)
    picked_pv = picked_workspace.mdl.domains[0].projections["BillingCustomer"][0]
    picked_signature = compute_version_signature("billing", "BillingCustomer", picked_pv)

    _write(
        picked_path,
        """
        domain billing {
          owner: "test-team"
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            legalName: string
          }
          projection BillingCustomer @ 1
            from billing.Customer @ 1 as c
          {
            @key customerId <- c.customerId
            legalName <- c.legalName
          }
        }
        """,
    )
    hand_workspace = load_workspace(tmp_path)
    hand_pv = hand_workspace.mdl.domains[0].projections["BillingCustomer"][0]
    hand_signature = compute_version_signature("billing", "BillingCustomer", hand_pv)

    assert picked_signature == hand_signature
