from __future__ import annotations

import pytest

from modelable.llm.conversation_plan import (
    AddField,
    AddProjectionField,
    AddProjectionJoin,
    AddSecondaryIndex,
    AppendModelVersion,
    AppendProjectionVersion,
    ChangeFieldType,
    ChangeSetPlan,
    ComputedMappingSpec,
    CreateModel,
    CreateProjection,
    DirectMappingSpec,
    FieldSpec,
    ProjectionFieldSpec,
    ProjectionJoinSpec,
    ProjectionSourceSpec,
    RemoveField,
    RemoveSecondaryIndex,
    RenameDefinition,
    RenameField,
    RetireDefinition,
    SecondaryIndexSpec,
    SetFieldAnnotations,
    SetFieldOptionality,
    SetPrimaryIndex,
    SetProjectionFilter,
    SetProjectionGrouping,
    SetProjectionMapping,
    SetProjectionSource,
)
from modelable.llm.workspace_editor import ChangedDefinition, WorkspaceEditError, WorkspaceEditor
from modelable.parser.ir import AnnKey, AnnPii, ComputedMapping, FieldDef, ObjectType, PrimitiveType
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


def two_file_plan() -> ChangeSetPlan:
    return ChangeSetPlan(
        summary="Create customer and invoice entities",
        operations=[
            CreateModel(
                domain="customer",
                name="Customer",
                model_kind="entity",
                fields=[
                    FieldSpec(
                        name="customerId",
                        type=PrimitiveType(kind="uuid"),
                        annotations=[AnnKey()],
                    )
                ],
            ),
            CreateModel(
                domain="billing",
                name="Invoice",
                model_kind="entity",
                fields=[
                    FieldSpec(
                        name="invoiceId",
                        type=PrimitiveType(kind="uuid"),
                        annotations=[AnnKey()],
                    )
                ],
            ),
        ],
    )


def _write_empty_customer_domain(tmp_path):
    source = tmp_path / "customer.mdl"
    original = 'domain customer {\n  owner: "customer-team"\n}\n'
    source.write_text(original, encoding="utf-8")
    return source, original


def _write_customer_model(tmp_path):
    source = tmp_path / "customer.mdl"
    source.write_text(
        """
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
  entity Customer @ 2 (additive) {
    @key customerId: uuid
  }
}
""".lstrip(),
        encoding="utf-8",
    )
    return source


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


def test_preview_is_all_or_nothing_when_later_operation_cannot_retire_definition(tmp_path) -> None:
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

    with pytest.raises(
        WorkspaceEditError,
        match=(
            r"Cannot retire customer\.Customer@1: the current \.mdl language has no "
            r"published-contract retirement declaration\."
        ),
    ):
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


def test_draft_rename_updates_later_logical_targets(tmp_path) -> None:
    source = tmp_path / "customer.mdl"
    source.write_text(
        """
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
  entity Customer @ 2 (additive) {
    @key customerId: uuid
  }
}
""".lstrip(),
        encoding="utf-8",
    )
    plan = ChangeSetPlan(
        summary="Rename the customer draft",
        edit_mode="draft",
        operations=[
            RenameDefinition(target="customer.Customer@1", new_name="Account"),
            AddField(
                target="customer.Customer@2",
                field=FieldSpec(name="email", type=PrimitiveType(kind="string"), optional=True),
            ),
        ],
    )

    pending = WorkspaceEditor(tmp_path).preview(plan)

    candidate = parse_text_to_ir(pending.candidate_sources[source])
    assert "Customer" not in candidate.domains[0].models
    assert [field.name for field in candidate.domains[0].models["Account"][1].fields] == [
        "customerId",
        "email",
    ]
    assert pending.changed[0] == ChangedDefinition(
        ref="customer.Account@1",
        reason="renamed definition customer.Customer@1",
    )


def test_rename_definition_requires_draft_mode(tmp_path) -> None:
    _write_customer_model(tmp_path)
    plan = ChangeSetPlan(
        summary="Rename a published definition",
        operations=[RenameDefinition(target="customer.Customer@1", new_name="Account")],
    )

    with pytest.raises(
        WorkspaceEditError,
        match=r"Cannot rename customer\.Customer@1; definition renames require draft mode",
    ):
        WorkspaceEditor(tmp_path).preview(plan)


def test_rename_definition_rejects_generated_projection_name_collision(tmp_path) -> None:
    source = tmp_path / "customer.mdl"
    source.write_text(
        """
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
  entity Candidate @ 1 (additive) {
    @key candidateId: uuid
  }
  auto projections Customer @ 1 {
    request
  }
}
""".lstrip(),
        encoding="utf-8",
    )
    plan = ChangeSetPlan(
        summary="Collide with generated projection",
        edit_mode="draft",
        operations=[RenameDefinition(target="customer.Candidate@1", new_name="CustomerRequest")],
    )

    with pytest.raises(
        WorkspaceEditError,
        match=r"Definition customer\.CustomerRequest already exists",
    ):
        WorkspaceEditor(tmp_path).preview(plan)


def test_preview_creates_complete_projection(tmp_path) -> None:
    (tmp_path / "customer.mdl").write_text(
        """
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    email: string
  }
}
""".lstrip(),
        encoding="utf-8",
    )
    billing_source = tmp_path / "billing.mdl"
    billing_original = 'domain billing {\n  owner: "billing-team"\n}\n'
    billing_source.write_text(billing_original, encoding="utf-8")
    plan = ChangeSetPlan(
        summary="Create a billing customer projection",
        operations=[
            CreateProjection(
                domain="billing",
                name="BillingCustomer",
                version=1,
                source=ProjectionSourceSpec(
                    model="customer.Customer",
                    version=1,
                    alias="c",
                ),
                fields=[
                    ProjectionFieldSpec(
                        name="customerId",
                        mapping=DirectMappingSpec(source_alias="c", source_field="customerId"),
                    ),
                    ProjectionFieldSpec(
                        name="normalizedEmail",
                        mapping=ComputedMappingSpec(expression="lower(c.email)"),
                    ),
                ],
            )
        ],
    )

    pending = WorkspaceEditor(tmp_path).preview(plan)

    candidate = pending.candidate_sources[billing_source]
    assert "projection BillingCustomer @ 1" in candidate
    assert "from customer.Customer @ 1 as c" in candidate
    assert "customerId <- c.customerId" in candidate
    assert "normalizedEmail = lower(c.email)" in candidate
    assert pending.changed == [ChangedDefinition(ref="billing.BillingCustomer@1", reason="created projection")]
    assert pending.diagnostics == []
    assert billing_source.read_text(encoding="utf-8") == billing_original


def test_append_projection_version_preserves_existing_version(tmp_path) -> None:
    source = tmp_path / "workspace.mdl"
    original = """
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    email: string
  }
}
domain billing {
  owner: "billing-team"
  projection BillingCustomer @ 1
    from customer.Customer @ 1 as c
  {
    reserved protobuf {
      numbers: [9]
    }
    customerId <- c.customerId
    email <- c.email
  }
}
""".lstrip()
    source.write_text(original, encoding="utf-8")
    plan = ChangeSetPlan(
        summary="Append BillingCustomer version 2",
        operations=[
            AppendProjectionVersion(
                source="billing.BillingCustomer@1",
                version=2,
            )
        ],
    )

    pending = WorkspaceEditor(tmp_path).preview(plan)

    candidate = parse_text_to_ir(pending.candidate_sources[source])
    versions = candidate.domains[1].projections["BillingCustomer"]
    assert [version.version for version in versions] == [1, 2]
    assert versions[0].protobuf_reservations is not None
    assert versions[1].protobuf_reservations is None
    assert pending.changed == [
        ChangedDefinition(
            ref="billing.BillingCustomer@2",
            reason="appended from billing.BillingCustomer@1",
        )
    ]
    assert source.read_text(encoding="utf-8") == original


def test_appended_projection_supports_structure_and_field_edits(tmp_path) -> None:
    source = tmp_path / "workspace.mdl"
    source.write_text(
        """
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    email: string
  }
  entity Customer @ 2 (additive) {
    @key customerId: uuid
    email: string
  }
}
domain billing {
  owner: "billing-team"
  projection BillingCustomer @ 1
    from customer.Customer @ 1 as c
  {
    customerId <- c.customerId
    email <- c.email
  }
}
""".lstrip(),
        encoding="utf-8",
    )
    plan = ChangeSetPlan(
        summary="Revise BillingCustomer",
        operations=[
            AppendProjectionVersion(source="billing.BillingCustomer@1", version=2),
            SetProjectionSource(
                target="billing.BillingCustomer@2",
                source=ProjectionSourceSpec(model="customer.Customer", version=2, alias="c"),
            ),
            RenameField(
                target="billing.BillingCustomer@2",
                field="email",
                new_name="normalizedEmail",
            ),
            SetProjectionMapping(
                target="billing.BillingCustomer@2",
                field="normalizedEmail",
                mapping=ComputedMappingSpec(expression="lower(c.email)"),
            ),
            AddProjectionField(
                target="billing.BillingCustomer@2",
                field=ProjectionFieldSpec(
                    name="displayEmail",
                    mapping=DirectMappingSpec(source_alias="c", source_field="email"),
                ),
            ),
            SetFieldAnnotations(
                target="billing.BillingCustomer@2",
                field="normalizedEmail",
                annotations=[AnnPii()],
            ),
            AddProjectionJoin(
                target="billing.BillingCustomer@2",
                join=ProjectionJoinSpec(
                    model="customer.Customer",
                    version=2,
                    alias="parent",
                    on="c.customerId == parent.customerId",
                    join_kind="left",
                    cardinality="many_to_one",
                    annotations=[AnnPii()],
                ),
            ),
            SetProjectionFilter(
                target="billing.BillingCustomer@2",
                expression='c.email != ""',
            ),
            SetProjectionGrouping(
                target="billing.BillingCustomer@2",
                fields=["c.customerId"],
            ),
            RemoveField(
                target="billing.BillingCustomer@2",
                field="displayEmail",
            ),
        ],
    )

    pending = WorkspaceEditor(tmp_path).preview(plan)

    candidate = parse_text_to_ir(pending.candidate_sources[source])
    versions = candidate.domains[1].projections["BillingCustomer"]
    assert versions[0].source.version.version == 1
    assert [field.name for field in versions[0].fields] == ["customerId", "email"]
    assert versions[1].source.version.version == 2
    assert versions[1].where == 'c.email != ""'
    assert versions[1].group_by == ["c.customerId"]
    assert versions[1].joins[0].alias == "parent"
    assert versions[1].joins[0].join_kind == "left"
    assert versions[1].joins[0].cardinality == "many_to_one"
    assert versions[1].joins[0].annotations == [AnnPii()]
    assert [field.name for field in versions[1].fields] == ["customerId", "normalizedEmail"]
    assert versions[1].fields[1].mapping == ComputedMapping(expression="lower(c.email)")
    assert versions[1].fields[1].annotations == [AnnPii()]


def test_preview_stages_multiple_files_and_reports_transitive_projection_impact(tmp_path) -> None:
    customer_source = tmp_path / "customer.mdl"
    billing_source = tmp_path / "billing.mdl"
    analytics_source = tmp_path / "analytics.mdl"
    customer_original = """
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""".lstrip()
    billing_original = """
domain billing {
  owner: "billing-team"
  projection BillingCustomer @ 1
    from customer.Customer @ 1 as c
  {
    customerId <- c.customerId
  }
}
""".lstrip()
    analytics_original = """
domain analytics {
  owner: "analytics-team"
  projection CustomerSummary @ 1
    from billing.BillingCustomer @ 1 as c
  {
    customerId <- c.customerId
  }
}
""".lstrip()
    customer_source.write_text(customer_original, encoding="utf-8")
    billing_source.write_text(billing_original, encoding="utf-8")
    analytics_source.write_text(analytics_original, encoding="utf-8")
    plan = ChangeSetPlan(
        summary="Add loyalty data and update the billing projection",
        operations=[
            AppendModelVersion(source="customer.Customer@1", version=2),
            AddField(
                target="customer.Customer@2",
                field=FieldSpec(name="loyaltyTier", type=PrimitiveType(kind="string")),
            ),
            AppendProjectionVersion(source="billing.BillingCustomer@1", version=2),
            SetProjectionSource(
                target="billing.BillingCustomer@2",
                source=ProjectionSourceSpec(model="customer.Customer", version=2, alias="c"),
            ),
        ],
    )

    pending = WorkspaceEditor(tmp_path).preview(plan)

    assert set(pending.candidate_sources) == {customer_source, billing_source}
    assert str(customer_source) in pending.diff_text
    assert str(billing_source) in pending.diff_text
    assert [definition.ref for definition in pending.affected] == [
        "analytics.CustomerSummary@1",
        "billing.BillingCustomer@1",
    ]
    assert len({definition.ref for definition in pending.affected}) == len(pending.affected)
    assert not pending.diagnostics
    assert customer_source.read_text(encoding="utf-8") == customer_original
    assert billing_source.read_text(encoding="utf-8") == billing_original
    assert analytics_source.read_text(encoding="utf-8") == analytics_original


def test_rename_reports_dependents_of_every_version_and_remaps_projection_source(tmp_path) -> None:
    source = tmp_path / "workspace.mdl"
    source.write_text(
        """
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
  entity Customer @ 2 (additive) {
    @key customerId: uuid
  }
}
domain billing {
  owner: "billing-team"
  projection BillingCustomer @ 1
    from customer.Customer @ 2 as c
  {
    customerId <- c.customerId
  }
}
""".lstrip(),
        encoding="utf-8",
    )
    plan = ChangeSetPlan(
        summary="Rename every customer version",
        edit_mode="draft",
        operations=[
            RenameDefinition(target="customer.Customer@1", new_name="Account"),
            SetProjectionSource(
                target="billing.BillingCustomer@1",
                source=ProjectionSourceSpec(model="customer.Customer", version=2, alias="c"),
            ),
        ],
    )

    pending = WorkspaceEditor(tmp_path).preview(plan)

    candidate = parse_text_to_ir(pending.candidate_sources[source])
    assert [version.version for version in candidate.domains[0].models["Account"]] == [1, 2]
    assert candidate.domains[1].projections["BillingCustomer"][0].source.model == "customer.Account"
    assert [definition.ref for definition in pending.affected] == ["billing.BillingCustomer@1"]


def test_rename_remaps_later_append_source(tmp_path) -> None:
    source = _write_customer_model(tmp_path)
    plan = ChangeSetPlan(
        summary="Rename and append the customer",
        edit_mode="draft",
        operations=[
            RenameDefinition(target="customer.Customer@1", new_name="Account"),
            AppendModelVersion(source="customer.Customer@2", version=3),
        ],
    )

    pending = WorkspaceEditor(tmp_path).preview(plan)

    candidate = parse_text_to_ir(pending.candidate_sources[source])
    assert [version.version for version in candidate.domains[0].models["Account"]] == [1, 2, 3]


def test_projection_rename_reports_all_versions_and_remaps_later_references(tmp_path) -> None:
    source = tmp_path / "workspace.mdl"
    source.write_text(
        """
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
domain billing {
  owner: "billing-team"
  projection BillingCustomer @ 1
    from customer.Customer @ 1 as c
  {
    customerId <- c.customerId
  }
  projection BillingCustomer @ 2
    from customer.Customer @ 1 as c
  {
    customerId <- c.customerId
  }
}
domain analytics {
  owner: "analytics-team"
  projection CustomerSummary @ 1
    from billing.BillingCustomer @ 2 as c
  {
    customerId <- c.customerId
  }
}
""".lstrip(),
        encoding="utf-8",
    )
    plan = ChangeSetPlan(
        summary="Rename and append the billing projection",
        edit_mode="draft",
        operations=[
            RenameDefinition(target="billing.BillingCustomer@1", new_name="AccountView"),
            AppendProjectionVersion(source="billing.BillingCustomer@2", version=3),
            SetProjectionSource(
                target="analytics.CustomerSummary@1",
                source=ProjectionSourceSpec(model="billing.BillingCustomer", version=2, alias="c"),
            ),
        ],
    )

    pending = WorkspaceEditor(tmp_path).preview(plan)

    candidate = parse_text_to_ir(pending.candidate_sources[source])
    assert [version.version for version in candidate.domains[1].projections["AccountView"]] == [1, 2, 3]
    assert candidate.domains[2].projections["CustomerSummary"][0].source.model == "billing.AccountView"
    assert [definition.ref for definition in pending.affected] == ["analytics.CustomerSummary@1"]


def test_affected_deduplication_preserves_strongest_impact(tmp_path) -> None:
    source = tmp_path / "workspace.mdl"
    source.write_text(
        """
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    email: string
  }
}
domain billing {
  owner: "billing-team"
  entity Account @ 1 (additive) {
    @key accountId: uuid
  }
  projection CustomerAccount @ 1
    from customer.Customer @ 1 as c
    join billing.Account @ 1 as a on c.customerId == a.accountId
  {
    email <- c.email
  }
}
""".lstrip(),
        encoding="utf-8",
    )
    plan = ChangeSetPlan(
        summary="Break both projection inputs",
        operations=[
            AppendModelVersion(source="billing.Account@1", version=2),
            AddField(
                target="billing.Account@2",
                field=FieldSpec(name="tier", type=PrimitiveType(kind="string")),
            ),
            AppendModelVersion(source="customer.Customer@1", version=2),
            RemoveField(target="customer.Customer@2", field="email"),
        ],
    )

    pending = WorkspaceEditor(tmp_path).preview(plan)

    assert len(pending.affected) == 1
    assert pending.affected[0].ref == "billing.CustomerAccount@1"
    assert pending.affected[0].status == "broken"
    assert "email" in pending.affected[0].reason
