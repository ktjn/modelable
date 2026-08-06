"""Test signature rendering for versioned ref<> type references (Slice C2)."""

from conformance.signature.scenarios import ref_target_change_pair, ref_version_only_change_pair

from modelable.compiler.render import render_model_version
from modelable.parser.parse import parse_text_to_ir


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
    old, new = ref_target_change_pair()

    assert old.signature != new.signature


def test_ref_version_only_change_does_not_alter_canonical_signature():
    old, new = ref_version_only_change_pair()

    assert old.signature == new.signature
