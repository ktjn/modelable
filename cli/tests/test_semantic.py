from modelable.parser.parse import parse_text_to_ir
from modelable.validation.semantic import validate


def test_valid_entity_passes():
    mdl = parse_text_to_ir("""
    domain customer {
      owner: "test-team"
      entity Customer @ 1 (additive) {
        @key customerId: uuid
        name: string
      }
    }
    """)

    errors = validate(mdl)

    assert errors == []


def test_entity_missing_key_fails():
    mdl = parse_text_to_ir("""
    domain customer {
      owner: "test-team"
      entity Customer @ 1 (additive) {
        customerId: uuid
        name: string
      }
    }
    """)

    errors = validate(mdl)

    assert any("key" in error.lower() for error in errors)


def test_event_must_not_have_key():
    mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      event OrderPlaced @ 1 (additive) {
        @key orderId: uuid
        amount: decimal(10, 2)
      }
    }
    """)

    errors = validate(mdl)

    assert any("key" in error.lower() for error in errors)


def test_versions_must_be_ascending():
    mdl = parse_text_to_ir("""
    domain customer {
      owner: "test-team"
      entity Customer @ 2 (additive) {
        @key customerId: uuid
      }
      entity Customer @ 1 (additive) {
        @key customerId: uuid
      }
    }
    """)

    errors = validate(mdl)

    assert any("version" in error.lower() for error in errors)


def test_additive_version_rejects_breaking_changes():
    mdl = parse_text_to_ir("""
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
    """)

    errors = validate(mdl)

    assert any("additive declaration includes incompatible changes" in error for error in errors)


def test_additive_version_allows_optional_additions():
    mdl = parse_text_to_ir("""
    domain customer {
      owner: "test-team"
      entity Customer @ 1 (additive) {
        @key customerId: uuid
        name: string
      }
      entity Customer @ 2 (additive) {
        @key customerId: uuid
        name: string
        email?: string
      }
    }
    """)

    errors = validate(mdl)

    assert errors == []


def test_breaking_version_requires_incompatible_change():
    mdl = parse_text_to_ir("""
    domain customer {
      owner: "test-team"
      entity Customer @ 1 (additive) {
        @key customerId: uuid
        name: string
      }
      entity Customer @ 2 (breaking) {
        @key customerId: uuid
        name: string
      }
    }
    """)

    errors = validate(mdl)

    assert any("breaking declaration must include at least one incompatible change" in error for error in errors)


def test_aggregate_function_without_group_by_fails():
    mdl = parse_text_to_ir("""
    domain stats {
      owner: "test-team"
      projection BadStats @ 1
        from orders.Order @ 1 as o
      {
        total = sum(o.amount)
      }
    }
    """)

    errors = validate(mdl)

    assert any("group by" in error.lower() or "aggregat" in error.lower() for error in errors)


def test_valid_classification_levels_pass():
    for level in ("open", "internal", "confidential", "restricted", "secret"):
        mdl = parse_text_to_ir(f"""
        domain payments {{
          owner: "test-team"
          entity Payment @ 1 (additive) {{
            @key paymentId: uuid
            @classification("{level}") cardNumber: string
          }}
        }}
        """)
        errors = validate(mdl)
        assert errors == [], f"Expected no errors for level '{level}', got: {errors}"


def test_invalid_classification_level_fails():
    mdl = parse_text_to_ir("""
    domain payments {
      owner: "test-team"
      entity Payment @ 1 (additive) {
        @key paymentId: uuid
        @classification("top-secret") cardNumber: string
      }
    }
    """)

    errors = validate(mdl)

    assert any("classification" in error.lower() for error in errors)
    assert any("top-secret" in error for error in errors)


def test_invalid_classification_level_on_projection_field_fails():
    mdl = parse_text_to_ir("""
    domain payments {
      owner: "test-team"
      projection PaymentSummary @ 1
        from payments.Payment @ 1 as p
      {
        @classification("classified") cardNumber <- p.cardNumber
      }
    }
    """)

    errors = validate(mdl)

    assert any("classification" in error.lower() for error in errors)
    assert any("classified" in error for error in errors)


def test_aggregate_function_with_group_by_passes():
    mdl = parse_text_to_ir("""
    domain stats {
      owner: "test-team"
      projection GoodStats @ 1
        from orders.Order @ 1 as o
        group by o.customerId
      {
        customerId <- o.customerId
        total = sum(o.amount)
      }
    }
    """)

    errors = validate(mdl)

    assert errors == []


def test_unknown_wire_target_fails():
    mdl = parse_text_to_ir("""
    domain metrics {
      owner: "test-team"
      entity Span @ 1 (additive) {
        @key spanId: string
        @wire(unknown: "string")
        startTimeUnixNano: int
      }
    }
    """)

    errors = validate(mdl)

    assert any("unknown wire target" in error.lower() for error in errors)


def test_json_wire_requires_string_encoding():
    mdl = parse_text_to_ir("""
    domain metrics {
      owner: "test-team"
      entity Span @ 1 (additive) {
        @key spanId: string
        @wire(json: "uuid")
        startTimeUnixNano: int
      }
    }
    """)

    errors = validate(mdl)

    assert any("unsupported json wire encoding" in error.lower() for error in errors)


def test_json_wire_rejects_non_integer_string_fields():
    mdl = parse_text_to_ir("""
    domain metrics {
      owner: "test-team"
      entity Span @ 1 (additive) {
        @key spanId: string
        @wire(json: "string")
        name: string
      }
    }
    """)

    errors = validate(mdl)

    assert any("only supports @wire(json: ...)" in error for error in errors)


def test_json_wire_case_on_enum_requires_no_encoding():
    """@wire(json.case: "SCREAMING_SNAKE_CASE") on an enum field is valid without json: encoding."""
    mdl = parse_text_to_ir("""
    domain events {
      owner: "test-team"
      entity Event @ 1 (additive) {
        @key eventId: uuid
        @wire(json.case: "SCREAMING_SNAKE_CASE")
        status: enum(Active, Inactive)
      }
    }
    """)

    errors = validate(mdl)

    assert errors == []


def test_json_wire_case_on_non_enum_is_rejected():
    """@wire(json.case: ...) on a non-enum field should be rejected."""
    mdl = parse_text_to_ir("""
    domain events {
      owner: "test-team"
      entity Event @ 1 (additive) {
        @key eventId: uuid
        @wire(json: "string", json.case: "SCREAMING_SNAKE_CASE")
        amount: int
      }
    }
    """)

    errors = validate(mdl)

    assert any("non-enum" in error.lower() for error in errors)


def test_json_wire_overrides_on_enum_requires_no_encoding():
    """@wire(json.overrides: {...}) on an enum field is valid without json: encoding."""
    mdl = parse_text_to_ir("""
    domain events {
      owner: "test-team"
      entity Event @ 1 (additive) {
        @key eventId: uuid
        @wire(json.overrides: { Active: "active", Inactive: "inactive" })
        status: enum(Active, Inactive)
      }
    }
    """)

    errors = validate(mdl)

    assert errors == []


def test_inline_object_wire_hints_are_validated_recursively():
    mdl = parse_text_to_ir("""
    domain metrics {
      owner: "test-team"
      entity Span @ 1 (additive) {
        @key spanId: string
        payload: object {
          @wire(json: "bad_encoding")
          count: int
        }
      }
    }
    """)

    errors = validate(mdl)

    assert any("payload" in error.lower() and "unsupported json wire encoding" in error.lower() for error in errors)


def test_rust_type_override_is_rejected_on_non_int_fields():
    mdl = parse_text_to_ir("""
    domain metrics {
      owner: "test-team"
      entity Span @ 1 (additive) {
        @key spanId: string
        @wire(rust.type: "i64")
        startedAt: timestamp
      }
    }
    """)

    errors = validate(mdl)

    assert any("only supports rust.type on int fields" in error.lower() for error in errors)


def test_projection_field_wire_hints_validate_against_source_type():
    mdl = parse_text_to_ir("""
    domain metrics {
      owner: "test-team"
      entity Span @ 1 (additive) {
        @key spanId: string
        amount: int
      }

      projection SpanView @ 1
        from metrics.Span @ 1 as s
      {
        @wire(json: "string")
        amount <- s.spanId
      }
    }
    """)

    errors = validate(mdl)

    assert any("only supports @wire(json: ...)" in error for error in errors)


def test_model_level_json_field_case_snake_case_passes():
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

    errors = validate(mdl)

    assert errors == []


def test_model_level_json_field_case_invalid_value_is_rejected():
    mdl = parse_text_to_ir("""
    domain tracing {
      owner: "test-team"

      @wire(json.fieldCase: "kebab-case")
      entity Span @ 1 (additive) {
        @key spanId: string
        startTimeUnixNano: int
      }
    }
    """)

    errors = validate(mdl)

    assert any("unsupported json.fieldcase" in error.lower() for error in errors)


def test_field_level_json_field_case_is_rejected():
    mdl = parse_text_to_ir("""
    domain tracing {
      owner: "test-team"

      entity Span @ 1 (additive) {
        @key spanId: string
        @wire(json.fieldCase: "snake_case")
        startTimeUnixNano: int
      }
    }
    """)

    errors = validate(mdl)

    assert any("json.fieldcase" in error.lower() for error in errors)


def test_projection_level_json_field_case_snake_case_passes():
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

    errors = validate(mdl)

    assert errors == []


def test_model_level_wire_target_other_than_json_field_case_is_rejected():
    mdl = parse_text_to_ir("""
    domain tracing {
      owner: "test-team"

      @wire(rust.case: "snake_case")
      entity Span @ 1 (additive) {
        @key spanId: string
        startTimeUnixNano: int
      }
    }
    """)

    errors = validate(mdl)

    assert any("only @wire(json.fieldcase: ...)" in error.lower() for error in errors)


def test_fixed_width_default_out_of_range_is_error():
    mdl = parse_text_to_ir("""
    domain types {
      owner: "test-team"
      entity Widths @ 1 (additive) {
        @key id: uuid
        score: u8 = 300
      }
    }
    """)

    errors = validate(mdl)

    assert any("u8" in e and "range" in e.lower() for e in errors)


def test_fixed_width_default_in_range_is_valid():
    mdl = parse_text_to_ir("""
    domain types {
      owner: "test-team"
      entity Widths @ 1 (additive) {
        @key id: uuid
        score: u8 = 200
        delta: i8 = -100
      }
    }
    """)

    errors = validate(mdl)

    assert errors == []


def test_fixed_width_negative_default_on_unsigned_is_error():
    mdl = parse_text_to_ir("""
    domain types {
      owner: "test-team"
      entity Widths @ 1 (additive) {
        @key id: uuid
        score: u32 = -1
      }
    }
    """)

    errors = validate(mdl)

    assert any("u32" in e for e in errors)
