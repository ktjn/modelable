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

    assert any(
        "group by" in error.lower() or "aggregat" in error.lower()
        for error in errors
    )


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
