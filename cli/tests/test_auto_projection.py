"""Additional auto-projection expansion tests (annotation exclusions, event ops)."""

from modelable.parser.parse import parse_text_to_ir
from modelable.planner.planner import expand_auto_projections


def test_pii_annotation_excluded_from_reply():
    mdl = parse_text_to_ir("""
    domain catalog {
      owner: "test-team"
      entity Customer @ 1 (additive) {
        @key customerId: uuid
        @pii email: string
        name: string
      }

      auto projections Customer @ 1 {
        reply
          exclude [@pii]
      }
    }
    """)
    errors = expand_auto_projections(mdl)
    assert errors == []
    fields = {f.name for f in mdl.domains[0].projections["CustomerReply"][0].fields}
    assert "customerId" in fields
    assert "name" in fields
    assert "email" not in fields


def test_server_annotation_excluded_from_request_by_default():
    mdl = parse_text_to_ir("""
    domain catalog {
      owner: "test-team"
      entity Product @ 1 (additive) {
        @key productId: uuid
        @server updatedAt: timestamp
        price: float
      }

      auto projections Product @ 1 {
        request
      }
    }
    """)
    expand_auto_projections(mdl)
    fields = {f.name for f in mdl.domains[0].projections["ProductRequest"][0].fields}
    assert "productId" in fields
    assert "price" in fields
    assert "updatedAt" not in fields


def test_db_includes_server_fields():
    mdl = parse_text_to_ir("""
    domain catalog {
      owner: "test-team"
      entity Product @ 1 (additive) {
        @key productId: uuid
        @server createdAt: timestamp
        price: float
      }

      auto projections Product @ 1 {
        db
      }
    }
    """)
    expand_auto_projections(mdl)
    fields = {f.name for f in mdl.domains[0].projections["ProductDb"][0].fields}
    assert "createdAt" in fields


def test_event_operations_stored():
    mdl = parse_text_to_ir("""
    domain catalog {
      owner: "test-team"
      entity Product @ 1 (additive) {
        @key productId: uuid
        name: string
      }

      auto projections Product @ 1 {
        event on [created, updated]
      }
    }
    """)
    errors = expand_auto_projections(mdl)
    assert errors == []
    event_pv = mdl.domains[0].projections["ProductEvent"][0]
    assert event_pv is not None


def test_multiple_exclusions_combined():
    mdl = parse_text_to_ir("""
    domain catalog {
      owner: "test-team"
      entity User @ 1 (additive) {
        @key userId: uuid
        @pii email: string
        password: string
        name: string
      }

      auto projections User @ 1 {
        reply
          exclude [@pii, password]
      }
    }
    """)
    errors = expand_auto_projections(mdl)
    assert errors == []
    fields = {f.name for f in mdl.domains[0].projections["UserReply"][0].fields}
    assert "userId" in fields
    assert "name" in fields
    assert "email" not in fields
    assert "password" not in fields


def test_auto_generated_flag_set():
    mdl = parse_text_to_ir("""
    domain catalog {
      owner: "test-team"
      entity Item @ 1 (additive) {
        @key itemId: uuid
      }

      auto projections Item @ 1 {
        db
      }
    }
    """)
    expand_auto_projections(mdl)
    pv = mdl.domains[0].projections["ItemDb"][0]
    assert pv.auto_generated is True
