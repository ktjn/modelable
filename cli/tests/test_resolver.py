import json
import sqlite3
from pathlib import Path

from modelable.compiler.workspace import load_workspace
from modelable.identity import DeclarationId, DeclarationReference, DeclarationVersion
from modelable.parser.ir import VersionMin
from modelable.parser.parse import parse_text_to_ir
from modelable.registry.index import build_registry
from modelable.registry.resolver import (
    ResolvedDeclaration,
    ResolvedDeclarationView,
    _iter_declaration_candidates,
    latest_enum_projection_declarations,
    latest_semantic_type_declarations,
    resolve_declaration,
    resolve_model_ref,
)


def _write_workspace(path: Path) -> None:
    path.write_text(
        """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }

  entity Customer @ 2 (additive) {
    @key customerId: uuid
    email?: string
  }

  entity Customer @ 3 (additive) {
    @key customerId: uuid
    email?: string
    status?: string
  }
}

domain billing {
  owner: "test-team"
  projection BillingCustomer @ 1
    from customer.Customer @ >=1 <3 as c
  {
    billingCustomerId <- c.customerId
  }
}
""",
        encoding="utf-8",
    )


def test_declaration_candidate_boundary_covers_all_named_declaration_families():
    mdl = parse_text_to_ir("""
    domain catalog {
      owner: "test-team"
      entity Product @ 1 (additive) { @key productId: uuid }
      projection ProductView @ 1 from catalog.Product @ 1 as product {
        productId <- product.productId
      }
      semantic Status @ 1 (additive): enum(active, retired)
      enum projection PublicStatus @ 1 (additive)
        from Status @ 1
        pick(active)
    }
    """)

    candidates = list(_iter_declaration_candidates(mdl))

    assert [(candidate.name, candidate.kind, candidate.version_number) for candidate in candidates] == [
        ("Product", "model", 1),
        ("ProductView", "projection", 1),
        ("Status", "semantic_type", 1),
        ("PublicStatus", "enum_projection", 1),
    ]


def test_declaration_identity_value_objects_render_canonical_versions() -> None:
    declaration = DeclarationId("catalog", "Product")
    version = DeclarationVersion(declaration, 3)

    assert declaration.render() == "catalog.Product"
    assert version.identity == "catalog.Product@3"
    assert DeclarationVersion.parse(version.identity) == version
    reference = DeclarationReference.parse("catalog.Product@3#email")
    assert reference.declaration == version
    assert reference.render() == "catalog.Product@3#email"


def test_latest_declaration_helpers_share_candidate_version_selection():
    mdl = parse_text_to_ir("""
    domain catalog {
      owner: "test-team"
      semantic Status @ 2 (additive): enum(active, retired)
      semantic Status @ 1 (additive): enum(active)
      semantic Region @ 1 (additive): string
      enum projection PublicStatus @ 2 (additive) from Status @ 2 pick(active)
      enum projection PublicStatus @ 1 (additive) from Status @ 1 pick(active)
    }
    """)
    domain = mdl.domains[0]

    assert [(declaration.name, declaration.version) for declaration in latest_semantic_type_declarations(domain)] == [
        ("Status", 2),
        ("Region", 1),
    ]
    assert [(declaration.name, declaration.version) for declaration in latest_enum_projection_declarations(domain)] == [
        ("PublicStatus", 2),
    ]


def test_resolve_declaration_exposes_one_boundary_for_all_declaration_families():
    mdl = parse_text_to_ir("""
    domain catalog {
      owner: "test-team"
      entity Product @ 1 (additive) { @key productId: uuid }
      value Address @ 1 (additive) { line1: string }
      projection ProductView @ 1 from catalog.Product @ 1 as product {
        productId <- product.productId
      }
      semantic Status @ 1 (additive): enum(active, retired)
      enum projection PublicStatus @ 1 (additive)
        from Status @ 1
        pick(active)
    }
    """)

    resolved = [
        resolve_declaration(mdl, reference, 1)
        for reference in (
            "catalog.Product",
            "catalog.Address",
            "catalog.ProductView",
            "catalog.Status",
            "catalog.PublicStatus",
        )
    ]

    assert [(item.name, item.kind, item.version_number) for item in resolved] == [
        ("Product", "model", 1),
        ("Address", "model", 1),
        ("ProductView", "projection", 1),
        ("Status", "semantic_type", 1),
        ("PublicStatus", "enum_projection", 1),
    ]
    assert [item.identity for item in resolved] == [
        "catalog.Product@1",
        "catalog.Address@1",
        "catalog.ProductView@1",
        "catalog.Status@1",
        "catalog.PublicStatus@1",
    ]
    assert all(isinstance(item, ResolvedDeclarationView) for item in resolved)


def test_resolve_declaration_carries_common_domain_metadata() -> None:
    mdl = parse_text_to_ir(
        """
        domain catalog {
          owner: "catalog-team"
          contact: "catalog@example.invalid"
          description: "Published catalog contracts."
          entity Product @ 1 (additive) { @key productId: uuid }
          semantic Status @ 1 (additive): enum(active)
        }
        """
    )

    resolved = [resolve_declaration(mdl, reference, 1) for reference in ("catalog.Product", "catalog.Status")]

    assert [(item.domain_owner, item.domain_contact, item.domain_description) for item in resolved] == [
        ("catalog-team", "catalog@example.invalid", "Published catalog contracts."),
        ("catalog-team", "catalog@example.invalid", "Published catalog contracts."),
    ]


def test_resolved_declaration_exposes_normalized_members() -> None:
    mdl = parse_text_to_ir(
        """
        domain catalog {
          owner: "catalog-team"
          entity Product @ 1 (additive) {
            @key productId: uuid
            label?: string
          }
          projection ProductView @ 1 from catalog.Product @ 1 as product {
            productId <- product.productId
            label <- product.label
          }
          semantic Status @ 1 (additive): enum(active, retired)
          enum projection PublicStatus @ 1 (additive) from Status @ 1 pick(active)
        }
        """
    )
    mdl.domains[0].enum_projections[0].members = ["active"]

    resolved = [
        resolve_declaration(mdl, reference, 1)
        for reference in ("catalog.Product", "catalog.ProductView", "catalog.Status", "catalog.PublicStatus")
    ]

    assert [member.name for member in resolved[0].members] == ["productId", "label"]
    assert [(member.name, member.optional, member.nullable) for member in resolved[0].members] == [
        ("productId", False, False),
        ("label", True, False),
    ]
    assert [member.name for member in resolved[1].members] == ["productId", "label"]
    assert all(member.optional is None and member.nullable is None for member in resolved[1].members)
    assert resolved[2].members == ()
    assert [member.name for member in resolved[3].members] == ["active"]


def test_resolved_declaration_exposes_lineage_and_annotations() -> None:
    mdl = parse_text_to_ir(
        """
        domain catalog {
          owner: "catalog-team"
          entity Product @ 1 (additive) { @key productId: uuid }
          projection ProductView @ 1 from catalog.Product @ 1 as product {
            productId <- product.productId
          }
          semantic Status @ 1 (additive): enum(active, retired)
          enum projection PublicStatus @ 1 (additive) from Status @ 1 pick(active)
        }
        """
    )
    mdl.domains[0].enum_projections[0].members = ["active"]

    projection = resolve_declaration(mdl, "catalog.ProductView", 1)
    enum_projection = resolve_declaration(mdl, "catalog.PublicStatus", 1)

    assert projection.annotations == ()
    assert projection.lineage == ("catalog.Product@1",)
    assert enum_projection.lineage == ("catalog.Status@1",)


def test_resolve_model_ref_exact_version(tmp_path):
    source = tmp_path / "workspace.mdl"
    _write_workspace(source)
    workspace = load_workspace(source)

    resolved = resolve_model_ref(workspace.mdl, "customer.Customer", 2)

    assert resolved.domain_name == "customer"
    assert resolved.model_name == "Customer"
    assert resolved.version.version == 2
    assert isinstance(resolved, ResolvedDeclaration)
    assert isinstance(resolved, ResolvedDeclarationView)
    assert (resolved.name, resolved.kind, resolved.version_number) == ("Customer", "model", 2)


def test_model_resolution_ignores_same_name_non_model_declarations():
    mdl = parse_text_to_ir("""
    domain catalog {
      owner: "test-team"
      entity Status @ 1 (additive) { @key statusId: uuid }
      semantic Status @ 2 (additive): string
    }
    """)

    resolved = resolve_model_ref(mdl, "catalog.Status", VersionMin(min_inclusive=1))

    assert (resolved.name, resolved.kind, resolved.version_number) == ("Status", "model", 1)


def test_resolve_model_ref_range_uses_highest_matching_version(tmp_path):
    source = tmp_path / "workspace.mdl"
    _write_workspace(source)
    workspace = load_workspace(source)
    projection = workspace.mdl.domains[1].projections["BillingCustomer"][0]

    resolved = resolve_model_ref(
        workspace.mdl,
        projection.source.model,
        projection.source.version,
    )

    assert resolved.version.version == 2
    assert (resolved.name, resolved.kind, resolved.version_number) == ("Customer", "model", 2)

    projection_resolved = resolve_model_ref(workspace.mdl, "billing.BillingCustomer", 1)
    assert (projection_resolved.name, projection_resolved.kind, projection_resolved.version_number) == (
        "BillingCustomer",
        "projection",
        1,
    )


def test_load_workspace_reports_unresolved_projection_source(tmp_path):
    source = tmp_path / "workspace.mdl"
    source.write_text(
        """
domain billing {
  owner: "test-team"
  projection MissingCustomer @ 1
    from customer.Customer @ 1 as c
  {
    id <- c.customerId
  }
}
""",
        encoding="utf-8",
    )

    workspace = load_workspace(source)

    assert any(
        "unresolved model reference customer.Customer@1" in diagnostic.message for diagnostic in workspace.errors
    )


def test_build_registry_persists_resolved_source_versions(tmp_path):
    source = tmp_path / "workspace.mdl"
    _write_workspace(source)
    workspace = load_workspace(source)

    registry_path = build_registry(workspace, tmp_path / ".modelable")

    with sqlite3.connect(registry_path) as conn:
        [(source_version_json,)] = conn.execute(
            """
            select source_version_json
            from projection_versions
            where domain_name = 'billing' and projection_name = 'BillingCustomer'
            """
        ).fetchall()

    assert json.loads(source_version_json) == {"kind": "exact", "version": 2}
