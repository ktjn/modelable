from modelable.parser.parse import parse_text
from modelable.validation.deferred_syntax import find_deferred_syntax_diagnostics


def test_workspace_registry_block_produces_deferred_warning():
    tree = parse_text("""
    workspace {
      name: "acme"
      registry {
        url: "https://registry.acme.internal"
      }
    }
    """)

    diagnostics = find_deferred_syntax_diagnostics(tree, path="workspace.mdl")

    assert len(diagnostics) == 1
    assert diagnostics[0].code == "DEFERRED"
    assert diagnostics[0].severity == "warning"
    assert diagnostics[0].path == "workspace.mdl"
    assert "registry" in diagnostics[0].message


def test_workspace_peers_block_produces_deferred_warning():
    tree = parse_text("""
    workspace {
      name: "acme"
      peers: [orders, analytics]
    }
    """)

    diagnostics = find_deferred_syntax_diagnostics(tree, path="workspace.mdl")

    assert len(diagnostics) == 1
    assert diagnostics[0].code == "DEFERRED"
    assert diagnostics[0].severity == "warning"
    assert "peers" in diagnostics[0].message


def test_top_level_consumer_declaration_produces_deferred_warning():
    tree = parse_text("""
    consumer billing {
      team: "billing-platform"
    }
    """)

    diagnostics = find_deferred_syntax_diagnostics(tree, path="consumers.mdl")

    assert len(diagnostics) == 1
    assert diagnostics[0].code == "DEFERRED"
    assert "consumer" in diagnostics[0].message


def test_top_level_subscription_declaration_produces_deferred_warning():
    tree = parse_text("""
    subscription orderEvents {
      topic: order.events
    }
    """)

    diagnostics = find_deferred_syntax_diagnostics(tree, path="subscriptions.mdl")

    assert len(diagnostics) == 1
    assert diagnostics[0].code == "DEFERRED"
    assert "subscription" in diagnostics[0].message


def test_projection_subscription_block_produces_deferred_warning():
    tree = parse_text("""
    domain orders {
      owner: "test-team"
      entity Order @ 1 (additive) {
        @key orderId: uuid
        status: string
      }
      projection OrderView @ 1 from Order @ 1 as o {
        orderId <- o.orderId
        subscription {
          mode: push
        }
      }
    }
    """)

    diagnostics = find_deferred_syntax_diagnostics(tree, path="orders.mdl")

    assert len(diagnostics) == 1
    assert diagnostics[0].code == "DEFERRED"
    assert "subscription" in diagnostics[0].message


def test_projection_materialisation_block_produces_deferred_warning():
    tree = parse_text("""
    domain orders {
      owner: "test-team"
      entity Order @ 1 (additive) {
        @key orderId: uuid
        status: string
      }
      projection OrderView @ 1 from Order @ 1 as o {
        orderId <- o.orderId
        materialisation {
          strategy: incremental
        }
      }
    }
    """)

    diagnostics = find_deferred_syntax_diagnostics(tree, path="orders.mdl")

    assert len(diagnostics) == 1
    assert diagnostics[0].code == "DEFERRED"
    assert "materialisation" in diagnostics[0].message


def test_binding_recognized_attrs_alone_produce_no_deferred_warning():
    tree = parse_text("""
    domain orders {
      owner: "test-team"
      entity Order @ 1 (additive) {
        @key orderId: uuid
      }
    }
    binding orderStore {
      adapter: postgres
      model: orders.Order @ 1
      table: "orders"
    }
    """)

    diagnostics = find_deferred_syntax_diagnostics(tree, path="bindings.mdl")

    assert diagnostics == []


def test_binding_opaque_content_produces_one_deferred_warning_per_unrecognized_key():
    tree = parse_text("""
    binding orderStream {
      adapter: kafka
      role: stream
      config: {
        brokers: ["kafka.internal:9092"]
      }
    }
    """)

    diagnostics = find_deferred_syntax_diagnostics(tree, path="bindings.mdl")

    assert len(diagnostics) == 2
    assert all(d.code == "DEFERRED" for d in diagnostics)
    assert all("binding" in d.message for d in diagnostics)


def test_no_deferred_syntax_produces_no_diagnostics():
    tree = parse_text("""
    domain orders {
      owner: "test-team"
      entity Order @ 1 (additive) {
        @key orderId: uuid
      }
    }
    """)

    diagnostics = find_deferred_syntax_diagnostics(tree, path="orders.mdl")

    assert diagnostics == []
