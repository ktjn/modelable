import pytest

from modelable.parser.parse import parse_text_to_ir
from modelable.registry.resolver import (
    ResolvedDeclarationView,
    resolve_enum_type_ref,
    resolve_named_declaration,
    resolve_semantic_type_ref,
)
from modelable.registry.signature import compute_version_signature
from modelable.registry.snapshot import _dependencies


def test_bare_name_resolves_in_current_domain_first():
    mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      semantic Id: uuid
    }
    domain billing {
      owner: "test-team"
      semantic Id: string
    }
    """)

    domain_name, decl = resolve_semantic_type_ref(mdl, "billing", "Id")

    # billing's own Id (string), not orders' Id (uuid) — if workspace-wide
    # fallback had run instead of domain-local shadowing, this would have
    # raised LookupError for ambiguity between orders.Id and billing.Id.
    assert domain_name == "billing"
    assert decl.name == "Id"
    assert decl.underlying.kind == "string"


def test_qualified_name_resolves_across_domains():
    mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      semantic Id: uuid
    }
    domain billing {
      owner: "test-team"
      semantic Id: string
    }
    """)

    domain_name, decl = resolve_semantic_type_ref(mdl, "billing", "orders.Id")

    assert domain_name == "orders"
    assert decl.name == "Id"


def test_bare_name_falls_back_to_workspace_when_current_domain_has_no_match():
    mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      semantic Id: uuid
    }
    domain billing {
      owner: "test-team"
      entity Invoice @ 1 (additive) {
        @key invoiceId: uuid
      }
    }
    """)

    domain_name, decl = resolve_semantic_type_ref(mdl, "billing", "Id")

    assert domain_name == "orders"
    assert decl.name == "Id"


def test_ambiguous_bare_reference_is_an_error():
    mdl = parse_text_to_ir("""
    domain alpha {
      owner: "test-team"
      semantic SharedId: uuid
    }
    domain beta {
      owner: "test-team"
      semantic SharedId: string
    }
    domain consumer {
      owner: "test-team"
      entity Event @ 1 (additive) {
        @key eventId: uuid
      }
    }
    """)

    with pytest.raises(
        LookupError, match=r"ambiguous semantic type 'SharedId'; candidates: alpha\.SharedId, beta\.SharedId"
    ):
        resolve_semantic_type_ref(mdl, "consumer", "SharedId")


def test_unknown_bare_name_is_an_error():
    mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      semantic Id: uuid
    }
    """)

    with pytest.raises(LookupError, match="unknown semantic type 'DoesNotExist'"):
        resolve_semantic_type_ref(mdl, "orders", "DoesNotExist")


def test_qualified_reference_to_unknown_domain_is_an_error():
    mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      semantic Id: uuid
    }
    """)

    with pytest.raises(LookupError, match="unknown domain 'nope'"):
        resolve_semantic_type_ref(mdl, "orders", "nope.Id")


def test_qualified_reference_to_unknown_name_in_known_domain_is_an_error():
    mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      semantic Id: uuid
    }
    """)

    with pytest.raises(LookupError, match=r"unknown semantic type 'orders\.DoesNotExist'"):
        resolve_semantic_type_ref(mdl, "orders", "orders.DoesNotExist")


def test_enum_type_reference_resolves_projection_and_exact_version():
    mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      semantic OrderStatus @ 1 (additive): enum(pending, paid)
      enum projection PublicStatus @ 1 (additive)
        from OrderStatus @ 1
        pick(paid)
      enum projection PublicStatus @ 2 (additive)
        from OrderStatus @ 1
        pick(pending, paid)
    }
    """)

    domain_name, decl = resolve_enum_type_ref(mdl, "orders", "PublicStatus", exact_version=1)

    assert domain_name == "orders"
    assert decl.name == "PublicStatus"
    assert decl.version == 1


def test_named_declaration_view_unifies_semantic_and_enum_projection_identity():
    mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      semantic OrderStatus @ 1 (additive): enum(pending, paid)
      enum projection PublicStatus @ 1 (additive)
        from OrderStatus @ 1
        pick(paid)
    }
    """)

    semantic = resolve_named_declaration(mdl, "orders", "OrderStatus", exact_version=1)
    projection = resolve_named_declaration(mdl, "orders", "PublicStatus", exact_version=1)

    assert (semantic.domain_name, semantic.name, semantic.version, semantic.kind) == (
        "orders",
        "OrderStatus",
        1,
        "semantic_type",
    )
    assert (projection.domain_name, projection.name, projection.version, projection.kind) == (
        "orders",
        "PublicStatus",
        1,
        "enum_projection",
    )
    assert isinstance(semantic, ResolvedDeclarationView)
    assert isinstance(projection, ResolvedDeclarationView)
    assert semantic.version_number == projection.version_number == 1


def test_enum_type_reference_rejects_ambiguous_cross_domain_projections():
    mdl = parse_text_to_ir("""
    domain alpha {
      owner: "test-team"
      semantic Status @ 1 (additive): enum(active)
      enum projection PublicStatus @ 1 (additive)
        from Status @ 1
        pick(active)
    }
    domain beta {
      owner: "test-team"
      semantic Status @ 1 (additive): enum(active)
      enum projection PublicStatus @ 1 (additive)
        from Status @ 1
        pick(active)
    }
    domain consumer {
      owner: "test-team"
    }
    """)

    with pytest.raises(LookupError, match=r"ambiguous enum type 'PublicStatus'"):
        resolve_enum_type_ref(mdl, "consumer", "PublicStatus", exact_version=1)


def test_projection_fallback_can_resolve_exact_version_when_semantic_version_is_absent():
    mdl = parse_text_to_ir("""
    domain source {
      owner: "test-team"
      semantic PublicStatus @ 1 (additive): enum(active)
    }
    domain consumer {
      owner: "test-team"
      enum projection PublicStatus @ 2 (additive)
        from source.PublicStatus @ 1
        pick(active)
    }
    """)

    domain_name, decl = resolve_enum_type_ref(mdl, "consumer", "PublicStatus", exact_version=2)

    assert domain_name == "consumer"
    assert decl.name == "PublicStatus"


def test_local_projection_does_not_hide_ambiguous_semantic_reference():
    mdl = parse_text_to_ir("""
    domain alpha {
      owner: "test-team"
      semantic PublicStatus @ 1 (additive): enum(active)
    }
    domain beta {
      owner: "test-team"
      semantic PublicStatus @ 1 (additive): enum(active)
    }
    domain consumer {
      owner: "test-team"
      semantic Status @ 1 (additive): enum(active)
      enum projection PublicStatus @ 1 (additive)
        from Status @ 1
        pick(active)
    }
    """)

    with pytest.raises(LookupError, match=r"ambiguous semantic type 'PublicStatus'"):
        resolve_enum_type_ref(mdl, "consumer", "PublicStatus")


def test_projection_typed_field_has_deterministic_nominal_signature():
    mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      semantic Status @ 1 (additive): enum(pending, paid)
      enum projection PublicStatus @ 1 (additive)
        from Status @ 1
        pick(paid)
      entity Order @ 1 (additive) {
        @key orderId: uuid
        status: PublicStatus @ 1
      }
    }
    """)
    version = mdl.domains[0].models["Order"][0]

    first = compute_version_signature("orders", "Order", version)
    second = compute_version_signature("orders", "Order", version.model_copy(deep=True))

    assert first == second
    semantic_mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      semantic Status @ 1 (additive): enum(pending, paid)
      entity Order @ 1 (additive) {
        @key orderId: uuid
        status: Status @ 1
      }
    }
    """)

    assert first != compute_version_signature("orders", "Order", semantic_mdl.domains[0].models["Order"][0])


def test_snapshot_dependencies_resolve_projection_field_identity():
    mdl = parse_text_to_ir("""
    domain source {
      owner: "test-team"
      semantic Status @ 1 (additive): enum(active)
      enum projection PublicStatus @ 1 (additive)
        from Status @ 1
        pick(active)
    }
    domain consumer {
      owner: "test-team"
      entity Order @ 1 (additive) {
        @key orderId: uuid
        status: source.PublicStatus @ 1
      }
    }
    """)
    version = mdl.domains[1].models["Order"][0]

    dependencies = _dependencies(version, mdl, "consumer")
    assert dependencies == ["source.PublicStatus@1"]
