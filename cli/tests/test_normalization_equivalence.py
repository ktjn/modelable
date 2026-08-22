"""Normalized-contract equivalence fixtures and assertions (evolution plan F4).

One executable definition of semantic equality for the normalization boundary:
everything that treats a `.mdl` declaration as a canonical contract must go
through ``load_workspace_from_sources``, and equivalent sources must produce
identical normalized IR, signatures, diffs, projection resolution, and
representative output.

The assertion helpers in this module are deliberately reusable so later slices
(e.g. delta-authored versions) can prove equivalence against full declarations
by loading both forms and calling the same functions.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from modelable.compat.diff import compare_model_versions, is_field_change_breaking
from modelable.compiler.workspace import Workspace, WorkspaceDocumentSource, load_workspace_from_sources
from modelable.emitters.json_schema import emit_json_schema_artifacts
from modelable.parser.parse import parse_text_to_ir
from modelable.registry.resolver import resolve_model_ref
from modelable.registry.signature import compute_version_signature

BILLING_MDL = """
domain billing {
  owner: "billing-team"

  entity Invoice @ 1 (additive) {
    @key invoiceId: uuid
    amount: decimal(10, 2) constraint { min: 0 } = 0
    @pii
    notes: string
    state: enum(draft, issued)
    customerRef?: ref<customer.Customer @ 1>
    @wire(json.case: "snake_case")
    legacyState: enum(open, closed)
    @server
    createdAt: timestamp

    reserved protobuf {
      numbers: [9]
      names: ["legacyNote"]
    }
  }

  entity Invoice @ 2 (breaking) {
    @key invoiceId: uuid
    amount: decimal(12, 2) constraint { min: 0 } = 0
    loyaltyPoints?: int = 0
    state: enum(draft, issued, voided)
    customerRef?: ref<customer.Customer @ 1>
    legacyState: enum(open, closed)

    reserved protobuf {
      numbers: [9]
      names: ["legacyNote"]
    }
  }

  index Invoice @ 1 {
    primary invoiceId
    secondary byState {
      key: [state]
    }
  }

  projection InvoiceSummary @ 1
    from billing.Invoice @ 1 as i
  {
    invoiceId <- i.invoiceId
    amount <- i.amount
    state <- i.state
  }
}
"""

CUSTOMER_MDL = """
domain customer {
  owner: "customer-team"

  entity Customer @ 1 (additive) {
    @key customerId: uuid
    displayName: string
  }

  auto projections Customer @ 1 {
    reply
  }
}
"""


def load_normalized(*texts: str) -> Workspace:
    """Load the given .mdl texts through the single normalization boundary."""
    sources = [
        WorkspaceDocumentSource(
            path=Path(f"source_{index}.mdl"),
            uri=f"file:///source_{index}.mdl",
            text=text,
        )
        for index, text in enumerate(texts)
    ]
    return load_workspace_from_sources(sources)


def assert_normalized_ir_equal(left: Workspace, right: Workspace) -> None:
    """Assert two normalized workspaces carry identical canonical contracts."""
    assert left.mdl.model_dump() == right.mdl.model_dump()
    assert left.errors == right.errors


def collect_version_signatures(workspace: Workspace) -> dict[tuple[str, str, int], str]:
    """Keyed signature map for every model and projection version."""
    signatures: dict[tuple[str, str, int], str] = {}
    for domain in workspace.mdl.domains:
        for model_name, versions in domain.models.items():
            for version in versions:
                signatures[(domain.name, model_name, version.version)] = compute_version_signature(
                    domain.name, model_name, version
                )
        for projection_name, versions in domain.projections.items():
            for version in versions:
                signatures[(domain.name, projection_name, version.version)] = compute_version_signature(
                    domain.name, projection_name, version
                )
    return signatures


def _change_is_breaking(change) -> bool:
    return is_field_change_breaking(change)


def test_double_load_produces_identical_normalized_ir_and_signatures():
    first = load_normalized(BILLING_MDL, CUSTOMER_MDL)
    second = load_normalized(BILLING_MDL, CUSTOMER_MDL)

    assert not first.errors
    assert_normalized_ir_equal(first, second)
    assert collect_version_signatures(first) == collect_version_signatures(second)


def test_signatures_are_stable_across_source_order():
    forward = load_normalized(BILLING_MDL, CUSTOMER_MDL)
    backward = load_normalized(CUSTOMER_MDL, BILLING_MDL)

    assert not backward.errors
    # Domain order follows source order, but per-version canonical signatures
    # must not depend on it.
    assert collect_version_signatures(forward).keys() == collect_version_signatures(backward).keys()
    assert collect_version_signatures(forward) == {
        key: collect_version_signatures(backward)[key] for key in collect_version_signatures(forward)
    }


def test_semantic_diff_equal_across_independent_loads():
    first = load_normalized(BILLING_MDL, CUSTOMER_MDL)
    second = load_normalized(BILLING_MDL, CUSTOMER_MDL)

    def diff(workspace):
        invoice = next(domain for domain in workspace.mdl.domains if domain.name == "billing").models["Invoice"]
        v1 = next(item for item in invoice if item.version == 1)
        v2 = next(item for item in invoice if item.version == 2)
        return [
            (change.kind, change.field_name, _change_is_breaking(change)) for change in compare_model_versions(v1, v2)
        ]

    assert diff(first) == diff(second)
    kinds = {kind for kind, _field, _is_breaking in diff(first)}
    assert "type_changed" in kinds  # decimal(10,2) -> decimal(12,2) is breaking
    removed = [change for change in diff(first) if change[0] == "removed_field"]
    assert any(change[1] == "notes" and change[2] for change in removed)


def test_projection_resolution_over_merged_workspace():
    workspace = load_normalized(BILLING_MDL, CUSTOMER_MDL)

    # Cross-domain ref<> resolves only through the merged, expanded IR.
    resolved = resolve_model_ref(workspace.mdl, "customer.Customer", 1)
    assert resolved.domain_name == "customer"

    summary = resolved_domain_projections(workspace)
    assert "InvoiceSummary" in summary
    assert [field.name for field in summary["InvoiceSummary"][0].fields] == ["invoiceId", "amount", "state"]


def resolved_domain_projections(workspace):
    billing = next(domain for domain in workspace.mdl.domains if domain.name == "billing")
    return billing.projections


def test_representative_output_equality_across_loads():
    first = emit_json_schema_artifacts(load_normalized(BILLING_MDL, CUSTOMER_MDL))
    second = emit_json_schema_artifacts(load_normalized(BILLING_MDL, CUSTOMER_MDL))

    by_id = lambda artifacts: {artifact.artifact_id: artifact.content_hash for artifact in artifacts}  # noqa: E731
    assert by_id(first) == by_id(second)
    assert set(by_id(first)) >= {"billing.Invoice.v1", "billing.Invoice.v2"}


def test_cross_file_refs_resolve_only_through_the_normalization_boundary():
    # Canonical reference state depends on the *complete* normalized source set:
    # loaded alone, the same well-formed billing source reports an unresolvable
    # cross-domain ref...
    alone = load_normalized(BILLING_MDL)
    alone_errors = [d.message for d in alone.errors]
    assert any("customerRef" in message for message in alone_errors), alone_errors

    # ...while through the boundary over the complete set it is clean.
    workspace = load_normalized(BILLING_MDL, CUSTOMER_MDL)
    boundary_errors = [d.message for d in workspace.errors]
    assert not any("customerRef" in message for message in boundary_errors), boundary_errors

    # Per-file parsing-level IR never validates references at all — which is
    # exactly why it must not be treated as canonical contract state.
    from modelable.validation.semantic import validate_diagnostics

    per_file_errors = [d.message for d in validate_diagnostics(parse_text_to_ir(BILLING_MDL))]
    assert not any("customerRef" in message for message in per_file_errors), per_file_errors


def test_single_source_still_reports_its_own_errors_through_the_boundary():
    broken = """
domain lonely {
  owner: "lonely-team"
  entity Thing @ 1 (additive) {
    @key thingId: uuid
    otherRef: ref<missing.Nowhere @ 1>
  }
}
"""
    workspace = load_normalized(BILLING_MDL, CUSTOMER_MDL, broken)
    assert any("otherRef" in d.message for d in workspace.errors)


@pytest.mark.parametrize("text", [BILLING_MDL, CUSTOMER_MDL])
def test_fixture_sources_are_individually_parseable(text):
    # The fixture itself must stay well-formed; this keeps the shared fixture
    # usable by future slices without silently rotting.
    parse_text_to_ir(text)
