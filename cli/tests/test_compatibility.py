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
          owner: "test-team"
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
          owner: "test-team"
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
          owner: "test-team"
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
          owner: "test-team"
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
          owner: "test-team"
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
          owner: "test-team"
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
          owner: "test-team"
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
          owner: "test-team"
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
          owner: "test-team"
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


def test_optional_to_required_is_breaking():
    mdl = parse_text_to_ir(
        """
        domain customer {
          owner: "test-team"
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            email?: string
          }
          entity Customer @ 2 (breaking) {
            @key customerId: uuid
            email: string
          }
        }
        """
    )

    from modelable.compat.checker import check_model_version_compatibility

    report = check_model_version_compatibility(mdl, "customer", "Customer", 1, 2)
    assert report.status == "breaking"
    assert any("nullability_changed email" in finding for finding in report.findings)


def test_required_to_optional_is_compatible():
    mdl = parse_text_to_ir(
        """
        domain customer {
          owner: "test-team"
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            email: string
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
    assert any("nullability_changed email" in finding for finding in report.findings)


def test_compare_model_versions_reports_enum_and_identity_changes():
    mdl = parse_text_to_ir(
        """
        domain customer {
          owner: "test-team"
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
          owner: "test-team"
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


def test_compatibility_status_is_based_on_structure_not_declared_change_kind():
    mdl = parse_text_to_ir(
        """
        domain customer {
          owner: "test-team"
          entity Customer @ 1 (breaking) {
            @key customerId: uuid
            name: string
          }
          entity Customer @ 2 (breaking) {
            @key customerId: uuid
            name: string
          }
        }
        """
    )

    from modelable.compat.checker import check_model_version_compatibility

    report = check_model_version_compatibility(mdl, "customer", "Customer", 1, 2)
    assert report.status == "compatible"
    assert report.findings == []


def test_find_projection_dependents_is_public_and_includes_joined_sources():
    mdl = parse_text_to_ir(
        """
        domain customer {
          owner: "customer-team"
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            name: string
          }
        }
        domain billing {
          owner: "billing-team"
          entity Invoice @ 1 (additive) {
            @key invoiceId: uuid
            customerId: uuid
          }
        }
        domain reporting {
          owner: "reporting-team"
          projection JoinedCustomer @ 1
            from billing.Invoice @ 1 as i
            join customer.Customer @ 1 as c on i.customerId == c.customerId
          {
            customerName <- c.name
          }
          projection DirectCustomer @ 1
            from customer.Customer @ 1 as c
          {
            customerName <- c.name
          }
        }
        """
    )

    from modelable.compat import find_projection_dependents

    assert find_projection_dependents(mdl, "customer.Customer@1") == [
        ("reporting", "DirectCustomer", 1),
        ("reporting", "JoinedCustomer", 1),
    ]


def _dependent_impact(mdl_text, from_version, to_version, dependent):
    mdl = parse_text_to_ir(mdl_text)

    from modelable.compat.checker import analyze_impact, check_model_version_compatibility

    report = check_model_version_compatibility(mdl, "customer", "Customer", from_version, to_version)
    return analyze_impact(mdl, report, dependent)


def test_analyze_impact_detects_computed_expression_dependency():
    impact = _dependent_impact(
        """
        domain customer {
          owner: "test-team"
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            status: string
          }
          entity Customer @ 2 (breaking) {
            @key customerId: uuid
          }
        }
        domain billing {
          owner: "test-team"
          projection BillingCustomer @ 1
            from customer.Customer @ 1 as c
          {
            id <- c.customerId
            isBillable = c.status == "active"
          }
        }
        """,
        1,
        2,
        ("billing", "BillingCustomer", 1),
    )

    assert impact.status == "broken"
    assert "field 'status' (removed_field)" in impact.reason


def test_analyze_impact_detects_join_predicate_dependency():
    impact = _dependent_impact(
        """
        domain customer {
          owner: "test-team"
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            legacyId: string
          }
          entity Customer @ 2 (breaking) {
            @key customerId: uuid
          }
        }
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            legacyCustomerId: string
          }
        }
        domain billing {
          owner: "test-team"
          projection OrderWithCustomer @ 1
            from orders.Order @ 1 as o
            join customer.Customer @ 1 as c on o.legacyCustomerId == c.legacyId
          {
            orderId <- o.orderId
          }
        }
        """,
        1,
        2,
        ("billing", "OrderWithCustomer", 1),
    )

    assert impact.status == "broken"
    assert "field 'legacyId' (removed_field)" in impact.reason


def test_analyze_impact_detects_where_filter_dependency():
    impact = _dependent_impact(
        """
        domain customer {
          owner: "test-team"
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            status: string
          }
          entity Customer @ 2 (breaking) {
            @key customerId: uuid
          }
        }
        domain billing {
          owner: "test-team"
          projection BillingCustomer @ 1
            from customer.Customer @ 1 as c
            where c.status == "active"
          {
            id <- c.customerId
          }
        }
        """,
        1,
        2,
        ("billing", "BillingCustomer", 1),
    )

    assert impact.status == "broken"
    assert "field 'status' (removed_field)" in impact.reason


def test_analyze_impact_detects_group_by_dependency():
    impact = _dependent_impact(
        """
        domain customer {
          owner: "test-team"
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            region: string
          }
          entity Customer @ 2 (breaking) {
            @key customerId: uuid
          }
        }
        domain billing {
          owner: "test-team"
          projection CustomersByRegion @ 1
            from customer.Customer @ 1 as c
            group by c.region
          {
            customerCount = count(c.customerId)
          }
        }
        """,
        1,
        2,
        ("billing", "CustomersByRegion", 1),
    )

    assert impact.status == "broken"
    assert "field 'region' (removed_field)" in impact.reason


def test_find_projection_dependents_includes_range_versioned_source():
    mdl = parse_text_to_ir(
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
            from customer.Customer @ >=1 <3 as c
          {
            id <- c.customerId
          }
        }
        """
    )

    from modelable.compat.checker import find_projection_dependents

    # The range >=1 <3 resolves to version 2 today, so BillingCustomer depends
    # on customer.Customer@2, not @1.
    assert find_projection_dependents(mdl, "customer.Customer@2") == [("billing", "BillingCustomer", 1)]
    assert find_projection_dependents(mdl, "customer.Customer@1") == []


def test_index_changed_is_visible_when_secondary_index_added():
    mdl = parse_text_to_ir(
        """
        domain platform {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
                 status:  string
          }
          entity Order @ 2 (additive) {
            @key orderId: uuid
                 status:  string
          }
          index Order @ 2 {
            primary orderId
            secondary byStatus {
              key: [status]
            }
          }
        }
        """
    )

    from modelable.compat.checker import check_model_version_compatibility

    report = check_model_version_compatibility(mdl, "platform", "Order", 1, 2)
    assert any(change.kind == "index_changed" for change in report.changes)


def test_index_changed_is_not_flagged_when_neither_version_has_one():
    mdl = parse_text_to_ir(
        """
        domain platform {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
          }
          entity Order @ 2 (additive) {
            @key orderId: uuid
                 status:  string
          }
        }
        """
    )

    from modelable.compat.checker import check_model_version_compatibility

    report = check_model_version_compatibility(mdl, "platform", "Order", 1, 2)
    assert not any(change.kind == "index_changed" for change in report.changes)
