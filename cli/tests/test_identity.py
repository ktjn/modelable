import pytest

from modelable.identity import declaration_id, parse_declaration_id, parse_semantic_path, semantic_path


@pytest.mark.parametrize(
    ("segments", "expected"),
    [
        (("email",), "customer.Customer@4#email"),
        (("address", "street"), "customer.Customer@4#address.street"),
        (("orders[]",), "customer.Customer@4#orders[]"),
        (("attributes{}", "value"), "customer.Customer@4#attributes{}.value"),
        (("status", "active"), "customer.Customer@4#status.active"),
    ],
)
def test_semantic_path_round_trips_typed_segments(segments: tuple[str, ...], expected: str) -> None:
    assert semantic_path(declaration_id("customer", "Customer", 4), *segments) == expected
    assert parse_semantic_path(expected).render() == expected


@pytest.mark.parametrize(
    "value",
    [
        "customer.Customer#email",
        "customer.Customer@4#",
        "customer.Customer@4#address..street",
        "customer.Customer@4#attributes{keys}",
        "customer.Customer@4#orders[ ]",
    ],
)
def test_semantic_path_rejects_ambiguous_or_inexact_forms(value: str) -> None:
    with pytest.raises(ValueError):
        parse_semantic_path(value)


def test_declaration_id_rejects_noncanonical_components() -> None:
    with pytest.raises(ValueError):
        declaration_id("customer", "Customer.Name", 1)
    with pytest.raises(ValueError):
        declaration_id("customer", "Customer", -1)


def test_semantic_path_rejects_noncanonical_declaration_root() -> None:
    with pytest.raises(ValueError):
        semantic_path("customer.Customer", "email")


def test_declaration_id_supports_quoted_domain_names() -> None:
    declaration = declaration_id("marketplace-api", "Product", 1)

    assert declaration == "marketplace-api.Product@1"
    assert parse_semantic_path(f"{declaration}#sku").render() == f"{declaration}#sku"


def test_parse_declaration_id_round_trips_canonical_identity() -> None:
    assert parse_declaration_id("marketplace-api.Product@0") == ("marketplace-api", "Product", 0)


@pytest.mark.parametrize(
    ("domain", "name", "version"),
    [
        ("customer", "Customer", 4),
        ("marketplace-api", "Product", 0),
        ("foo-bar", "Thing", 2),
        ("foo_bar", "Thing", 2),
        ("customer", "customer", 4),
    ],
)
def test_declaration_id_round_trip_fixtures_are_collision_free(domain: str, name: str, version: int) -> None:
    value = declaration_id(domain, name, version)

    assert declaration_id(*parse_declaration_id(value)) == value


def test_declaration_id_keeps_similar_components_distinct() -> None:
    values = {
        declaration_id("foo-bar", "Thing", 2),
        declaration_id("foo_bar", "Thing", 2),
        declaration_id("customer", "Thing", 2),
        declaration_id("customer", "thing", 2),
        declaration_id("customer", "Thing", 3),
    }

    assert len(values) == 5
