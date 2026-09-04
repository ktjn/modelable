from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from modelable.facets import Facet, FacetIdentity, FacetSubject
from modelable.planner.protocol import facet_documents, migrate_plan, validate_plan

FIXTURE = Path(__file__).parent / "fixtures" / "plan_v0" / "billing.BillingCustomer.v1.plan.json"
V1_SCHEMA = Path(__file__).parents[1] / "src" / "modelable" / "schemas" / "plan-v1.schema.json"


def test_plan_v1_accepts_canonical_facet_arrays_without_changing_v0_migration() -> None:
    """Rejecting valid facet arrays would prevent plan consumers from observing normalized facts."""
    plan = migrate_plan(json.loads(FIXTURE.read_text(encoding="utf-8")), "modelable.plan/v1")
    facet = Facet(
        FacetIdentity.from_canonical("org.example/retention-class@1"),
        "regulated",
        FacetSubject.parse("field:billing.Customer@1#customerId"),
        "project",
        interpretation="known",
    )
    plan["source"]["facets"] = []
    plan["source"]["resolved"]["facets"] = []
    plan["source"]["resolved"]["fields"][0]["facets"] = facet_documents((facet,))
    plan["fields"][0]["facets"] = facet_documents((facet,))

    assert validate_plan(plan) == plan
    assert list(Draft202012Validator(json.loads(V1_SCHEMA.read_text(encoding="utf-8"))).iter_errors(plan)) == []


def test_facet_documents_sort_identity_and_provenance_deterministically() -> None:
    """Using sidecar order would make equivalent plan output vary between runs."""
    high = Facet(
        FacetIdentity.from_canonical("org.example/zeta@1"),
        "z",
        FacetSubject.parse("field:orders.Order@1#id"),
        "none",
        interpretation="known",
    )
    low = Facet(
        FacetIdentity.from_canonical("org.example/alpha@1"),
        "a",
        FacetSubject.parse("field:orders.Order@1#id"),
        "none",
        interpretation="unknown",
    )

    assert [document["identity"] for document in facet_documents((high, low))] == [
        "org.example/alpha@1",
        "org.example/zeta@1",
    ]
