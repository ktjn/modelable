"""Shared signature fixtures (Slice G3).

`registry/signature.py::compute_version_signature` has two real consumers
today: the registry resolver's version-pin matching (`registry/resolver.py`,
exercised by `test_version_range_resolution.py`/`test_render_ref_types.py`)
and the LSP's federation-reference validation (`lsp/federation.py`,
exercised by `test_lsp_federation_diagnostics.py`). Before this module, each
consumer's tests built their own matching `.mdl` text or hand-constructed
`ModelVersion` IR independently -- two ways to express "customer.Customer@1"
that had to be kept in sync by hand, with no test catching drift between
them. Every `ModelVersion` here is derived by parsing canonical `.mdl` text
(never hand-built IR), so a scenario's signature is exactly what parsing
that text produces, not a reconstruction someone has to keep matching it.
"""

from __future__ import annotations

from dataclasses import dataclass

from modelable.parser.ir import ModelVersion
from modelable.parser.parse import parse_text_to_ir
from modelable.registry.signature import compute_version_signature


@dataclass(frozen=True)
class SignatureScenario:
    domain_name: str
    model_name: str
    version: ModelVersion

    @property
    def signature(self) -> str:
        return compute_version_signature(self.domain_name, self.model_name, self.version)


def _model_version(mdl_text: str, domain_name: str, model_name: str, version: int = 1) -> ModelVersion:
    mdl = parse_text_to_ir(mdl_text)
    domain = next(d for d in mdl.domains if d.name == domain_name)
    return next(v for v in domain.models[model_name] if v.version == version)


CUSTOMER_V1_TEXT = """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""".strip("\n")


def customer_v1() -> SignatureScenario:
    """The canonical customer.Customer@1, shared by resolver pin tests and
    LSP federation-reference tests."""
    return SignatureScenario("customer", "Customer", _model_version(CUSTOMER_V1_TEXT, "customer", "Customer"))


_REF_TARGET_CHANGE_OLD_TEXT = """
domain orders {
  owner: "test-team"
  entity Customer @ 1 (additive) { @key customerId: uuid }
  entity Shipment @ 1 (additive) { @key shipmentId: uuid }
  entity Order @ 1 (additive) {
    @key orderId: uuid
    targetRef: ref<orders.Customer>
  }
}
""".strip("\n")

_REF_TARGET_CHANGE_NEW_TEXT = """
domain orders {
  owner: "test-team"
  entity Customer @ 1 (additive) { @key customerId: uuid }
  entity Shipment @ 1 (additive) { @key shipmentId: uuid }
  entity Order @ 1 (additive) {
    @key orderId: uuid
    targetRef: ref<orders.Shipment>
  }
}
""".strip("\n")


def ref_target_change_pair() -> tuple[SignatureScenario, SignatureScenario]:
    """Order.targetRef retargeted from orders.Customer to orders.Shipment.

    Retargeting a ref<> is a real type change: the two signatures must
    differ.
    """
    old = _model_version(_REF_TARGET_CHANGE_OLD_TEXT, "orders", "Order")
    new = _model_version(_REF_TARGET_CHANGE_NEW_TEXT, "orders", "Order")
    return SignatureScenario("orders", "Order", old), SignatureScenario("orders", "Order", new)


_REF_VERSION_ONLY_CHANGE_OLD_TEXT = """
domain orders {
  owner: "test-team"
  entity Customer @ 1 (additive) { @key customerId: uuid }
  entity Customer @ 2 (additive) { @key customerId: uuid }
  entity Order @ 1 (additive) {
    @key orderId: uuid
    targetRef: ref<orders.Customer @ 1>
  }
}
""".strip("\n")

_REF_VERSION_ONLY_CHANGE_NEW_TEXT = """
domain orders {
  owner: "test-team"
  entity Customer @ 1 (additive) { @key customerId: uuid }
  entity Customer @ 2 (additive) { @key customerId: uuid }
  entity Order @ 1 (additive) {
    @key orderId: uuid
    targetRef: ref<orders.Customer @ 2>
  }
}
""".strip("\n")


def ref_version_only_change_pair() -> tuple[SignatureScenario, SignatureScenario]:
    """Order.targetRef pinned at two different versions of the same target
    model (orders.Customer@1 vs @2).

    Bumping only the pinned version is not a type change: the two
    signatures must be equal.
    """
    old = _model_version(_REF_VERSION_ONLY_CHANGE_OLD_TEXT, "orders", "Order")
    new = _model_version(_REF_VERSION_ONLY_CHANGE_NEW_TEXT, "orders", "Order")
    return SignatureScenario("orders", "Order", old), SignatureScenario("orders", "Order", new)
