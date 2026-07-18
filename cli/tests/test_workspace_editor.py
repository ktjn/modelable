from __future__ import annotations

import pytest

from modelable.llm.conversation_plan import (
    AddField,
    AddSecondaryIndex,
    AppendModelVersion,
    ChangeFieldType,
    ChangeSetPlan,
    CreateModel,
    FieldSpec,
    RemoveField,
    RemoveSecondaryIndex,
    RenameField,
    RetireDefinition,
    SecondaryIndexSpec,
    SetFieldAnnotations,
    SetFieldOptionality,
    SetPrimaryIndex,
)
from modelable.llm.workspace_editor import ChangedDefinition, WorkspaceEditError, WorkspaceEditor
from modelable.parser.ir import AnnKey, AnnPii, FieldDef, ObjectType, PrimitiveType
from modelable.parser.parse import parse_text_to_ir


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
                RetireDefinition(target="customer.Customer@1"),
            ]
        },
        deep=True,
    )

    with pytest.raises(WorkspaceEditError, match="Unsupported workspace operation"):
        WorkspaceEditor(tmp_path).preview(plan)

    assert source.read_text(encoding="utf-8") == original


def test_append_model_version_classifies_and_reports_dependents(tmp_path) -> None:
    customer_source = tmp_path / "customer.mdl"
    customer_source.write_text(
        """
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    name: string
  }
}
""".lstrip(),
        encoding="utf-8",
    )
    (tmp_path / "billing.mdl").write_text(
        """
domain billing {
  owner: "billing-team"
  projection BillingCustomer @ 1
    from customer.Customer @ 1 as c
  {
    customerId <- c.customerId
    name <- c.name
  }
}
""".lstrip(),
        encoding="utf-8",
    )
    plan = ChangeSetPlan(
        summary="Add required loyaltyTier",
        operations=[
            AppendModelVersion(source="customer.Customer@1", version=2),
            AddField(
                target="customer.Customer@2",
                field=FieldSpec(
                    name="loyaltyTier",
                    type=PrimitiveType(kind="string"),
                    optional=False,
                ),
            ),
        ],
    )

    pending = WorkspaceEditor(tmp_path).preview(plan)

    candidate = pending.candidate_sources[customer_source]
    assert "entity Customer @ 1 (additive)" in candidate
    assert "entity Customer @ 2 (breaking)" in candidate
    assert any(item.ref == "billing.BillingCustomer@1" for item in pending.affected)
    assert any(item.status == "breaking" for item in pending.compatibility)


def test_existing_model_version_requires_explicit_draft_mode_and_warns(tmp_path) -> None:
    source = tmp_path / "customer.mdl"
    original = """
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""".lstrip()
    source.write_text(original, encoding="utf-8")
    operation = AddField(
        target="customer.Customer@1",
        field=FieldSpec(name="email", type=PrimitiveType(kind="string"), optional=True),
    )

    with pytest.raises(WorkspaceEditError, match="append a new version or use draft mode"):
        WorkspaceEditor(tmp_path).preview(
            ChangeSetPlan(summary="Add email", operations=[operation]),
        )

    pending = WorkspaceEditor(tmp_path).preview(
        ChangeSetPlan(
            summary="Add email to the local draft",
            edit_mode="draft",
            operations=[operation],
        ),
    )

    assert "email?: string" in pending.candidate_sources[source]
    assert any("local publication state is not known" in assumption for assumption in pending.assumptions)
    assert source.read_text(encoding="utf-8") == original


@pytest.mark.parametrize(
    ("operation", "expected_fields"),
    [
        (
            RenameField(
                target="customer.Customer@2",
                field="name",
                new_name="displayName",
            ),
            [
                FieldDef(name="customerId", type=PrimitiveType(kind="uuid"), annotations=[AnnKey()]),
                FieldDef(name="displayName", type=PrimitiveType(kind="string")),
            ],
        ),
        (
            RemoveField(target="customer.Customer@2", field="name"),
            [FieldDef(name="customerId", type=PrimitiveType(kind="uuid"), annotations=[AnnKey()])],
        ),
        (
            ChangeFieldType(
                target="customer.Customer@2",
                field="name",
                type=PrimitiveType(kind="int"),
            ),
            [
                FieldDef(name="customerId", type=PrimitiveType(kind="uuid"), annotations=[AnnKey()]),
                FieldDef(name="name", type=PrimitiveType(kind="int")),
            ],
        ),
        (
            SetFieldOptionality(
                target="customer.Customer@2",
                field="name",
                optional=True,
            ),
            [
                FieldDef(name="customerId", type=PrimitiveType(kind="uuid"), annotations=[AnnKey()]),
                FieldDef(name="name", type=PrimitiveType(kind="string"), optional=True),
            ],
        ),
        (
            SetFieldAnnotations(
                target="customer.Customer@2",
                field="name",
                annotations=[AnnPii()],
            ),
            [
                FieldDef(name="customerId", type=PrimitiveType(kind="uuid"), annotations=[AnnKey()]),
                FieldDef(name="name", type=PrimitiveType(kind="string"), annotations=[AnnPii()]),
            ],
        ),
    ],
)
def test_appended_model_supports_field_edit_operations(tmp_path, operation, expected_fields) -> None:
    source = tmp_path / "customer.mdl"
    source.write_text(
        """
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    name: string
  }
}
""".lstrip(),
        encoding="utf-8",
    )
    plan = ChangeSetPlan(
        summary="Revise Customer",
        operations=[
            AppendModelVersion(source="customer.Customer@1", version=2),
            operation,
        ],
    )

    pending = WorkspaceEditor(tmp_path).preview(plan)

    candidate = parse_text_to_ir(pending.candidate_sources[source])
    version = next(item for item in candidate.domains[0].models["Customer"] if item.version == 2)
    assert version.fields == expected_fields


def test_append_model_version_copies_and_edits_indexes(tmp_path) -> None:
    source = tmp_path / "customer.mdl"
    source.write_text(
        """
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    name: string
  }
  index Customer @ 1 {
    primary customerId
    secondary byName {
      key: [name]
    }
  }
}
""".lstrip(),
        encoding="utf-8",
    )
    plan = ChangeSetPlan(
        summary="Replace the customer lookup index",
        operations=[
            AppendModelVersion(source="customer.Customer@1", version=2),
            AddField(
                target="customer.Customer@2",
                field=FieldSpec(
                    name="email",
                    type=PrimitiveType(kind="string"),
                    optional=True,
                ),
            ),
            SetPrimaryIndex(target="customer.Customer@2", fields=["customerId"]),
            RemoveSecondaryIndex(target="customer.Customer@2", name="byName"),
            AddSecondaryIndex(
                target="customer.Customer@2",
                index=SecondaryIndexSpec(name="byEmail", key=["email"], unique=True),
            ),
        ],
    )

    pending = WorkspaceEditor(tmp_path).preview(plan)

    candidate = parse_text_to_ir(pending.candidate_sources[source])
    indexes = {
        (declaration.model, declaration.version): declaration for declaration in candidate.domains[0].index_decls
    }
    assert indexes[("Customer", 1)].secondary[0].name == "byName"
    assert indexes[("Customer", 2)].primary == ["customerId"]
    assert [index.name for index in indexes[("Customer", 2)].secondary] == ["byEmail"]
    assert indexes[("Customer", 2)].secondary[0].unique is True


def test_add_secondary_index_rejects_duplicate_name_before_staging(tmp_path) -> None:
    source = tmp_path / "customer.mdl"
    original = """
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    name: string
  }
  index Customer @ 1 {
    primary customerId
    secondary byName {
      key: [name]
    }
  }
}
""".lstrip()
    source.write_text(original, encoding="utf-8")
    plan = ChangeSetPlan(
        summary="Duplicate customer lookup",
        operations=[
            AppendModelVersion(source="customer.Customer@1", version=2),
            AddSecondaryIndex(
                target="customer.Customer@2",
                index=SecondaryIndexSpec(name="byName", key=["name"]),
            ),
        ],
    )

    with pytest.raises(WorkspaceEditError, match="Secondary index byName already exists"):
        WorkspaceEditor(tmp_path).preview(plan)

    assert source.read_text(encoding="utf-8") == original


def test_append_model_version_clears_version_local_protobuf_reservations(tmp_path) -> None:
    source = tmp_path / "customer.mdl"
    source.write_text(
        """
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    reserved protobuf {
      numbers: [9]
      names: ["legacy_name"]
    }
    @key customerId: uuid
  }
}
""".lstrip(),
        encoding="utf-8",
    )
    plan = ChangeSetPlan(
        summary="Append Customer version 2",
        operations=[AppendModelVersion(source="customer.Customer@1", version=2)],
    )

    pending = WorkspaceEditor(tmp_path).preview(plan)

    candidate = parse_text_to_ir(pending.candidate_sources[source])
    versions = candidate.domains[0].models["Customer"]
    assert versions[0].protobuf_reservations is not None
    assert versions[1].protobuf_reservations is None


def test_append_model_version_requires_the_next_available_version(tmp_path) -> None:
    source = tmp_path / "customer.mdl"
    original = """
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""".lstrip()
    source.write_text(original, encoding="utf-8")
    plan = ChangeSetPlan(
        summary="Skip Customer version 2",
        operations=[AppendModelVersion(source="customer.Customer@1", version=3)],
    )

    with pytest.raises(WorkspaceEditError, match="expected 2"):
        WorkspaceEditor(tmp_path).preview(plan)

    assert source.read_text(encoding="utf-8") == original
