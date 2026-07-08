import pytest

from modelable.parser.parse import ParseError, parse_file, parse_text, parse_text_to_ir


def test_import():
    assert parse_text is not None


SIMPLE_MODEL = """
domain customer {
  owner: "customer-platform"
  description: "Customer data."

  entity Customer @ 2 (additive) {
    @key
    customerId: uuid
    @pii
    email?: string
    status: enum(active, blocked, deleted)
    total: decimal(12, 2)
    tags: array<string>
    createdAt: timestamp
  }
}
"""


def test_parse_simple_model():
    tree = parse_text(SIMPLE_MODEL)
    assert tree.data == "start"


def test_parse_domain_contact_metadata():
    tree = parse_text("""
    domain customer {
      owner: "customer-platform"
      contact: "customer@example.com"
      description: "Customer data."
    }
    """)
    assert tree.data == "start"


def test_parse_all_primitive_types():
    tree = parse_text("""
    domain types {
      owner: "test-team"
      entity AllTypes @ 1 (additive) {
        a: string
        b: int
        c: float
        d: bool
        e: uuid
        f: timestamp
        g: date
        h: time
        i: duration
        j: binary
      }
    }
    """)
    assert tree.data == "start"


def test_parse_all_fixed_width_integer_types():
    tree = parse_text("""
    domain types {
      owner: "test-team"
      entity FixedWidth @ 1 (additive) {
        a: u8
        b: u16
        c: u32
        d: u64
        e: u128
        f: i8
        g: i16
        h: i32
        i: i64
        j: i128
      }
    }
    """)
    assert tree.data == "start"


def test_fixed_width_integer_ir_kinds():
    ir = parse_text_to_ir(
        SIMPLE_MODEL.replace(
            "total: decimal(12, 2)",
            "total: decimal(12, 2)\n    moduleId: u32\n    delta: i64",
        )
    )
    fields = {f.name: f.type for f in ir.domains[0].models["Customer"][0].fields}
    assert fields["moduleId"].kind == "u32"
    assert fields["delta"].kind == "i64"


def test_parse_fixed_length_binary():
    tree = parse_text("""
    domain types {
      owner: "test-team"
      entity Widths @ 1 (additive) {
        @key id: uuid
        keyHash: binary(32)
        avatar: binary
      }
    }
    """)
    assert tree.data == "start"


def test_fixed_length_binary_ir_shape():
    ir = parse_text_to_ir(
        SIMPLE_MODEL.replace(
            "total: decimal(12, 2)",
            "total: decimal(12, 2)\n    keyHash: binary(32)",
        )
    )
    fields = {f.name: f.type for f in ir.domains[0].models["Customer"][0].fields}
    assert fields["keyHash"].kind == "fixed_binary"
    assert fields["keyHash"].length == 32


def test_parse_semantic_type_decl():
    tree = parse_text("""
    domain platform {
      owner: "platform-team"

      semantic ModuleId : u32 {
        registry: true
      }

      semantic Identity128 : u128

      entity Schema @ 1 (additive) {
        @key moduleId: ModuleId
      }
    }
    """)
    assert tree.data == "start"


def test_semantic_type_decl_ir_shape():
    ir = parse_text_to_ir("""
    domain platform {
      owner: "platform-team"

      semantic ModuleId : u32 {
        registry: true
      }

      semantic Identity128 : u128
    }
    """)
    domain = ir.domains[0]
    by_name = {s.name: s for s in domain.semantic_types}
    assert by_name["ModuleId"].underlying.kind == "u32"
    assert by_name["ModuleId"].registry is True
    assert by_name["Identity128"].underlying.kind == "u128"
    assert by_name["Identity128"].registry is False


def test_field_referencing_semantic_type_is_named_type():
    ir = parse_text_to_ir("""
    domain platform {
      owner: "platform-team"

      semantic ModuleId : u32

      entity Schema @ 1 (additive) {
        @key moduleId: ModuleId
      }
    }
    """)
    field = ir.domains[0].models["Schema"][0].fields[0]
    assert field.type.kind == "named"
    assert field.type.name == "ModuleId"


def test_parse_composite_types():
    tree = parse_text("""
    domain types {
      owner: "test-team"
      entity Composite @ 1 (additive) {
        @key id: uuid
        tags: array<string>
        meta: map<string, int>
        total: decimal(12, 2)
        addr: ref<address.Address>
        status: enum(active, inactive)
      }
    }
    """)
    assert tree.data == "start"


def test_parse_annotations():
    tree = parse_text("""
    domain types {
      owner: "test-team"
      entity Annotated @ 1 (additive) {
        @key id: uuid
        @pii email?: string
        @classification("restricted") secret: string
        @deprecated(replacedBy: "email") oldEmail?: string
        @owner("team-a") managed: string
      }
    }
    """)
    assert tree.data == "start"


def test_parse_file(tmp_path):
    model = tmp_path / "simple_model.mdl"
    model.write_text(SIMPLE_MODEL, encoding="utf-8")

    tree = parse_file(model)

    assert tree.data == "start"


def test_parse_invalid_syntax_raises_parse_error():
    with pytest.raises(ParseError):
        parse_text("domain customer { entity Customer @ }")


def test_parse_customer_fixture(fixture_path):
    tree = parse_file(fixture_path / "customer.mdl")
    assert tree.data == "start"


def test_parse_billing_projection_fixture(fixture_path):
    tree = parse_file(fixture_path / "billing_projection.mdl")
    assert tree.data == "start"


def test_parse_direct_mapping():
    tree = parse_text("""
    domain billing {
      owner: "test-team"
      projection BillingCustomer @ 1
        from customer.Customer @ 2 as c
      {
        id <- c.customerId
        name <- c.legalName
      }
    }
    """)
    assert tree.data == "start"


def test_parse_join():
    tree = parse_text("""
    domain billing {
      owner: "test-team"
      projection OrderLine @ 1
        from orders.Order @ 1 as o
        join customer.Customer @ 2 as c on o.customerId == c.customerId
      {
        orderId <- o.orderId
        customerName <- c.legalName
      }
    }
    """)
    assert tree.data == "start"


def test_parse_version_range():
    tree = parse_text("""
    domain billing {
      owner: "test-team"
      projection Ranged @ 1
        from customer.Customer @ >=2 <3 as c
      {
        id <- c.customerId
      }
    }
    """)
    assert tree.data == "start"


def test_parse_aggregation():
    tree = parse_text("""
    domain stats {
      owner: "test-team"
      projection OrderStats @ 1
        from orders.Order @ 1 as o
        group by o.customerId
      {
        customerId <- o.customerId
        total = sum(o.amount)
      }
    }
    """)
    assert tree.data == "start"


def test_parse_field_default_values():
    tree = parse_text("""
    domain commerce {
      owner: "test-team"
      entity Order @ 1 (additive) {
        discountCents: int = 0
        isActive: bool = false
        note?: string = "[ERASED]"
      }
    }
    """)
    assert tree.data == "start"


def test_parse_workspace_metadata():
    tree = parse_text("""
    workspace "analytics-platform" {
      name: "analytics-platform"
      description: "Analytics registry"
      generate {
        docs -> "./generated/docs/"
        sql(postgres) -> "./generated/sql/"
      }
    }
    """)
    assert tree.data == "start"


def test_parse_left_join_and_where():
    tree = parse_text("""
    domain billing {
      owner: "test-team"
      projection OrderLine @ 1
        from orders.Order @ 1 as o
        left join customer.Customer @ 2 as c on o.customerId == c.customerId
        where o.status == "confirmed"
      {
        orderId <- o.orderId
      }
    }
    """)
    assert tree.data == "start"


def test_parse_access_block():
    tree = parse_text("""
    domain customer {
      owner: "test-team"
      entity Customer @ 1 (additive) {
        @key customerId: uuid
        access {
          entity billing [read, project, subscribe]
          property email billing [read]
        }
        email?: string
      }
    }
    """)
    assert tree.data == "start"


def test_model_level_wire_field_case_annotation():
    mdl = parse_text_to_ir("""
    domain tracing {
      owner: "test-team"

      @wire(json.fieldCase: "snake_case")
      entity Span @ 1 (additive) {
        @key spanId: string
        startTimeUnixNano: int
      }
    }
    """)

    model = mdl.domains[0].models["Span"][0]
    wire_targets = model.wire_targets()
    assert wire_targets["json"].field_case == "snake_case"


def test_projection_level_wire_field_case_annotation():
    mdl = parse_text_to_ir("""
    domain tracing {
      owner: "test-team"

      entity Span @ 1 (additive) {
        @key spanId: string
        startTimeUnixNano: int
      }

      @wire(json.fieldCase: "snake_case")
      projection SpanRow @ 1
        from tracing.Span @ 1 as s
      {
        spanId <- s.spanId
        startTimeUnixNano <- s.startTimeUnixNano
      }
    }
    """)

    projection = mdl.domains[0].projections["SpanRow"][0]
    wire_targets = projection.wire_targets()
    assert wire_targets["json"].field_case == "snake_case"
