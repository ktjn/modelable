from modelable.compat.checker import ProjectionCompatibilityReport, check_projection_version_compatibility
from modelable.compat.diff import (
    _compare_governance,
    _compare_lineage,
    _compare_shape,
    _compare_storage,
    _compare_wire,
    compare_projection_versions,
)
from modelable.parser.parse import parse_text_to_ir


def _projection(mdl_text: str, name: str = "OrderView"):
    mdl = parse_text_to_ir(mdl_text)
    domain = mdl.domains[0]
    return mdl, domain.projections[name][0]


def _two_versions(old_text: str, new_text: str, name: str = "OrderView"):
    """Parse two separately-authored .mdl snippets as if they were the same
    projection at two points in time. Returns (new_mdl, old, new): only
    new_mdl is kept, so this is only valid when the source model's fields
    are IDENTICAL between old_text and new_text — true for every
    lineage/governance/wire/storage test (they compare projection-level
    properties: mappings, access, wire hints, where/group_by/joins — none
    of them resolve a field's type through the source model at all, so
    `_compare_lineage`/`_compare_governance`/`_compare_wire`/`_compare_storage`
    don't even take an `mdl` parameter). For a shape/type-resolution test
    where the source model's fields must actually differ between old and
    new, don't use this helper — declare both model versions explicitly in
    one shared .mdl text instead (see test_type_changed_is_breaking)."""
    _, old = _projection(old_text, name)
    new_mdl, new = _projection(new_text, name)
    return new_mdl, old, new


def test_field_removed_is_breaking():
    mdl, old, new = _two_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            status: string
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            status <- o.status
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
          }
        }
        """,
    )

    changes = _compare_shape(mdl, old, new)

    assert any(c.kind == "field_removed" and c.breaking and c.field_name == "status" for c in changes)


def test_field_added_is_not_breaking():
    mdl, old, new = _two_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            status: string
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            status <- o.status
          }
        }
        """,
    )

    changes = _compare_shape(mdl, old, new)

    assert any(c.kind == "field_added" and not c.breaking and c.field_name == "status" for c in changes)


def test_type_changed_is_breaking():
    # A model version's own definition never changes once published, so
    # testing "the source field's resolved type differs" must declare TWO
    # distinct model versions (and two projection versions sourcing them)
    # in one shared .mdl text, not two independently-parsed snippets — a
    # single merged `mdl` is what `resolve_projection_field_type_and_optionality`
    # actually needs to tell old and new apart. This mirrors the existing
    # precedent in cli/tests/test_cli.py::test_diff_reports_breaking_changes
    # (`entity Customer @ 1 { ... } entity Customer @ 2 { ... }` in one block).
    mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      entity Order @ 1 (additive) {
        @key orderId: uuid
        quantity: int
      }
      entity Order @ 2 (additive) {
        @key orderId: uuid
        quantity: string
      }
      projection OrderView @ 1 from orders.Order @ 1 as o {
        orderId <- o.orderId
        quantity <- o.quantity
      }
      projection OrderView @ 2 from orders.Order @ 2 as o {
        orderId <- o.orderId
        quantity <- o.quantity
      }
    }
    """)
    domain = mdl.domains[0]
    old = domain.projections["OrderView"][0]
    new = domain.projections["OrderView"][1]

    changes = _compare_shape(mdl, old, new)

    assert any(c.kind == "type_changed" and c.breaking and c.field_name == "quantity" for c in changes)


def test_optional_to_required_is_breaking():
    mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      entity Order @ 1 (additive) {
        @key orderId: uuid
        note?: string
      }
      entity Order @ 2 (additive) {
        @key orderId: uuid
        note: string
      }
      projection OrderView @ 1 from orders.Order @ 1 as o {
        orderId <- o.orderId
        note <- o.note
      }
      projection OrderView @ 2 from orders.Order @ 2 as o {
        orderId <- o.orderId
        note <- o.note
      }
    }
    """)
    domain = mdl.domains[0]
    old = domain.projections["OrderView"][0]
    new = domain.projections["OrderView"][1]

    changes = _compare_shape(mdl, old, new)

    assert any(c.kind == "optionality_changed" and c.breaking and c.field_name == "note" for c in changes)


def test_required_to_optional_is_not_breaking():
    mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      entity Order @ 1 (additive) {
        @key orderId: uuid
        note: string
      }
      entity Order @ 2 (additive) {
        @key orderId: uuid
        note?: string
      }
      projection OrderView @ 1 from orders.Order @ 1 as o {
        orderId <- o.orderId
        note <- o.note
      }
      projection OrderView @ 2 from orders.Order @ 2 as o {
        orderId <- o.orderId
        note <- o.note
      }
    }
    """)
    domain = mdl.domains[0]
    old = domain.projections["OrderView"][0]
    new = domain.projections["OrderView"][1]

    changes = _compare_shape(mdl, old, new)

    assert any(c.kind == "optionality_changed" and not c.breaking and c.field_name == "note" for c in changes)


def test_unchanged_fields_produce_no_shape_changes():
    mdl, old, new = _two_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
          }
        }
        """,
    )

    assert _compare_shape(mdl, old, new) == []


def test_remapped_source_field_is_visible_but_not_breaking():
    _mdl, old, new = _two_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            legacyStatus: string
            status: string
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            status <- o.legacyStatus
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            legacyStatus: string
            status: string
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            status <- o.status
          }
        }
        """,
    )

    changes = _compare_lineage(old, new)

    assert any(c.kind == "source_remapped" and not c.breaking and c.field_name == "status" for c in changes)


def test_expression_text_changed_is_visible_but_not_breaking():
    _mdl, old, new = _two_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            status: string
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            isShipped = o.status == "shipped"
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            status: string
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            isShipped = o.status == "delivered"
          }
        }
        """,
    )

    changes = _compare_lineage(old, new)

    assert any(c.kind == "expression_changed" and not c.breaking and c.field_name == "isShipped" for c in changes)


def test_unchanged_lineage_produces_no_changes():
    _mdl, old, new = _two_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
          }
        }
        """,
    )

    assert _compare_lineage(old, new) == []


def test_access_grant_removed_is_breaking():
    _mdl, old, new = _two_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            access {
              entity billing-team [read]
            }
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
          }
        }
        """,
    )

    changes = _compare_governance(old, new)

    assert any(c.kind == "access_grant_removed" and c.breaking for c in changes)


def test_access_grant_added_is_not_breaking():
    _mdl, old, new = _two_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            access {
              entity billing-team [read]
            }
          }
        }
        """,
    )

    changes = _compare_governance(old, new)

    assert any(c.kind == "access_grant_added" and not c.breaking for c in changes)


def test_classification_tightened_is_breaking():
    _mdl, old, new = _two_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            note: string
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            @classification("open")
            note <- o.note
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            note: string
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            @classification("confidential")
            note <- o.note
          }
        }
        """,
    )

    changes = _compare_governance(old, new)

    assert any(c.kind == "classification_changed" and c.breaking and c.field_name == "note" for c in changes)


def test_classification_loosened_is_not_breaking():
    _mdl, old, new = _two_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            note: string
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            @classification("confidential")
            note <- o.note
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            note: string
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            @classification("open")
            note <- o.note
          }
        }
        """,
    )

    changes = _compare_governance(old, new)

    assert any(c.kind == "classification_changed" and not c.breaking and c.field_name == "note" for c in changes)


def test_pii_added_is_breaking():
    _mdl, old, new = _two_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            note: string
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            note <- o.note
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            note: string
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            @pii
            note <- o.note
          }
        }
        """,
    )

    changes = _compare_governance(old, new)

    assert any(c.kind == "pii_changed" and c.breaking and c.field_name == "note" for c in changes)


def test_pii_removed_is_not_breaking():
    _mdl, old, new = _two_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            note: string
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            @pii
            note <- o.note
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            note: string
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            note <- o.note
          }
        }
        """,
    )

    changes = _compare_governance(old, new)

    assert any(c.kind == "pii_changed" and not c.breaking and c.field_name == "note" for c in changes)


def test_wire_hint_value_changed_is_breaking():
    _mdl, old, new = _two_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            createdAt: timestamp
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            @wire(json.fieldCase: "camelCase")
            createdAt <- o.createdAt
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            createdAt: timestamp
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            @wire(json.fieldCase: "snake_case")
            createdAt <- o.createdAt
          }
        }
        """,
    )

    changes = _compare_wire(old, new)

    assert any(c.kind == "wire_hint_changed" and c.breaking and c.field_name == "createdAt" for c in changes)


def test_wire_hint_added_where_none_existed_is_not_breaking():
    _mdl, old, new = _two_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            createdAt: timestamp
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            createdAt <- o.createdAt
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            createdAt: timestamp
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            @wire(json.fieldCase: "snake_case")
            createdAt <- o.createdAt
          }
        }
        """,
    )

    changes = _compare_wire(old, new)

    assert any(c.kind == "wire_hint_added" and not c.breaking and c.field_name == "createdAt" for c in changes)


def test_wire_hint_removed_is_not_breaking():
    _mdl, old, new = _two_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            createdAt: timestamp
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            @wire(json.fieldCase: "snake_case")
            createdAt <- o.createdAt
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            createdAt: timestamp
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            createdAt <- o.createdAt
          }
        }
        """,
    )

    changes = _compare_wire(old, new)

    assert any(c.kind == "wire_hint_removed" and not c.breaking and c.field_name == "createdAt" for c in changes)


def test_where_clause_changed_is_breaking():
    _mdl, old, new = _two_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            status: string
          }
          projection OrderView @ 1
            from orders.Order @ 1 as o
            where o.status == "open"
          {
            orderId <- o.orderId
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            status: string
          }
          projection OrderView @ 1
            from orders.Order @ 1 as o
            where o.status == "closed"
          {
            orderId <- o.orderId
          }
        }
        """,
    )

    changes = _compare_storage(old, new)

    assert any(c.kind == "where_changed" and c.breaking for c in changes)


def test_group_by_changed_is_breaking():
    _mdl, old, new = _two_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            status: string
            customerId: uuid
          }
          projection OrderCounts @ 1
            from orders.Order @ 1 as o
            group by o.status
          {
            status <- o.status
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            status: string
            customerId: uuid
          }
          projection OrderCounts @ 1
            from orders.Order @ 1 as o
            group by o.customerId
          {
            status <- o.status
          }
        }
        """,
        name="OrderCounts",
    )

    changes = _compare_storage(old, new)

    assert any(c.kind == "group_by_changed" and c.breaking for c in changes)


def test_join_added_is_breaking():
    _mdl, old, new = _two_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            customerId: uuid
          }
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            name: string
          }
          projection OrderView @ 1
            from orders.Order @ 1 as o
          {
            orderId <- o.orderId
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            customerId: uuid
          }
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            name: string
          }
          projection OrderView @ 1
            from orders.Order @ 1 as o
            join orders.Customer @ 1 as c on o.customerId == c.customerId
          {
            orderId <- o.orderId
          }
        }
        """,
    )

    changes = _compare_storage(old, new)

    assert any(c.kind == "join_added" and c.breaking and c.field_name == "c" for c in changes)


def test_join_removed_is_breaking():
    _mdl, old, new = _two_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            customerId: uuid
          }
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            name: string
          }
          projection OrderView @ 1
            from orders.Order @ 1 as o
            join orders.Customer @ 1 as c on o.customerId == c.customerId
          {
            orderId <- o.orderId
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            customerId: uuid
          }
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            name: string
          }
          projection OrderView @ 1
            from orders.Order @ 1 as o
          {
            orderId <- o.orderId
          }
        }
        """,
    )

    changes = _compare_storage(old, new)

    assert any(c.kind == "join_removed" and c.breaking and c.field_name == "c" for c in changes)


def test_join_predicate_changed_is_breaking():
    _mdl, old, new = _two_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            customerId: uuid
            altCustomerId: uuid
          }
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            name: string
          }
          projection OrderView @ 1
            from orders.Order @ 1 as o
            join orders.Customer @ 1 as c on o.customerId == c.customerId
          {
            orderId <- o.orderId
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            customerId: uuid
            altCustomerId: uuid
          }
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            name: string
          }
          projection OrderView @ 1
            from orders.Order @ 1 as o
            join orders.Customer @ 1 as c on o.altCustomerId == c.customerId
          {
            orderId <- o.orderId
          }
        }
        """,
    )

    changes = _compare_storage(old, new)

    assert any(c.kind == "join_changed" and c.breaking and c.field_name == "c" for c in changes)


def test_unchanged_storage_produces_no_changes():
    _mdl, old, new = _two_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
          }
          projection OrderView @ 1
            from orders.Order @ 1 as o
          {
            orderId <- o.orderId
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
          }
          projection OrderView @ 1
            from orders.Order @ 1 as o
          {
            orderId <- o.orderId
          }
        }
        """,
    )

    assert _compare_storage(old, new) == []


def test_compare_projection_versions_combines_all_dimensions():
    # note's optionality differs between old and new, so — same reasoning as
    # Task 2's shape tests — this needs two explicit model versions in one
    # shared .mdl text, not two independently-parsed snippets.
    mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      entity Order @ 1 (additive) {
        @key orderId: uuid
        status: string
        note?: string
      }
      entity Order @ 2 (additive) {
        @key orderId: uuid
        status: string
        note: string
        extra: string
      }
      projection OrderView @ 1
        from orders.Order @ 1 as o
        where o.status == "open"
      {
        orderId <- o.orderId
        status <- o.status
        note <- o.note
      }
      projection OrderView @ 2
        from orders.Order @ 2 as o
        where o.status == "closed"
      {
        orderId <- o.orderId
        status <- o.status
        note <- o.note
        extra <- o.extra
      }
    }
    """)
    domain = mdl.domains[0]
    old = domain.projections["OrderView"][0]
    new = domain.projections["OrderView"][1]

    changes = compare_projection_versions(mdl, old, new)
    kinds = {c.kind for c in changes}

    assert "field_added" in kinds  # extra
    assert "optionality_changed" in kinds  # note optional -> required
    assert "where_changed" in kinds
    assert any(c.dimension == "shape" for c in changes)
    assert any(c.dimension == "storage" for c in changes)


def test_check_projection_version_compatibility_reports_breaking_status():
    mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      entity Order @ 1 (additive) {
        @key orderId: uuid
        status: string
      }
      projection OrderView @ 1 from orders.Order @ 1 as o {
        orderId <- o.orderId
        status <- o.status
      }
      projection OrderView @ 2 from orders.Order @ 1 as o {
        orderId <- o.orderId
      }
    }
    """)

    report = check_projection_version_compatibility(mdl, "orders", "OrderView", 1, 2)

    assert isinstance(report, ProjectionCompatibilityReport)
    assert report.status == "breaking"
    assert any("field_removed" in finding for finding in report.findings)


def test_check_projection_version_compatibility_reports_compatible_status():
    mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      entity Order @ 1 (additive) {
        @key orderId: uuid
        status: string
      }
      projection OrderView @ 1 from orders.Order @ 1 as o {
        orderId <- o.orderId
      }
      projection OrderView @ 2 from orders.Order @ 1 as o {
        orderId <- o.orderId
        status <- o.status
      }
    }
    """)

    report = check_projection_version_compatibility(mdl, "orders", "OrderView", 1, 2)

    assert report.status == "compatible"


def test_check_projection_version_compatibility_raises_for_unknown_version():
    mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      entity Order @ 1 (additive) {
        @key orderId: uuid
      }
      projection OrderView @ 1 from orders.Order @ 1 as o {
        orderId <- o.orderId
      }
    }
    """)

    import pytest

    with pytest.raises(LookupError):
        check_projection_version_compatibility(mdl, "orders", "OrderView", 1, 2)


def test_source_version_dimension_mirrors_model_compat_status():
    from modelable.compat.checker import check_model_version_compatibility

    mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      entity Order @ 1 (additive) {
        @key orderId: uuid
        status: string
      }
      entity Order @ 2 (additive) {
        @key orderId: uuid
      }
      projection OrderView @ 1 from orders.Order @ 1 as o {
        orderId <- o.orderId
      }
      projection OrderView @ 2 from orders.Order @ 2 as o {
        orderId <- o.orderId
      }
    }
    """)

    model_report = check_model_version_compatibility(mdl, "orders", "Order", 1, 2)
    projection_report = check_projection_version_compatibility(mdl, "orders", "OrderView", 1, 2)

    source_version_changes = [c for c in projection_report.changes if c.dimension == "source_version"]
    assert len(source_version_changes) == 1
    assert source_version_changes[0].breaking == (model_report.status == "breaking")


def test_source_version_skips_when_alias_resolves_to_different_model_name():
    mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      entity Order @ 1 (additive) {
        @key orderId: uuid
      }
      entity Shipment @ 1 (additive) {
        @key orderId: uuid
      }
      projection OrderView @ 1 from orders.Order @ 1 as o {
        orderId <- o.orderId
      }
      projection OrderView @ 2 from orders.Shipment @ 1 as o {
        orderId <- o.orderId
      }
    }
    """)

    report = check_projection_version_compatibility(mdl, "orders", "OrderView", 1, 2)

    source_version_changes = [c for c in report.changes if c.dimension == "source_version"]
    assert source_version_changes == []
