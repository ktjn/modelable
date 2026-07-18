from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from modelable.llm.conversation_plan import (
    ChangeSetPlan,
    CreateModel,
    QueryPlan,
    parse_conversation_plan,
)


def test_parse_create_model_plan_with_nested_address() -> None:
    payload = {
        "kind": "change_set",
        "summary": "Create customer.Customer@1",
        "assumptions": ["Address is inline", "Owner comes from domain customer"],
        "edit_mode": "append_versions",
        "operations": [
            {
                "kind": "create_model",
                "domain": "customer",
                "name": "Customer",
                "model_kind": "entity",
                "version": 1,
                "fields": [
                    {
                        "name": "customerId",
                        "type": {"kind": "uuid", "version": 4},
                        "annotations": [{"kind": "key"}],
                    },
                    {
                        "name": "address",
                        "type": {
                            "kind": "object",
                            "fields": [
                                {"name": "street", "type": {"kind": "string", "version": 4}},
                                {"name": "city", "type": {"kind": "string", "version": 4}},
                                {"name": "postalCode", "type": {"kind": "string", "version": 4}},
                                {"name": "country", "type": {"kind": "string", "version": 4}},
                            ],
                        },
                    },
                ],
            }
        ],
    }

    plan = parse_conversation_plan(json.dumps(payload))

    assert isinstance(plan, ChangeSetPlan)
    operation = plan.operations[0]
    assert isinstance(operation, CreateModel)
    assert operation.fields[1].name == "address"
    assert operation.fields[1].to_field_def().type.kind == "object"


def test_query_plan_is_closed_to_known_query_kinds() -> None:
    with pytest.raises(ValidationError):
        QueryPlan(kind="query", query_kind="run_shell", refs=[], question="delete files")


def test_change_plan_rejects_raw_patch_and_path_fields() -> None:
    payload = {
        "kind": "change_set",
        "summary": "unsafe",
        "assumptions": [],
        "edit_mode": "append_versions",
        "operations": [
            {
                "kind": "create_model",
                "domain": "customer",
                "name": "Customer",
                "model_kind": "entity",
                "version": 1,
                "fields": [
                    {
                        "name": "customerId",
                        "type": {"kind": "uuid"},
                        "annotations": [{"kind": "key"}],
                    }
                ],
                "path": "customer.mdl",
                "patch": "@@",
            }
        ],
    }

    with pytest.raises(ValidationError):
        parse_conversation_plan(json.dumps(payload))


def test_change_plan_rejects_empty_operations() -> None:
    with pytest.raises(ValidationError):
        ChangeSetPlan(summary="Do nothing", operations=[])


@pytest.mark.parametrize(
    "operation",
    [
        {"kind": "append_model_version", "source": "customer.Customer@1", "version": 2},
        {"kind": "append_projection_version", "source": "billing.CustomerView@1", "version": 2},
        {
            "kind": "add_field",
            "target": "customer.Customer@2",
            "field": {"name": "email", "type": {"kind": "string"}},
        },
        {"kind": "rename_field", "target": "customer.Customer@2", "field": "name", "new_name": "displayName"},
        {"kind": "remove_field", "target": "customer.Customer@2", "field": "legacyName"},
        {
            "kind": "change_field_type",
            "target": "customer.Customer@2",
            "field": "age",
            "type": {"kind": "u16"},
        },
        {
            "kind": "set_field_optionality",
            "target": "customer.Customer@2",
            "field": "email",
            "optional": True,
        },
        {
            "kind": "set_field_annotations",
            "target": "customer.Customer@2",
            "field": "email",
            "annotations": [{"kind": "pii"}],
        },
        {"kind": "set_primary_index", "target": "customer.Customer@2", "fields": ["customerId"]},
        {
            "kind": "add_secondary_index",
            "target": "customer.Customer@2",
            "index": {"name": "byEmail", "key": ["email"], "sort": [], "unique": True},
        },
        {"kind": "remove_secondary_index", "target": "customer.Customer@2", "name": "byEmail"},
        {
            "kind": "set_projection_source",
            "target": "billing.CustomerView@2",
            "source": {"model": "customer.Customer", "version": 2, "alias": "c"},
        },
        {
            "kind": "add_projection_field",
            "target": "billing.CustomerView@2",
            "field": {
                "name": "email",
                "mapping": {"kind": "direct", "source_alias": "c", "source_field": "email"},
            },
        },
        {
            "kind": "set_projection_mapping",
            "target": "billing.CustomerView@2",
            "field": "email",
            "mapping": {"kind": "computed", "expression": "lower(c.email)"},
        },
        {
            "kind": "add_projection_join",
            "target": "billing.CustomerView@2",
            "join": {
                "model": "orders.Order",
                "version": 1,
                "alias": "o",
                "on": "c.customerId == o.customerId",
            },
        },
        {
            "kind": "set_projection_filter",
            "target": "billing.CustomerView@2",
            "expression": 'c.status == "active"',
        },
        {
            "kind": "set_projection_grouping",
            "target": "billing.CustomerView@2",
            "fields": ["c.customerId"],
        },
        {"kind": "rename_definition", "target": "customer.Customer@1", "new_name": "Client"},
        {"kind": "retire_definition", "target": "customer.Customer@1", "replacement": "customer.Client@1"},
    ],
)
def test_operation_discriminators_accept_the_closed_vocabulary(operation: dict[str, object]) -> None:
    payload = {
        "kind": "change_set",
        "summary": "Change workspace",
        "operations": [operation],
    }

    plan = parse_conversation_plan(json.dumps(payload))

    assert isinstance(plan, ChangeSetPlan)
    assert plan.operations[0].kind == operation["kind"]


def test_unknown_operation_kind_is_rejected() -> None:
    payload = {
        "kind": "change_set",
        "summary": "Run arbitrary code",
        "operations": [{"kind": "run_tool", "tool": "shell"}],
    }

    with pytest.raises(ValidationError):
        parse_conversation_plan(json.dumps(payload))
