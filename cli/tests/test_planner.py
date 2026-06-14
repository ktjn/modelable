from modelable.parser.parse import parse_text_to_ir
from modelable.planner.planner import expand_auto_projections


def test_expand_auto_projections_generates_all_targets():
    mdl = parse_text_to_ir("""
    domain catalog {
      owner: "test-team"
      entity Product @ 1 (additive) {
        @key productId: uuid
        sku: string
        name: string
        @server createdAt: timestamp
      }

      auto projections Product @ 1 {
        db
        request
        reply
        event
      }
    }
    """)
    errors = expand_auto_projections(mdl)
    assert errors == []

    domain = mdl.domains[0]
    assert "ProductDb" in domain.projections
    assert "ProductRequest" in domain.projections
    assert "ProductReply" in domain.projections
    assert "ProductEvent" in domain.projections

    # Each generated projection has one version
    assert len(domain.projections["ProductDb"]) == 1
    assert len(domain.projections["ProductRequest"]) == 1


def test_request_excludes_server_fields():
    mdl = parse_text_to_ir("""
    domain catalog {
      owner: "test-team"
      entity Product @ 1 (additive) {
        @key productId: uuid
        sku: string
        @server createdAt: timestamp
      }

      auto projections Product @ 1 {
        request
      }
    }
    """)
    expand_auto_projections(mdl)
    fields = {f.name for f in mdl.domains[0].projections["ProductRequest"][0].fields}
    assert "productId" in fields
    assert "sku" in fields
    assert "createdAt" not in fields


def test_explicit_exclusions():
    mdl = parse_text_to_ir("""
    domain catalog {
      owner: "test-team"
      entity Product @ 1 (additive) {
        @key productId: uuid
        sku: string
        secret: string
      }

      auto projections Product @ 1 {
        reply
          exclude [secret]
      }
    }
    """)
    expand_auto_projections(mdl)
    fields = {f.name for f in mdl.domains[0].projections["ProductReply"][0].fields}
    assert "productId" in fields
    assert "sku" in fields
    assert "secret" not in fields


def test_auto_projection_unknown_model():
    mdl = parse_text_to_ir("""
    domain catalog {
      owner: "test-team"
      auto projections Missing @ 1 {
        db
      }
    }
    """)
    errors = expand_auto_projections(mdl)
    assert any("unknown model 'Missing'" in e for e in errors)


def test_auto_projection_unknown_version():
    mdl = parse_text_to_ir("""
    domain catalog {
      owner: "test-team"
      entity Product @ 1 (additive) {
        @key productId: uuid
      }

      auto projections Product @ 2 {
        db
      }
    }
    """)
    errors = expand_auto_projections(mdl)
    assert any("Product@2 which does not exist" in e for e in errors)


def test_expanded_projections_resolve_as_sources():
    mdl = parse_text_to_ir("""
    domain catalog {
      owner: "test-team"
      entity Product @ 1 (additive) {
        @key productId: uuid
        name: string
      }

      auto projections Product @ 1 {
        reply
      }
    }

    domain storefront {
      owner: "test-team"
      projection ProductDisplay @ 1
        from catalog.ProductReply @ 1 as p
      {
        productId <- p.productId
        name <- p.name
      }
    }
    """)
    errors = expand_auto_projections(mdl)
    assert errors == []

    from modelable.registry.resolver import validate_references

    ref_errors = validate_references(mdl)
    assert ref_errors == []
