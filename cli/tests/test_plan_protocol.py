from pathlib import Path

import pytest

from modelable.planner.protocol import (
    PLAN_V1_SCHEMA,
    PlanProtocolError,
    load_plan,
    migrate_plan,
    serialize_plan,
    validate_plan,
)

FIXTURE = Path(__file__).parent / "fixtures" / "plan_v0" / "billing.BillingCustomer.v1.plan.json"


def test_migrate_v0_plan_to_v1_records_source_schema() -> None:
    v0 = load_plan(FIXTURE)

    v1 = migrate_plan(v0, PLAN_V1_SCHEMA)

    assert v1["$schema"] == PLAN_V1_SCHEMA
    assert v1["planner_metadata"] == {
        "modelable_schema": "1.0",
        "migrated_from": "modelable.plan/v0",
    }
    assert validate_plan(v1) == v1
    assert serialize_plan(v1) == serialize_plan(migrate_plan(v0, PLAN_V1_SCHEMA))


def test_validate_plan_dispatches_v1_and_rejects_unknown_schema() -> None:
    v1 = migrate_plan(load_plan(FIXTURE), PLAN_V1_SCHEMA)

    assert validate_plan(v1)["$schema"] == PLAN_V1_SCHEMA

    unknown = dict(v1)
    unknown["$schema"] = "modelable.plan/v2"
    with pytest.raises(PlanProtocolError, match="unsupported plan schema"):
        validate_plan(unknown)


def test_migrate_plan_rejects_unsupported_direction() -> None:
    with pytest.raises(PlanProtocolError, match="unsupported plan migration"):
        migrate_plan(load_plan(FIXTURE), "modelable.plan/v2")
