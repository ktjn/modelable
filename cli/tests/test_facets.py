"""Contract tests for parser-independent typed semantic facets."""

from __future__ import annotations

import json
import math
from dataclasses import replace
from importlib.resources import files
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from modelable.compiler.workspace import Workspace, WorkspaceDocumentSource, load_workspace_from_sources
from modelable.facets import (
    Facet,
    FacetError,
    FacetIdentity,
    FacetRegistry,
    FacetSchema,
    FacetSource,
    FacetSubject,
    facets_for_subject,
    load_facet_document,
    normalize_workspace_facets,
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


def test_load_facet_document_orders_validated_facts_and_preserves_explicit_source_uri(tmp_path: Path) -> None:
    """Removing local schema validation or canonical sorting must break this contract."""
    sidecar = tmp_path / "modelable.facets.json"
    sidecar.write_text(
        json.dumps(
            {
                "$schema": "modelable.facets/v1",
                "schemas": [
                    {
                        "identity": "org.example/retention-class@1",
                        "value_schema": {"type": "string", "enum": ["regulated", "transient"]},
                        "allowed_subjects": ["field"],
                        "propagation": "project",
                    },
                    {
                        "identity": "org.example/confidentiality@1",
                        "value_schema": {"type": "string"},
                        "allowed_subjects": ["declaration"],
                        "propagation": "inherit",
                    },
                ],
                "facets": [
                    {
                        "identity": "org.example/retention-class@1",
                        "value": "regulated",
                        "subject": "field:orders.Order@1#customer_id",
                        "propagation": "project",
                    },
                    {
                        "identity": "org.example/unregistered@1",
                        "value": {"classification": "future"},
                        "subject": "field:orders.Order@1#customer_id",
                        "propagation": "none",
                        "source": {
                            "subject": "field:orders.Order@1#customer_id",
                            "location": "file:///governance/modelable.facets.json",
                        },
                    },
                    {
                        "identity": "org.example/confidentiality@1",
                        "value": "restricted",
                        "subject": "declaration:orders.Order@1",
                        "propagation": "inherit",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    registry, facets = load_facet_document(sidecar)

    assert [identity.canonical for identity in registry.schemas] == [
        "org.example/confidentiality@1",
        "org.example/retention-class@1",
    ]
    assert [facet.identity.canonical for facet in facets] == [
        "org.example/confidentiality@1",
        "org.example/retention-class@1",
        "org.example/unregistered@1",
    ]
    assert [facet.interpretation for facet in facets] == ["known", "known", "unknown"]
    assert facets[2].source is not None
    assert facets[2].source.location == "file:///governance/modelable.facets.json"


def test_load_facet_document_rejects_duplicate_schema_identities(tmp_path: Path) -> None:
    """Removing duplicate rejection would make schema resolution ambiguous."""
    sidecar = tmp_path / "modelable.facets.json"
    sidecar.write_text(
        json.dumps(
            {
                "$schema": "modelable.facets/v1",
                "schemas": [
                    {
                        "identity": "org.example/retention-class@1",
                        "value_schema": {"type": "string"},
                        "allowed_subjects": ["field"],
                        "propagation": "none",
                    },
                    {
                        "identity": "org.example/retention-class@1",
                        "value_schema": {"type": "string"},
                        "allowed_subjects": ["field"],
                        "propagation": "none",
                    },
                ],
                "facets": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(FacetError, match="duplicate facet schema identity"):
        load_facet_document(sidecar)


def test_load_facet_document_rejects_in_memory_interpretation_field(tmp_path: Path) -> None:
    """Allowing a caller-supplied interpretation would bypass local schema validation."""
    sidecar = tmp_path / "modelable.facets.json"
    sidecar.write_text(
        json.dumps(
            {
                "$schema": "modelable.facets/v1",
                "schemas": [],
                "facets": [
                    {
                        "identity": "org.example/future-fact@1",
                        "value": True,
                        "subject": "field:orders.Order@1#customer_id",
                        "propagation": "none",
                        "interpretation": "known",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(FacetError, match=r"unknown key.*interpretation"):
        load_facet_document(sidecar)


def test_checked_in_facet_sidecar_schema_rejects_unsupported_value_schema_keywords() -> None:
    """Permitting arbitrary JSON-Schema keywords would diverge from the local facet validator."""
    schema = json.loads(files("modelable.data").joinpath("modelable.facets.v1.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    document = {
        "$schema": "modelable.facets/v1",
        "schemas": [
            {
                "identity": "org.example/retention-class@1",
                "value_schema": {"format": "uri"},
                "allowed_subjects": ["field"],
                "propagation": "none",
            }
        ],
        "facets": [],
    }

    with pytest.raises(ValidationError, match="Additional properties are not allowed"):
        validator.validate(document)


def _propagation_workspace() -> Workspace:
    """Build a resolved workspace with direct, computed, and chained projection lineage."""
    source = WorkspaceDocumentSource(
        path=None,
        uri="memory://facets-propagation.mdl",
        text="""
domain customers {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key id: uuid
  }
}
domain orders {
  owner: "test-team"
  entity Order @ 1 (additive) {
    @key id: uuid
    customerId: uuid
  }
}
domain analytics {
  owner: "test-team"
  projection CustomerOrder @ 1
    from orders.Order @ 1 as o
    join customers.Customer @ 1 as c on o.customerId == c.id
  {
    customerId <- o.customerId
    matches = c.id == o.customerId
  }
  projection CustomerOrderAgain @ 1
    from analytics.CustomerOrder @ 1 as co
  {
    matches <- co.matches
  }
}
""",
    )
    return load_workspace_from_sources(
        [source],
        facets_document={
            "$schema": "modelable.facets/v1",
            "schemas": [
                {
                    "identity": "org.example/data-subject@1",
                    "value_schema": {"type": "string"},
                    "allowed_subjects": ["field", "projection_field"],
                    "propagation": "project",
                },
                {
                    "identity": "org.example/jurisdiction@1",
                    "value_schema": {"type": "string"},
                    "allowed_subjects": ["declaration", "field", "projection", "projection_field"],
                    "propagation": "inherit",
                },
                {
                    "identity": "org.example/local-note@1",
                    "value_schema": {"type": "string"},
                    "allowed_subjects": ["field"],
                    "propagation": "none",
                },
            ],
            "facets": [
                {
                    "identity": "org.example/jurisdiction@1",
                    "value": "SE",
                    "subject": "declaration:orders.Order@1",
                    "propagation": "inherit",
                },
                {
                    "identity": "org.example/data-subject@1",
                    "value": "customer",
                    "subject": "field:customers.Customer@1#id",
                    "propagation": "project",
                },
                {
                    "identity": "org.example/data-subject@1",
                    "value": "order",
                    "subject": "field:orders.Order@1#customerId",
                    "propagation": "project",
                },
                {
                    "identity": "org.example/local-note@1",
                    "value": "do-not-project",
                    "subject": "field:orders.Order@1#customerId",
                    "propagation": "none",
                },
                {
                    "identity": "org.example/future@1",
                    "value": "uninterpreted",
                    "subject": "field:orders.Order@1#customerId",
                    "propagation": "project",
                },
                {
                    "identity": "org.example/data-subject@1",
                    "value": "override",
                    "subject": "projection_field:analytics.CustomerOrder@1#matches",
                    "propagation": "project",
                },
            ],
        },
    )


def test_facets_for_subject_applies_only_known_project_lineage_in_stable_source_order() -> None:
    """Removing lineage propagation, source ordering, or unknown isolation breaks this contract."""
    workspace = _propagation_workspace()

    facets = facets_for_subject(workspace, FacetSubject.parse("projection_field:analytics.CustomerOrder@1#matches"))

    assert [(facet.value, facet.source.subject.canonical if facet.source else None) for facet in facets] == [
        ("override", None),
    ]
    chained = facets_for_subject(
        workspace,
        FacetSubject.parse("projection_field:analytics.CustomerOrderAgain@1#matches"),
    )
    assert [(facet.value, facet.source.subject.canonical if facet.source else None) for facet in chained] == [
        ("override", "projection_field:analytics.CustomerOrder@1#matches"),
    ]
    assert [
        facet.identity.canonical
        for facet in facets_for_subject(
            workspace,
            FacetSubject.parse("projection_field:analytics.CustomerOrder@1#customerId"),
        )
    ] == ["org.example/data-subject@1"]


def test_facets_for_subject_retains_all_computed_project_sources_in_canonical_order() -> None:
    """Removing multi-source lineage or sorting by input order breaks this contract."""
    workspace = _propagation_workspace()
    without_destination_replacement = replace(
        workspace,
        facets=tuple(
            facet
            for facet in workspace.facets
            if facet.source is None
            and facet.subject != FacetSubject.parse("projection_field:analytics.CustomerOrder@1#matches")
        ),
    )

    facets = facets_for_subject(
        without_destination_replacement,
        FacetSubject.parse("projection_field:analytics.CustomerOrder@1#matches"),
    )

    assert [(facet.value, facet.source.subject.canonical if facet.source else None) for facet in facets] == [
        ("customer", "field:customers.Customer@1#id"),
        ("order", "field:orders.Order@1#customerId"),
    ]


def test_normalize_workspace_facets_inherits_declarations_and_rejects_conflicting_explicit_identities() -> None:
    """Removing inheritance or duplicate detection breaks deterministic facet semantics."""
    workspace = _propagation_workspace()

    normalized = normalize_workspace_facets(workspace)

    inherited = [
        facet
        for facet in normalized
        if facet.subject == FacetSubject.parse("field:orders.Order@1#customerId")
        and facet.identity.canonical == "org.example/jurisdiction@1"
    ]
    assert [(facet.value, facet.source.subject.canonical if facet.source else None) for facet in inherited] == [
        ("SE", "declaration:orders.Order@1"),
    ]

    duplicate = load_workspace_from_sources(
        [
            WorkspaceDocumentSource(
                path=None,
                uri="memory://duplicate.mdl",
                text="""
domain orders {
  owner: "test-team"
  entity Order @ 1 (additive) { @key id: uuid }
}
""",
            )
        ],
        facets_document={
            "$schema": "modelable.facets/v1",
            "schemas": [
                {
                    "identity": "org.example/jurisdiction@1",
                    "value_schema": {"type": "string"},
                    "allowed_subjects": ["declaration"],
                    "propagation": "inherit",
                }
            ],
            "facets": [
                {
                    "identity": "org.example/jurisdiction@1",
                    "value": "SE",
                    "subject": "declaration:orders.Order@1",
                    "propagation": "inherit",
                },
                {
                    "identity": "org.example/jurisdiction@1",
                    "value": "NO",
                    "subject": "declaration:orders.Order@1",
                    "propagation": "inherit",
                },
            ],
        },
    )

    assert any(
        diagnostic.code == "FACET" and "duplicate explicit facet" in diagnostic.message
        for diagnostic in duplicate.errors
    )


def test_workspace_reports_a_facet_subject_that_is_not_a_resolved_field() -> None:
    """Removing resolved-subject validation would accept inert governance facts."""
    workspace = load_workspace_from_sources(
        [
            WorkspaceDocumentSource(
                path=None,
                uri="memory://missing-field.mdl",
                text="""
domain orders {
  owner: "test-team"
  entity Order @ 1 (additive) { @key id: uuid }
}
""",
            )
        ],
        facets_document={
            "$schema": "modelable.facets/v1",
            "schemas": [
                {
                    "identity": "org.example/data-subject@1",
                    "value_schema": {"type": "string"},
                    "allowed_subjects": ["field"],
                    "propagation": "none",
                }
            ],
            "facets": [
                {
                    "identity": "org.example/data-subject@1",
                    "value": "customer",
                    "subject": "field:orders.Order@1#missing",
                    "propagation": "none",
                }
            ],
        },
    )

    assert any(
        diagnostic.code == "FACET" and "facet subject does not exist" in diagnostic.message
        for diagnostic in workspace.errors
    )
