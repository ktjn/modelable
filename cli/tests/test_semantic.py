from modelable.parser.parse import parse_text_to_ir
from modelable.validation.semantic import validate


def test_valid_entity_passes():
    mdl = parse_text_to_ir("""
    domain customer {
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


def test_aggregate_function_without_group_by_fails():
    mdl = parse_text_to_ir("""
    domain stats {
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


def test_aggregate_function_with_group_by_passes():
    mdl = parse_text_to_ir("""
    domain stats {
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
