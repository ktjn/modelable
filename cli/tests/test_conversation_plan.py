from __future__ import annotations

import json
from dataclasses import dataclass

import pytest
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

from modelable.llm.conversation_plan import (
    ChangeSetPlan,
    CreateModel,
    QueryPlan,
    parse_conversation_plan,
)
from modelable.llm.providers import LLMRequest, LLMResponse


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


def test_change_plan_rejects_forbidden_fields_nested_inside_ir_types() -> None:
    payload = {
        "kind": "change_set",
        "summary": "unsafe nested field",
        "operations": [
            {
                "kind": "create_model",
                "domain": "customer",
                "name": "Customer",
                "model_kind": "entity",
                "fields": [
                    {
                        "name": "customerId",
                        "type": {"kind": "uuid", "path": "/tmp/escape"},
                        "annotations": [{"kind": "key", "command": "run"}],
                    }
                ],
            }
        ],
    }

    with pytest.raises(JsonSchemaValidationError):
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


def test_conversation_planner_repairs_invalid_provider_plan() -> None:
    from modelable.llm.conversation_planner import ConversationPlanner, PlannerContext

    requests: list[LLMRequest] = []
    responses = iter(
        [
            LLMResponse(content='{"kind":"change_set","operations":[]}', provider="fake", model="fake"),
            LLMResponse(
                content=json.dumps(
                    {
                        "kind": "change_set",
                        "summary": "Create customer.Customer@1",
                        "operations": [
                            {
                                "kind": "create_model",
                                "domain": "customer",
                                "name": "Customer",
                                "model_kind": "entity",
                                "fields": [
                                    {
                                        "name": "customerId",
                                        "type": {"kind": "uuid"},
                                        "annotations": [{"kind": "key"}],
                                    }
                                ],
                            }
                        ],
                    }
                ),
                provider="fake",
                model="fake",
            ),
        ]
    )

    @dataclass(frozen=True)
    class FakeProvider:
        def complete(self, request: LLMRequest) -> LLMResponse:
            requests.append(request)
            return next(responses)

    planner = ConversationPlanner(FakeProvider())
    plan = planner.plan(
        "Create a customer model with a UUID customerId",
        PlannerContext(
            workspace_summary="domain customer\n  owner: customer-team",
            focused_ref=None,
            history=(),
            pending_plan=None,
        ),
    )

    assert isinstance(plan, ChangeSetPlan)
    assert isinstance(plan.operations[0], CreateModel)
    assert len(requests) == 2
    assert "validation error" in requests[1].user.lower()
    assert "operations" in requests[1].user


def test_conversation_planner_returns_typed_unsupported_when_initial_provider_call_fails() -> None:
    from modelable.llm.conversation_plan import UnsupportedPlan
    from modelable.llm.conversation_planner import ConversationPlanner, PlannerContext

    calls = 0

    @dataclass(frozen=True)
    class FailingProvider:
        def complete(self, request: LLMRequest) -> LLMResponse:
            nonlocal calls
            calls += 1
            raise RuntimeError("provider unavailable")

    plan = ConversationPlanner(FailingProvider(), repair_attempts=2).plan(
        "Create a customer model",
        PlannerContext(workspace_summary="", focused_ref=None, history=(), pending_plan=None),
    )

    assert isinstance(plan, UnsupportedPlan)
    assert calls == 1
    assert "provider" in plan.reason.lower()
    assert "unavailable" in plan.reason.lower()


def test_conversation_planner_returns_typed_unsupported_when_repair_provider_call_fails() -> None:
    from modelable.llm.conversation_plan import UnsupportedPlan
    from modelable.llm.conversation_planner import ConversationPlanner, PlannerContext

    calls = 0

    @dataclass(frozen=True)
    class RepairFailingProvider:
        def complete(self, request: LLMRequest) -> LLMResponse:
            nonlocal calls
            calls += 1
            if calls == 1:
                return LLMResponse(content="{malformed", provider="fake", model="fake")
            raise RuntimeError("repair transport failed")

    plan = ConversationPlanner(RepairFailingProvider(), repair_attempts=2).plan(
        "Create a customer model",
        PlannerContext(workspace_summary="", focused_ref=None, history=(), pending_plan=None),
    )

    assert isinstance(plan, UnsupportedPlan)
    assert calls == 2
    assert "provider" in plan.reason.lower()
    assert "repair transport failed" in plan.reason


def test_conversation_planner_honors_exact_configured_repair_attempt_count() -> None:
    from modelable.llm.conversation_plan import UnsupportedPlan
    from modelable.llm.conversation_planner import ConversationPlanner, PlannerContext

    calls = 0

    @dataclass(frozen=True)
    class MalformedProvider:
        def complete(self, request: LLMRequest) -> LLMResponse:
            nonlocal calls
            calls += 1
            return LLMResponse(content="{malformed", provider="fake", model="fake")

    plan = ConversationPlanner(MalformedProvider(), repair_attempts=3).plan(
        "Create a customer model",
        PlannerContext(workspace_summary="", focused_ref=None, history=(), pending_plan=None),
    )

    assert isinstance(plan, UnsupportedPlan)
    assert calls == 4


def test_conversation_planner_exhausted_malformed_responses_are_actionable() -> None:
    from modelable.llm.conversation_plan import UnsupportedPlan
    from modelable.llm.conversation_planner import ConversationPlanner, PlannerContext

    @dataclass(frozen=True)
    class MalformedProvider:
        def complete(self, request: LLMRequest) -> LLMResponse:
            return LLMResponse(content="{malformed", provider="fake", model="fake")

    plan = ConversationPlanner(MalformedProvider(), repair_attempts=1).plan(
        "Create a customer model",
        PlannerContext(workspace_summary="", focused_ref=None, history=(), pending_plan=None),
    )

    assert isinstance(plan, UnsupportedPlan)
    assert "valid typed plan" in plan.reason.lower()
    assert "expecting property name" in plan.reason.lower()


def test_conversation_request_exposes_only_closed_typed_plan_schema() -> None:
    from modelable.llm.conversation_planner import PlannerContext, build_conversation_request

    request = build_conversation_request(
        message="Add an email field",
        context=PlannerContext(
            workspace_summary="domain customer",
            focused_ref="customer.Customer@1",
            history=(("user", "Focus on Customer"),),
            pending_plan=None,
        ),
    )

    schema_text = json.dumps(request.schema).lower()
    assert request.response_format == "json"
    assert request.schema is not None
    assert '"queryplan"' in schema_text
    assert '"changesetplan"' in schema_text
    assert '"clarificationplan"' in schema_text
    assert '"unsupportedplan"' in schema_text
    for forbidden in (
        '"patch"',
        '"path"',
        '"command"',
        '"compile"',
        '"sync"',
        '"publish"',
        '"external_action"',
        '"validation_override"',
    ):
        assert forbidden not in schema_text

    def assert_closed_objects(node: object) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                assert node.get("additionalProperties") is False
            for value in node.values():
                assert_closed_objects(value)
        elif isinstance(node, list):
            for value in node:
                assert_closed_objects(value)

    assert_closed_objects(request.schema)
    assert json.dumps(request.schema, sort_keys=True) in request.system


def test_conversation_system_prompt_states_safety_and_ambiguity_rules() -> None:
    from modelable.llm.conversation_planner import PlannerContext, build_conversation_request

    request = build_conversation_request(
        message="Change customer.Customer@1",
        context=PlannerContext(
            workspace_summary="domain customer",
            focused_ref="customer.Customer@1",
            history=(),
            pending_plan=None,
        ),
    )
    system = request.system.lower()

    for plan_kind in ("query", "change_set", "clarification", "unsupported"):
        assert plan_kind in system
    for ambiguity in ("ownership", "identity", "reusable address", "source"):
        assert ambiguity in system
    assert "append" in system and "version" in system
    assert "operations" in system
    for unsupported in ("compile", "sync", "publish", "external"):
        assert unsupported in system


def test_offline_planner_routes_commands_questions_and_mutations() -> None:
    from modelable.llm.conversation_plan import UnsupportedPlan
    from modelable.llm.conversation_planner import ConversationPlanner, PlannerContext

    planner = ConversationPlanner(None)
    context = PlannerContext(
        workspace_summary="domain customer",
        focused_ref="customer.Customer@1",
        history=(),
        pending_plan=None,
    )

    describe = planner.plan("/describe", context)
    ownership = planner.plan("Who owns it?", context)
    mutation = planner.plan("Add an email field", context)
    polite_mutation = planner.plan("Could you add an email field?", context)

    assert isinstance(describe, QueryPlan)
    assert describe.query_kind == "summary"
    assert describe.refs == ["customer.Customer@1"]
    assert isinstance(ownership, QueryPlan)
    assert ownership.query_kind == "ownership"
    assert ownership.refs == ["customer.Customer@1"]
    assert isinstance(mutation, UnsupportedPlan)
    assert "provider" in mutation.reason.lower()
    assert isinstance(polite_mutation, UnsupportedPlan)
    assert "provider" in polite_mutation.reason.lower()


@pytest.mark.parametrize("command", ["/compile", "/sync", "/publish"])
def test_offline_planner_routes_slash_operations_to_operations_roadmap(command: str) -> None:
    from modelable.llm.conversation_plan import UnsupportedPlan
    from modelable.llm.conversation_planner import ConversationPlanner, PlannerContext

    plan = ConversationPlanner(None).plan(
        command,
        PlannerContext(workspace_summary="", focused_ref=None, history=(), pending_plan=None),
    )

    assert isinstance(plan, UnsupportedPlan)
    assert plan.roadmap_area == "operations"
    assert "operational" in plan.reason.lower()
