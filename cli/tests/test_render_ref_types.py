"""Test signature rendering for versioned ref<> type references (Slice C2)."""

from modelable.parser.parse import parse_text_to_ir
from modelable.compiler.render import render_model_version
from modelable.registry.signature import compute_version_signature


def test_versioned_ref_round_trips_through_canonical_rendering():
    mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      entity Customer @ 1 (additive) { @key customerId: uuid }
      entity Order @ 1 (additive) {
        @key orderId: uuid
        customerRef: ref<orders.Customer @ 1>
      }
    }
    """)
    domain = mdl.domains[0]
    version = domain.models["Order"][0]

    rendered = render_model_version(domain.name, "Order", version, domain.owner, domain.description)

    assert "ref<orders.Customer @ 1>" in rendered


def test_ref_target_change_alters_canonical_signature():
    old_mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      entity Customer @ 1 (additive) { @key customerId: uuid }
      entity Shipment @ 1 (additive) { @key shipmentId: uuid }
      entity Order @ 1 (additive) {
        @key orderId: uuid
        targetRef: ref<orders.Customer>
      }
    }
    """)
    new_mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      entity Customer @ 1 (additive) { @key customerId: uuid }
      entity Shipment @ 1 (additive) { @key shipmentId: uuid }
      entity Order @ 1 (additive) {
        @key orderId: uuid
        targetRef: ref<orders.Shipment>
      }
    }
    """)

    old_version = old_mdl.domains[0].models["Order"][0]
    new_version = new_mdl.domains[0].models["Order"][0]

    old_sig = compute_version_signature("orders", "Order", old_version)
    new_sig = compute_version_signature("orders", "Order", new_version)

    assert old_sig != new_sig


def test_ref_version_only_change_does_not_alter_canonical_signature():
    old_mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      entity Customer @ 1 (additive) { @key customerId: uuid }
      entity Customer @ 2 (additive) { @key customerId: uuid }
      entity Order @ 1 (additive) {
        @key orderId: uuid
        targetRef: ref<orders.Customer @ 1>
      }
    }
    """)
    new_mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      entity Customer @ 1 (additive) { @key customerId: uuid }
      entity Customer @ 2 (additive) { @key customerId: uuid }
      entity Order @ 1 (additive) {
        @key orderId: uuid
        targetRef: ref<orders.Customer @ 2>
      }
    }
    """)

    old_version = old_mdl.domains[0].models["Order"][0]
    new_version = new_mdl.domains[0].models["Order"][0]

    old_sig = compute_version_signature("orders", "Order", old_version)
    new_sig = compute_version_signature("orders", "Order", new_version)

    assert old_sig == new_sig
