from modelable.compat.diff import ProjectionChange, _compare_shape
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

    assert any(
        c.kind == "optionality_changed" and c.breaking and c.field_name == "note"
        for c in changes
    )


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

    assert any(
        c.kind == "optionality_changed" and not c.breaking and c.field_name == "note"
        for c in changes
    )


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
