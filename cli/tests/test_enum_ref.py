"""Round-trip and validation tests for exact versioned semantic-enum
references (evolution plan E1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from modelable.compiler.render import render_mdl
from modelable.compiler.workspace import WorkspaceDocumentSource, load_workspace_from_sources
from modelable.emitters.targets import list_implemented_codegen_targets
from modelable.operations.compilation import (
    CompilationDiagnosticsError,
    _reject_unsupported_enum_projection_fields,
)
from modelable.parser.ir import EnumRefType
from modelable.parser.parse import parse_text_to_ir, parse_text_to_ir_with_tree


def _field_type_of(mdl, domain: str, model: str, field: str):
    d = next(item for item in mdl.domains if item.name == domain)
    return next(f.type for f in d.models[model][0].fields if f.name == field)


SOURCE = """
domain orders {
  owner: "orders-team"

  semantic OrderStatus @ 1 (additive): enum(active, blocked)
  semantic OrderStatus @ 2 (additive): enum(active, blocked, voided)

  entity Order @ 1 (additive) {
    @key orderId: uuid
    status: OrderStatus @ 1
  }

  entity Order @ 2 (breaking) {
    @key orderId: uuid
    status: OrderStatus @ 2
    priorState?: orders.OrderStatus @ 1
    anonymous?: enum(active, blocked)
  }
}

domain shipping {
  owner: "shipping-team"

  semantic ShipmentState @ 1 (additive): enum(active, blocked)

  entity Manifest @ 1 (additive) {
    @key manifestId: uuid
    orderStatus: orders.OrderStatus @ 1
    ownState: ShipmentState @ 1
  }
}
"""


def test_same_domain_exact_enum_reference_parses_and_round_trips():
    mdl = parse_text_to_ir(SOURCE)
    status_type = _field_type_of(mdl, "orders", "Order", "status")
    assert isinstance(status_type, EnumRefType)
    assert status_type.name == "OrderStatus"
    assert status_type.version == 1

    rendered = render_mdl(mdl)
    assert "status: OrderStatus @ 1" in rendered

    reparsed, _tree = parse_text_to_ir_with_tree(rendered)
    assert _field_type_of(reparsed, "orders", "Order", "status") == status_type


def test_cross_domain_qualified_exact_reference_round_trips():
    mdl = parse_text_to_ir(SOURCE)
    ref_type = _field_type_of(mdl, "shipping", "Manifest", "orderStatus")
    assert isinstance(ref_type, EnumRefType)
    assert ref_type.name == "orders.OrderStatus"
    assert ref_type.version == 1

    rendered = render_mdl(mdl)
    assert "orderStatus: orders.OrderStatus @ 1" in rendered

    reparsed, _tree = parse_text_to_ir_with_tree(rendered)
    assert _field_type_of(reparsed, "shipping", "Manifest", "orderStatus") == ref_type


def test_identical_shaped_semantic_enums_remain_distinct():
    workspace = load_workspace_from_sources(
        [WorkspaceDocumentSource(path=Path("a.mdl"), uri="file:///a.mdl", text=SOURCE)]
    )
    assert not [d.message for d in workspace.errors]

    # orders.OrderStatus @ 1 and shipping.ShipmentState @ 1 have identical
    # members but are distinct declarations; both references are valid.
    shipping = next(domain for domain in workspace.mdl.domains if domain.name == "shipping")
    assert shipping.semantic_types[0].underlying.values == ["active", "blocked"]


def test_mixed_anonymous_and_versioned_semantic_enums_coexist():
    workspace = load_workspace_from_sources(
        [WorkspaceDocumentSource(path=Path("a.mdl"), uri="file:///a.mdl", text=SOURCE)]
    )
    assert not [d.message for d in workspace.errors]

    mdl = parse_text_to_ir(SOURCE)
    v2 = next(domain for domain in mdl.domains if domain.name == "orders").models["Order"][1]
    kinds = {field.name: field.type.kind for field in v2.fields}
    assert kinds["anonymous"] == "enum"
    assert kinds["status"] == "enum_ref"


def test_exact_version_mismatch_is_an_enumref_error():
    source = """
domain orders {
  owner: "orders-team"

  semantic OrderStatus @ 1 (additive): enum(active, blocked)

  entity Order @ 1 (additive) {
    @key orderId: uuid
    status: OrderStatus @ 99
  }
}
"""
    workspace = load_workspace_from_sources(
        [WorkspaceDocumentSource(path=Path("a.mdl"), uri="file:///a.mdl", text=source)]
    )
    errors = [d.message for d in workspace.errors]
    assert any(d.code == "ENUMREF" for d in workspace.errors), errors
    assert any("no version 99" in message and "known versions: [1]" in message for message in errors), errors


def test_adding_a_later_declaration_does_not_re_resolve_existing_consumers():
    """E2 item 6: a consumer pinned to OrderStatus @ 1 stays resolved to that
    exact version after OrderStatus @ 2 is declared."""
    workspace = load_workspace_from_sources(
        [WorkspaceDocumentSource(path=Path("a.mdl"), uri="file:///a.mdl", text=SOURCE)]
    )
    errors = [d.message for d in workspace.errors if "OrderStatus" in d.message or "status" in d.message.lower()]
    assert not [message for message in errors if "ENUMREF" in message or "no version" in message], errors

    orders = next(domain for domain in workspace.mdl.domains if domain.name == "orders")
    v1 = next(item for item in orders.models["Order"] if item.version == 1)
    v1_status = next(field for field in v1.fields if field.name == "status").type
    assert isinstance(v1_status, EnumRefType)
    assert v1_status.version == 1


def test_bare_semantic_enum_reference_warns_with_resolved_version():
    source = """
domain orders {
  owner: "orders-team"

  semantic OrderStatus @ 3 (additive): enum(active, blocked)

  entity Order @ 1 (additive) {
    @key orderId: uuid
    status: OrderStatus
  }
}
"""
    workspace = load_workspace_from_sources(
        [WorkspaceDocumentSource(path=Path("a.mdl"), uri="file:///a.mdl", text=source)]
    )

    enum_warnings = [d for d in workspace.warnings if d.code == "ENUMREF" and "status" in d.message]
    assert any(
        "resolves to orders.OrderStatus@3" in d.message and "OrderStatus @ 3" in d.message for d in enum_warnings
    ), [d.message for d in workspace.warnings]
    # Non-blocking: it is a warning, not an error.
    assert not any(d.code == "ENUMREF" and d.severity == "error" for d in workspace.errors)


def test_projection_field_reference_accepts_exact_and_warns_when_bare():
    source = """
domain orders {
  owner: "orders-team"

  semantic OrderStatus @ 1 (additive): enum(pending, paid)
  enum projection PublicStatus @ 1 (additive)
    from OrderStatus @ 1
    pick(paid)

  entity ExactOrder @ 1 (additive) {
    @key orderId: uuid
    status: PublicStatus @ 1
  }
  entity BareOrder @ 1 (additive) {
    @key orderId: uuid
    status: PublicStatus
  }
}
"""
    workspace = load_workspace_from_sources(
        [WorkspaceDocumentSource(path=Path("a.mdl"), uri="file:///a.mdl", text=source)]
    )

    assert not workspace.errors, [d.message for d in workspace.errors]
    assert any("enum projection 'PublicStatus' resolves to" in d.message for d in workspace.warnings)


def test_phase_one_rejects_projection_typed_fields_for_every_codegen_target():
    source = """
domain orders {
  owner: "orders-team"
  semantic Status @ 1 (additive): enum(pending, paid)
  enum projection PublicStatus @ 1 (additive)
    from Status @ 1
    pick(paid)
  entity Order @ 1 (additive) {
    @key orderId: uuid
    status: PublicStatus @ 1
  }
}
"""
    workspace = load_workspace_from_sources(
        [WorkspaceDocumentSource(path=Path("a.mdl"), uri="file:///a.mdl", text=source)]
    )

    for target in (item.name for item in list_implemented_codegen_targets()):
        with pytest.raises(CompilationDiagnosticsError, match=rf"target '{target}'.*EMIT007|target '{target}'"):
            _reject_unsupported_enum_projection_fields(workspace, target)


def test_qualified_missing_version_lists_known_versions():
    source = """
domain orders {
  owner: "orders-team"

  semantic OrderStatus @ 1 (additive): enum(active, blocked)

  entity Order @ 1 (additive) {
    @key orderId: uuid
    status: orders.OrderStatus @ 99
  }
}
"""
    workspace = load_workspace_from_sources(
        [WorkspaceDocumentSource(path=Path("a.mdl"), uri="file:///a.mdl", text=source)]
    )
    errors = [d.message for d in workspace.errors]
    assert any("no version 99" in message and "known versions: [1]" in message for message in errors), errors


def test_cross_domain_bare_reference_missing_version_is_rejected():
    source = """
domain orders {
  owner: "orders-team"

  semantic OrderStatus @ 1 (additive): enum(active, blocked)
}

domain shipping {
  owner: "shipping-team"

  entity Manifest @ 1 (additive) {
    @key manifestId: uuid
    status: ShipmentAlias
  }

  semantic ShipmentAlias @ 1 (additive): enum(active)
}
"""
    # Bare 'OrderStatus' referenced nowhere; instead exercise the workspace-wide
    # fallback missing-version path through an exact reference from another
    # domain where the local domain has no such declaration at that version.
    source = source.replace("status: ShipmentAlias", "orderStatus: orders.OrderStatus @ 7")
    workspace = load_workspace_from_sources(
        [WorkspaceDocumentSource(path=Path("a.mdl"), uri="file:///a.mdl", text=source)]
    )
    errors = [d.message for d in workspace.errors]
    assert any("no version 7" in message and "known versions: [1]" in message for message in errors), errors


def test_non_enum_bare_reference_gets_no_enumref_warning():
    source = """
domain orders {
  owner: "orders-team"

  semantic CustomerId @ 1 (additive): string

  entity Order @ 1 (additive) {
    @key orderId: uuid
    customer: CustomerId
  }
}
"""
    workspace = load_workspace_from_sources(
        [WorkspaceDocumentSource(path=Path("a.mdl"), uri="file:///a.mdl", text=source)]
    )
    assert not [d for d in workspace.warnings if d.code == "ENUMREF"]


def test_non_enum_target_is_an_enumref_error():
    source = """
domain orders {
  owner: "orders-team"

  semantic CustomerId @ 1 (additive): string

  entity Order @ 1 (additive) {
    @key orderId: uuid
    status: CustomerId @ 1
  }
}
"""
    workspace = load_workspace_from_sources(
        [WorkspaceDocumentSource(path=Path("a.mdl"), uri="file:///a.mdl", text=source)]
    )
    errors = [d.message for d in workspace.errors]
    assert any(d.code == "ENUMREF" and "enum-backed" in d.message for d in workspace.errors), errors


def test_unknown_enum_reference_is_an_enumref_error():
    source = """
domain orders {
  owner: "orders-team"

  entity Order @ 1 (additive) {
    @key orderId: uuid
    status: NoSuchStatus @ 1
  }
}
"""
    workspace = load_workspace_from_sources(
        [WorkspaceDocumentSource(path=Path("a.mdl"), uri="file:///a.mdl", text=source)]
    )
    errors = [d.message for d in workspace.errors]
    assert any(d.code == "ENUMREF" for d in workspace.errors), errors


def test_duplicate_semantic_enum_members_are_rejected():
    source = """
domain orders {
  owner: "orders-team"

  semantic Bad @ 1 (additive): enum(active, active)
}
"""
    workspace = load_workspace_from_sources(
        [WorkspaceDocumentSource(path=Path("a.mdl"), uri="file:///a.mdl", text=source)]
    )
    errors = [d.message for d in workspace.errors]
    assert any("Bad" in message and "duplicate enum member 'active'" in message for message in errors), errors
