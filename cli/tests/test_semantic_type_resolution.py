import pytest

from modelable.parser.parse import parse_text_to_ir
from modelable.registry.resolver import resolve_semantic_type_ref


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
