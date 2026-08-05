from modelable.compat.projection_fields import resolve_projection_field_type_and_optionality
from modelable.parser.parse import parse_text_to_ir

DIRECT_MAPPING_MODEL = """
domain orders {
  owner: "test-team"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    status?: string
  }
  projection OrderView @ 1 from orders.Order @ 1 as o {
    orderId <- o.orderId
    status <- o.status
  }
}
"""


def test_resolves_type_and_optionality_for_direct_mapping():
    mdl = parse_text_to_ir(DIRECT_MAPPING_MODEL)
    domain = mdl.domains[0]
    projection = domain.projections["OrderView"][0]
    status_field = next(f for f in projection.fields if f.name == "status")

    field_type, optional = resolve_projection_field_type_and_optionality(status_field, projection, mdl)

    assert field_type is not None
    assert field_type.kind == "string"
    assert optional is True


def test_resolves_through_a_join_alias():
    mdl = parse_text_to_ir("""
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
      projection OrderWithCustomer @ 1 from orders.Order @ 1 as o
        join orders.Customer @ 1 as c on o.customerId == c.customerId {
        orderId <- o.orderId
        customerName <- c.name
      }
    }
    """)
    domain = mdl.domains[0]
    projection = domain.projections["OrderWithCustomer"][0]
    name_field = next(f for f in projection.fields if f.name == "customerName")

    field_type, optional = resolve_projection_field_type_and_optionality(name_field, projection, mdl)

    assert field_type is not None
    assert field_type.kind == "string"
    assert optional is False


def test_computed_mapping_returns_none_none():
    mdl = parse_text_to_ir("""
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
    """)
    domain = mdl.domains[0]
    projection = domain.projections["OrderView"][0]
    computed_field = next(f for f in projection.fields if f.name == "isShipped")

    field_type, optional = resolve_projection_field_type_and_optionality(computed_field, projection, mdl)

    assert field_type is None
    assert optional is None


def test_resolves_recursively_through_a_projection_of_a_projection():
    mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      entity Order @ 1 (additive) {
        @key orderId: uuid
        status?: string
      }
      projection OrderBase @ 1 from orders.Order @ 1 as o {
        orderId <- o.orderId
        status <- o.status
      }
      projection OrderDerived @ 1 from orders.OrderBase @ 1 as b {
        orderId <- b.orderId
        status <- b.status
      }
    }
    """)
    domain = mdl.domains[0]
    derived = domain.projections["OrderDerived"][0]
    status_field = next(f for f in derived.fields if f.name == "status")

    field_type, optional = resolve_projection_field_type_and_optionality(status_field, derived, mdl)

    assert field_type is not None
    assert field_type.kind == "string"
    assert optional is True
