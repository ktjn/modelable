from modelable.parser.parse import parse_text_to_ir


def _model_version(mdl_text: str, version: int = 1):
    mdl = parse_text_to_ir(mdl_text)
    domain = mdl.domains[0]
    model_name = next(iter(domain.models))
    return next(item for item in domain.models[model_name] if item.version == version)


def test_compare_model_versions_reports_field_add_remove_and_type_changes():
    old_version = _model_version(
        """
        domain customer {
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            name: string
            status: enum(active, blocked)
          }
        }
        """
    )
    new_version = _model_version(
        """
        domain customer {
          entity Customer @ 2 (additive) {
            @key customerId: uuid
            fullName: string
            status: string
            email?: string
          }
        }
        """,
        version=2,
    )

    from modelable.compat.diff import compare_model_versions

    changes = compare_model_versions(old_version, new_version)
    assert [change.kind for change in changes] == [
        "removed_field",
        "type_changed",
        "added_field",
        "added_field",
    ]
    assert changes[0].field_name == "name"
    assert changes[1].field_name == "status"
    assert {changes[2].field_name, changes[3].field_name} == {"fullName", "email"}


def test_compare_model_versions_reports_stable_change_order():
    old_version = _model_version(
        """
        domain customer {
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            name: string
            status: enum(active, blocked)
          }
        }
        """
    )
    new_version = _model_version(
        """
        domain customer {
          entity Customer @ 2 (additive) {
            @key customerId: uuid
            fullName: string
            status: string
            email?: string
          }
        }
        """,
        version=2,
    )

    from modelable.compat.diff import compare_model_versions

    changes = compare_model_versions(old_version, new_version)
    assert [change.kind for change in changes] == [
        "removed_field",
        "type_changed",
        "added_field",
        "added_field",
    ]


def test_compare_model_versions_reports_rename_and_nullability():
    old_version = _model_version(
        """
        domain customer {
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            @deprecated(replacedBy: "fullName") name: string
          }
        }
        """
    )
    new_version = _model_version(
        """
        domain customer {
          entity Customer @ 2 (additive) {
            @key customerId: uuid
            fullName?: string
          }
        }
        """,
        version=2,
    )

    from modelable.compat.diff import compare_model_versions

    changes = compare_model_versions(old_version, new_version)
    assert [change.kind for change in changes] == ["renamed_field", "nullability_changed"]
    assert changes[0].field_name == "name"
    assert changes[0].replacement == "fullName"
    assert changes[1].field_name == "fullName"
    assert changes[1].from_optional is False
    assert changes[1].to_optional is True


def test_additive_declaration_rejects_breaking_changes():
    mdl = parse_text_to_ir(
        """
        domain customer {
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            name: string
          }
          entity Customer @ 2 (additive) {
            @key customerId: uuid
          }
        }
        """
    )

    from modelable.compat.checker import check_model_version_compatibility

    report = check_model_version_compatibility(mdl, "customer", "Customer", 1, 2)
    assert report.status == "breaking"
    assert any("removed_field name" in finding for finding in report.findings)


def test_optional_field_addition_is_compatible():
    mdl = parse_text_to_ir(
        """
        domain customer {
          entity Customer @ 1 (additive) {
            @key customerId: uuid
          }
          entity Customer @ 2 (additive) {
            @key customerId: uuid
            email?: string
          }
        }
        """
    )

    from modelable.compat.checker import check_model_version_compatibility

    report = check_model_version_compatibility(mdl, "customer", "Customer", 1, 2)
    assert report.status == "compatible"
    assert any(change.kind == "added_field" and change.field_name == "email" for change in report.changes)
    assert any("added_field email" in finding for finding in report.findings)


def test_compare_model_versions_reports_required_field_addition_as_breaking():
    mdl = parse_text_to_ir(
        """
        domain customer {
          entity Customer @ 1 (additive) {
            @key customerId: uuid
          }
          entity Customer @ 2 (additive) {
            @key customerId: uuid
            email: string
          }
        }
        """
    )

    from modelable.compat.checker import check_model_version_compatibility

    report = check_model_version_compatibility(mdl, "customer", "Customer", 1, 2)
    assert report.status == "breaking"
    assert any("added_field email" in finding for finding in report.findings)


def test_compare_model_versions_reports_enum_and_identity_changes():
    mdl = parse_text_to_ir(
        """
        domain customer {
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            status: enum(active, blocked)
          }
          entity Customer @ 2 (additive) {
            customerId: uuid
            status: enum(active, blocked, archived)
          }
        }
        """
    )

    from modelable.compat.checker import check_model_version_compatibility

    report = check_model_version_compatibility(mdl, "customer", "Customer", 1, 2)
    assert report.status == "breaking"
    assert any("identity_changed customerId" in finding for finding in report.findings)
    assert any("enum_changed status" in finding for finding in report.findings)


def test_breaking_declaration_can_admit_breaking_changes():
    mdl = parse_text_to_ir(
        """
        domain customer {
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            name: string
          }
          entity Customer @ 2 (breaking) {
            @key customerId: uuid
          }
        }
        """
    )

    from modelable.compat.checker import check_model_version_compatibility

    report = check_model_version_compatibility(mdl, "customer", "Customer", 1, 2)
    assert report.status == "breaking"
    assert any("removed_field name" in finding for finding in report.findings)
