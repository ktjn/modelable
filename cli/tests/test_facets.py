"""Contract tests for parser-independent typed semantic facets."""

from __future__ import annotations

import math

import pytest

from modelable.facets import (
    Facet,
    FacetError,
    FacetIdentity,
    FacetRegistry,
    FacetSchema,
    FacetSource,
    FacetSubject,
)


def _retention_schema() -> FacetSchema:
    return FacetSchema(
        identity=FacetIdentity("org.example", "retention-class", 1),
        value_schema={"type": "string", "enum": ["transient", "regulated"]},
        allowed_subjects=("field", "projection_field"),
        propagation="project",
    )


def test_identity_round_trips_canonically() -> None:
    identity = FacetIdentity.from_canonical("org.example/retention-class@1")

    assert identity == FacetIdentity("org.example", "retention-class", 1)
    assert identity.canonical == "org.example/retention-class@1"


@pytest.mark.parametrize(
    "identity",
    [
        ("Org.example", "retention-class", 1),
        ("org..example", "retention-class", 1),
        ("org.example", "retention--class", 1),
        ("org.example", "retention_class", 1),
        ("org.example", "retention-class", 0),
        ("org.example", "retention-class", True),
    ],
)
def test_identity_rejects_noncanonical_components(identity: tuple[object, object, object]) -> None:
    with pytest.raises(FacetError):
        FacetIdentity(*identity)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "value",
    [
        "org.example/retention-class@01",
        "org.example/retention-class@0",
        "org.example/retention-class@1#extra",
        "org.example.retention-class@1",
        "org.example/retention-class@one",
    ],
)
def test_identity_parser_rejects_noncanonical_strings(value: str) -> None:
    with pytest.raises(FacetError):
        FacetIdentity.from_canonical(value)


@pytest.mark.parametrize(
    ("value", "kind", "reference"),
    [
        ("declaration:orders.Order@1", "declaration", "orders.Order@1"),
        ("field:orders.Order@1#customer_id", "field", "orders.Order@1#customer_id"),
        ("projection:analytics.OrderView@2", "projection", "analytics.OrderView@2"),
        (
            "projection_field:analytics.OrderView@2#customer_id",
            "projection_field",
            "analytics.OrderView@2#customer_id",
        ),
    ],
)
def test_subject_parses_each_canonical_kind(value: str, kind: str, reference: str) -> None:
    subject = FacetSubject.parse(value)

    assert subject.kind == kind
    assert subject.reference == reference
    assert subject.canonical == value


@pytest.mark.parametrize(
    "value",
    [
        "model:orders.Order@1",
        "field:orders.Order@1",
        "declaration:orders.Order@1#customer_id",
        "projection:analytics.OrderView@2#customer_id",
        "field:orders.Order@01#customer_id",
        "field:orders.Order@1#bad..path",
        "field:orders.Order@1#customer_id:extra",
    ],
)
def test_subject_rejects_invalid_kind_or_reference(value: str) -> None:
    with pytest.raises(FacetError):
        FacetSubject.parse(value)


def test_source_serializes_canonically() -> None:
    source = FacetSource(
        subject=FacetSubject.parse("field:orders.Order@1#customer_id"),
        location="orders.mdl:5:3",
        lineage="lineage:orders-customer",
    )

    assert source.as_dict() == {
        "subject": "field:orders.Order@1#customer_id",
        "location": "orders.mdl:5:3",
        "lineage": "lineage:orders-customer",
    }


def test_known_facet_serializes_with_sorted_json_keys_and_defensive_value_copy() -> None:
    value = {"z": [True, None], "a": {"y": "value", "x": 1}}
    facet = Facet(
        identity=FacetIdentity("org.example", "jurisdiction", 1),
        value=value,
        subject=FacetSubject.parse("declaration:orders.Order@1"),
        propagation="inherit",
        source=FacetSource(subject=FacetSubject.parse("declaration:orders.Order@1")),
        interpretation="known",
    )
    value["a"]["x"] = 2

    assert facet.as_dict() == {
        "identity": "org.example/jurisdiction@1",
        "value": {"a": {"x": 1, "y": "value"}, "z": [True, None]},
        "subject": "declaration:orders.Order@1",
        "propagation": "inherit",
        "source": {"subject": "declaration:orders.Order@1"},
        "interpretation": "known",
    }


@pytest.mark.parametrize("value", [math.nan, math.inf, {"value": math.nan}, ("not", "json")])
def test_facet_rejects_non_json_values(value: object) -> None:
    with pytest.raises(FacetError):
        Facet(
            identity=FacetIdentity("org.example", "retention-class", 1),
            value=value,
            subject=FacetSubject.parse("field:orders.Order@1#customer_id"),
            propagation="none",
        )


def test_schema_rejects_unsupported_keywords_and_duplicate_typed_enum_values() -> None:
    identity = FacetIdentity("org.example", "retention-class", 1)

    with pytest.raises(FacetError, match="unsupported keyword"):
        FacetSchema(identity, {"format": "uri"}, ("field",), "none")
    with pytest.raises(FacetError, match="duplicate enum"):
        FacetSchema(identity, {"enum": [1, 1]}, ("field",), "none")

    schema = FacetSchema(identity, {"enum": [1, True]}, ("field",), "none")
    assert schema.value_schema == {"enum": [1, True]}


def test_schema_rejects_invalid_subjects_and_propagation() -> None:
    identity = FacetIdentity("org.example", "retention-class", 1)

    with pytest.raises(FacetError, match="allowed subject"):
        FacetSchema(identity, {"type": "string"}, ("model",), "none")
    with pytest.raises(FacetError, match="duplicate allowed subject"):
        FacetSchema(identity, {"type": "string"}, ("field", "field"), "none")
    with pytest.raises(FacetError, match="propagation"):
        FacetSchema(identity, {"type": "string"}, ("field",), "all")


def test_registry_validates_scalar_object_array_and_numeric_constraints() -> None:
    identity = FacetIdentity("org.example", "governance", 1)
    schema = FacetSchema(
        identity,
        {
            "type": "object",
            "properties": {
                "region": {"type": "string", "pattern": "^[A-Z]{2}$"},
                "basis": {"const": "contract"},
                "retention_days": {"type": "integer", "minimum": 1, "maximum": 3650},
                "recipients": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 2,
                },
            },
            "required": ["region", "basis", "retention_days", "recipients"],
            "additionalProperties": False,
        },
        ("declaration",),
        "inherit",
    )
    registry = FacetRegistry({identity: schema})
    subject = FacetSubject.parse("declaration:orders.Order@1")

    valid = Facet(
        identity,
        {"region": "SE", "basis": "contract", "retention_days": 365, "recipients": ["ops"]},
        subject,
        "inherit",
    )
    assert registry.validate(valid).interpretation == "known"

    for value in (
        {"region": "se", "basis": "contract", "retention_days": 365, "recipients": ["ops"]},
        {"region": "SE", "basis": "consent", "retention_days": 365, "recipients": ["ops"]},
        {"region": "SE", "basis": "contract", "retention_days": 0, "recipients": ["ops"]},
        {"region": "SE", "basis": "contract", "retention_days": True, "recipients": ["ops"]},
        {"region": "SE", "basis": "contract", "retention_days": 365, "recipients": []},
        {"region": "SE", "basis": "contract", "retention_days": 365, "recipients": ["ops", "audit", "legal"]},
        {"region": "SE", "basis": "contract", "retention_days": 365, "recipients": ["ops"], "extra": True},
    ):
        with pytest.raises(FacetError):
            registry.validate(Facet(identity, value, subject, "inherit"))


def test_registry_rejects_wrong_subject_or_propagation_for_known_schema() -> None:
    schema = _retention_schema()
    registry = FacetRegistry({schema.identity: schema})

    with pytest.raises(FacetError, match="does not allow subject kind"):
        registry.validate(
            Facet(schema.identity, "transient", FacetSubject.parse("declaration:orders.Order@1"), "project")
        )
    with pytest.raises(FacetError, match="requires propagation"):
        registry.validate(
            Facet(schema.identity, "transient", FacetSubject.parse("field:orders.Order@1#customer_id"), "none")
        )


def test_registry_marks_missing_schema_unknown_without_dropping_value() -> None:
    facet = Facet.from_document(
        {
            "identity": "org.example/new-fact@1",
            "value": {"enabled": True},
            "subject": "field:orders.Order@1#customer_id",
            "propagation": "none",
        }
    )

    validated = FacetRegistry({}).validate(facet)

    assert validated.interpretation == "unknown"
    assert validated.as_dict() == {
        "identity": "org.example/new-fact@1",
        "value": {"enabled": True},
        "subject": "field:orders.Order@1#customer_id",
        "propagation": "none",
        "interpretation": "unknown",
    }
