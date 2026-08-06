import pytest

from modelable.parser.parse import parse_text_to_ir
from modelable.registry.resolver import resolve_ref_type

DOMAIN = """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
  entity Customer @ 2 (additive) {
    @key customerId: uuid
    name: string
  }
}
"""


def _ref_field(mdl_text: str):
    mdl = parse_text_to_ir(mdl_text)
    return mdl, mdl.domains[1].models["Order"][0].fields[1].type


def test_unversioned_ref_resolves_to_latest():
    mdl, field_type = _ref_field(
        DOMAIN
        + """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            customerRef: ref<customer.Customer>
          }
        }
        """
    )

    resolved = resolve_ref_type(field_type, mdl)

    assert resolved.domain_name == "customer"
    assert resolved.model_name == "Customer"
    assert resolved.version.version == 2


def test_exact_versioned_ref_resolves_to_that_version():
    mdl, field_type = _ref_field(
        DOMAIN
        + """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            customerRef: ref<customer.Customer @ 1>
          }
        }
        """
    )

    resolved = resolve_ref_type(field_type, mdl)

    assert resolved.version.version == 1


def test_unresolvable_target_raises_lookup_error():
    mdl, field_type = _ref_field(
        DOMAIN
        + """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            customerRef: ref<customer.MissingEntity>
          }
        }
        """
    )

    with pytest.raises(LookupError):
        resolve_ref_type(field_type, mdl)


def test_unresolvable_version_raises_lookup_error():
    mdl, field_type = _ref_field(
        DOMAIN
        + """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            customerRef: ref<customer.Customer @ 99>
          }
        }
        """
    )

    with pytest.raises(LookupError):
        resolve_ref_type(field_type, mdl)
