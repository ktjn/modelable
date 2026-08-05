from modelable.compat.diff import ProjectionChange, _compare_shape
from modelable.parser.parse import parse_text_to_ir


def _projection(mdl_text: str, name: str = "OrderView"):
    mdl = parse_text_to_ir(mdl_text)
    domain = mdl.domains[0]
    return mdl, domain.projections[name][0]


def _two_versions(old_text: str, new_text: str, name: str = "OrderView"):
    """Parse two separately-authored .mdl snippets as if they were the same
    projection at two points in time. Each snippet must declare a domain
    with matching name so both resolve into one merged view for tests that
    need a single `mdl` (most shape/lineage/governance/wire/storage tests
    only need each side's ProjectionVersion in isolation, not merged)."""
    from modelable.parser.ir import VersionExact

    old_mdl, old = _projection(old_text, name)
    new_mdl, new = _projection(new_text, name)

    # Merge entity versions into a single mdl for shape comparison:
    # old @ 1 stays @ 1, new @ 1 becomes @ 2 so both exist in the mdl
    # This allows resolve_projection_field_type_and_optionality to find the correct version for each projection
    old_domain = old_mdl.domains[0]
    new_domain = new_mdl.domains[0]

    for model_name, old_versions in old_domain.models.items():
        if model_name not in new_domain.models:
            continue

        new_versions = new_domain.models[model_name]

        # If both have @ 1, renumber new to @ 2 so they can coexist
        if len(old_versions) > 0 and len(new_versions) > 0:
            if old_versions[0].version == new_versions[0].version:
                for v in new_versions:
                    v.version = v.version + 1

                new_domain.models[model_name] = old_versions + new_versions

    # Update new projection's source reference to point to the renumbered version
    if hasattr(new.source.version, 'version'):
        new.source.version = VersionExact(kind='exact', version=new.source.version.version + 1)

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
    mdl, old, new = _two_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            quantity: int
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            quantity <- o.quantity
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            quantity: string
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            quantity <- o.quantity
          }
        }
        """,
    )

    changes = _compare_shape(mdl, old, new)

    assert any(c.kind == "type_changed" and c.breaking and c.field_name == "quantity" for c in changes)


def test_optional_to_required_is_breaking():
    mdl, old, new = _two_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            note?: string
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
            note <- o.note
          }
        }
        """,
    )

    changes = _compare_shape(mdl, old, new)

    assert any(
        c.kind == "optionality_changed" and c.breaking and c.field_name == "note"
        for c in changes
    )


def test_required_to_optional_is_not_breaking():
    mdl, old, new = _two_versions(
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
            note?: string
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            note <- o.note
          }
        }
        """,
    )

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
