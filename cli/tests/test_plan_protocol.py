import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from modelable.planner.protocol import (
    PLAN_V1_SCHEMA,
    PlanProtocolError,
    load_plan,
    migrate_plan,
    serialize_plan,
    validate_plan,
)

FIXTURE = Path(__file__).parent / "fixtures" / "plan_v0" / "billing.BillingCustomer.v1.plan.json"
V1_SCHEMA = Path(__file__).parents[1] / "src" / "modelable" / "schemas" / "plan-v1.schema.json"


def test_migrate_v0_plan_to_v1_records_source_schema() -> None:
    v0 = load_plan(FIXTURE)

    v1 = migrate_plan(v0, PLAN_V1_SCHEMA)

    assert v1["$schema"] == PLAN_V1_SCHEMA
    assert v1["planner_metadata"] == {
        "modelable_schema": "1.0",
        "migrated_from": "modelable.plan/v0",
    }
    assert all("#" in ref for field in v1["fields"] for ref in field["lineage"])
    assert validate_plan(v1) == v1
    assert serialize_plan(v1) == serialize_plan(migrate_plan(v0, PLAN_V1_SCHEMA))


def test_validate_plan_dispatches_v1_and_rejects_unknown_schema() -> None:
    v1 = migrate_plan(load_plan(FIXTURE), PLAN_V1_SCHEMA)

    assert validate_plan(v1)["$schema"] == PLAN_V1_SCHEMA

    unknown = dict(v1)
    unknown["$schema"] = "modelable.plan/v2"
    with pytest.raises(PlanProtocolError, match="unsupported plan schema"):
        validate_plan(unknown)


def test_validate_v1_rejects_legacy_dotted_lineage() -> None:
    v1 = migrate_plan(load_plan(FIXTURE), PLAN_V1_SCHEMA)
    v1["fields"][0]["lineage"] = ["customer.Customer@1.customerId"]

    with pytest.raises(PlanProtocolError, match="canonical semantic path"):
        validate_plan(v1)


def test_migrate_plan_rejects_unsupported_direction() -> None:
    with pytest.raises(PlanProtocolError, match="unsupported plan migration"):
        migrate_plan(load_plan(FIXTURE), "modelable.plan/v2")


def test_checked_in_v1_schema_accepts_migrated_plan() -> None:
    schema = json.loads(V1_SCHEMA.read_text(encoding="utf-8"))
    plan = migrate_plan(load_plan(FIXTURE), PLAN_V1_SCHEMA)

    errors = list(Draft202012Validator(schema).iter_errors(plan))

    assert errors == []
    assert schema["$id"] == PLAN_V1_SCHEMA
