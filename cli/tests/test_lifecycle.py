from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from modelable.lifecycle import (
    LifecycleError,
    LifecycleState,
    find_lifecycle_reference_findings,
    parse_lifecycle_document,
    validate_lifecycle_transition,
)


def test_lifecycle_document_is_strict_canonical_and_deterministic() -> None:
    document = parse_lifecycle_document(
        {
            "$schema": "modelable.lifecycle/v1",
            "entries": [
                {"identity": "orders.Order@2", "state": "deprecated", "replacement": "orders.Order@3"},
                {"identity": "orders.Order@1", "state": "published"},
            ],
        }
    )

    assert document == {
        "$schema": "modelable.lifecycle/v1",
        "entries": [
            {"identity": "orders.Order@1", "state": "published"},
            {"identity": "orders.Order@2", "state": "deprecated", "replacement": "orders.Order@3"},
        ],
    }


def test_lifecycle_transition_is_monotonic_and_canonical() -> None:
    validate_lifecycle_transition(LifecycleState.published, LifecycleState.deprecated)

    with pytest.raises(LifecycleError, match="cannot transition"):
        validate_lifecycle_transition(LifecycleState.candidate, LifecycleState.retired)

    with pytest.raises(LifecycleError, match="canonical declaration identity"):
        parse_lifecycle_document(
            {
                "$schema": "modelable.lifecycle/v1",
                "entries": [{"identity": "orders.Order@01", "state": "published"}],
            }
        )


def test_lifecycle_schema_is_valid_and_accepts_the_protocol_document() -> None:
    schema_path = Path(__file__).parents[1] / "src" / "modelable" / "data" / "modelable.lifecycle.v1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate({"$schema": "modelable.lifecycle/v1", "entries": []})


def test_lifecycle_reference_check_reports_deprecated_and_retired_dependencies() -> None:
    lifecycle = parse_lifecycle_document(
        {
            "$schema": "modelable.lifecycle/v1",
            "entries": [
                {"identity": "orders.Order@1", "state": "deprecated"},
                {"identity": "orders.Order@2", "state": "retired"},
            ],
        }
    )

    findings = find_lifecycle_reference_findings(
        [
            {"identity": "billing.Invoice@1", "dependencies": ["orders.Order@1", "orders.Order@2"]},
            {"identity": "orders.Order@3", "dependencies": []},
        ],
        lifecycle,
    )

    assert findings == [
        {"source": "billing.Invoice@1", "target": "orders.Order@1", "state": "deprecated"},
        {"source": "billing.Invoice@1", "target": "orders.Order@2", "state": "retired"},
    ]
