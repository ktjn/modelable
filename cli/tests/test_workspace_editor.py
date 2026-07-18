from __future__ import annotations

import pytest

from modelable.llm.conversation_plan import (
    AppendModelVersion,
    ChangeSetPlan,
    CreateModel,
    FieldSpec,
)
from modelable.llm.workspace_editor import ChangedDefinition, WorkspaceEditError, WorkspaceEditor
from modelable.parser.ir import AnnKey, FieldDef, ObjectType, PrimitiveType


def create_customer_plan() -> ChangeSetPlan:
    return ChangeSetPlan(
        summary="Create customer.Customer@1",
        assumptions=["Address is an inline object"],
        operations=[
            CreateModel(
                domain="customer",
                name="Customer",
                model_kind="entity",
                version=1,
                fields=[
                    FieldSpec(
                        name="customerId",
                        type=PrimitiveType(kind="uuid"),
                        annotations=[AnnKey()],
                    ),
                    FieldSpec(
                        name="address",
                        type=ObjectType(
                            fields=[
                                FieldDef(name="street", type=PrimitiveType(kind="string")),
                                FieldDef(name="city", type=PrimitiveType(kind="string")),
                                FieldDef(name="postalCode", type=PrimitiveType(kind="string")),
                                FieldDef(name="country", type=PrimitiveType(kind="string")),
                            ]
                        ),
                    ),
                ],
            )
        ],
    )


def _write_empty_customer_domain(tmp_path):
    source = tmp_path / "customer.mdl"
    original = 'domain customer {\n  owner: "customer-team"\n}\n'
    source.write_text(original, encoding="utf-8")
    return source, original


def test_preview_creates_complete_entity_without_writing(tmp_path) -> None:
    source, original = _write_empty_customer_domain(tmp_path)

    pending = WorkspaceEditor(tmp_path).preview(create_customer_plan())

    assert pending.changed == [ChangedDefinition(ref="customer.Customer@1", reason="created entity")]
    assert "entity Customer @ 1 (additive)" in pending.candidate_sources[source]
    assert "address: object" in pending.candidate_sources[source]
    assert "--- " in pending.diff_text
    assert "+++ " in pending.diff_text
    assert pending.assumptions == ("Address is an inline object",)
    assert pending.focus_ref == "customer.Customer@1"
    assert len(pending.change_set_id) == 16
    assert source.read_text(encoding="utf-8") == original


def test_preview_change_set_id_is_deterministic(tmp_path) -> None:
    _write_empty_customer_domain(tmp_path)
    editor = WorkspaceEditor(tmp_path)

    first = editor.preview(create_customer_plan())
    second = editor.preview(create_customer_plan())

    assert first.change_set_id == second.change_set_id
    assert first.diff_text == second.diff_text


def test_preview_rejects_duplicate_definition_without_writing(tmp_path) -> None:
    source = tmp_path / "customer.mdl"
    original = """
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
"""
    source.write_text(original, encoding="utf-8")

    with pytest.raises(WorkspaceEditError, match="already exists"):
        WorkspaceEditor(tmp_path).preview(create_customer_plan())

    assert source.read_text(encoding="utf-8") == original


def test_preview_rejects_entity_without_exactly_one_key(tmp_path) -> None:
    source, original = _write_empty_customer_domain(tmp_path)
    plan = ChangeSetPlan(
        summary="Create invalid customer",
        operations=[
            CreateModel(
                domain="customer",
                name="Customer",
                model_kind="entity",
                fields=[FieldSpec(name="name", type=PrimitiveType(kind="string"))],
            )
        ],
    )

    with pytest.raises(WorkspaceEditError, match="exactly one @key"):
        WorkspaceEditor(tmp_path).preview(plan)

    assert source.read_text(encoding="utf-8") == original


def test_preview_rejects_unknown_domain_without_writing(tmp_path) -> None:
    source, original = _write_empty_customer_domain(tmp_path)
    plan = create_customer_plan().model_copy(deep=True)
    operation = plan.operations[0]
    assert isinstance(operation, CreateModel)
    operation.domain = "missing"

    with pytest.raises(WorkspaceEditError, match="Unknown domain"):
        WorkspaceEditor(tmp_path).preview(plan)

    assert source.read_text(encoding="utf-8") == original


def test_preview_is_all_or_nothing_when_later_operation_is_unsupported(tmp_path) -> None:
    source, original = _write_empty_customer_domain(tmp_path)
    plan = create_customer_plan().model_copy(
        update={
            "operations": [
                *create_customer_plan().operations,
                AppendModelVersion(source="customer.Customer@1", version=2),
            ]
        },
        deep=True,
    )

    with pytest.raises(WorkspaceEditError, match="Unsupported workspace operation"):
        WorkspaceEditor(tmp_path).preview(plan)

    assert source.read_text(encoding="utf-8") == original
