"""Production correspondence and regression tests for formal TLA+ specifications.

Architecture reference: docs/tla-formal-verification.md
Formal specification: formal/tla/ModelLifecycle.tla
"""

from __future__ import annotations

import pytest

from modelable.lifecycle import (
    LifecycleError,
    LifecycleState,
    find_lifecycle_reference_findings,
    parse_lifecycle_document,
    validate_lifecycle_transition,
)
from modelable.parser.ir import VersionExact, VersionMin, VersionRange
from modelable.parser.parse import parse_text_to_ir
from modelable.registry.resolver import (
    _iter_declaration_candidates,
    resolve_declaration,
    resolve_model_ref,
    resolved_version_spec,
)
from modelable.registry.signature import compute_version_signature


def test_formal_published_is_known() -> None:
    """Invariant: PublishedIsKnown.

    Every published version in a workspace must be present in the candidate/known pool.
    """
    mdl = parse_text_to_ir(
        """
        domain catalog {
          owner: "catalog-team"
          entity Product @ 1 (additive) {
            @key productId: uuid
          }
          entity Product @ 2 (additive) {
            @key productId: uuid
            name?: string
          }
        }
        """
    )
    candidates = list(_iter_declaration_candidates(mdl))
    candidate_identities = {f"{c.domain_name}.{c.name}@{c.version_number}" for c in candidates}

    assert "catalog.Product@1" in candidate_identities
    assert "catalog.Product@2" in candidate_identities


def test_formal_published_fingerprint_unchanged() -> None:
    """Invariant: PublishedFingerprintUnchanged.

    A published declaration's semantic signature is immutable for identical semantics
    and changes whenever fields or types change.
    """
    mdl_initial = parse_text_to_ir(
        """
        domain orders {
          owner: "orders-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            amount: decimal(10, 2)
          }
        }
        """
    )
    product_v1 = mdl_initial.domains[0].models["Order"][0]
    sig1 = compute_version_signature("orders", "Order", product_v1)

    # Identical structure yields identical signature
    mdl_reloaded = parse_text_to_ir(
        """
        domain orders {
          owner: "orders-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            amount: decimal(10, 2)
          }
        }
        """
    )
    product_v1_reloaded = mdl_reloaded.domains[0].models["Order"][0]
    sig2 = compute_version_signature("orders", "Order", product_v1_reloaded)
    assert sig1 == sig2

    # Modified structure yields distinct signature
    mdl_modified = parse_text_to_ir(
        """
        domain orders {
          owner: "orders-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            amount: decimal(12, 4)
          }
        }
        """
    )
    product_v1_modified = mdl_modified.domains[0].models["Order"][0]
    sig3 = compute_version_signature("orders", "Order", product_v1_modified)
    assert sig1 != sig3


def test_formal_retired_is_published() -> None:
    """Invariant: RetiredIsPublished.

    A declaration version can only reach 'retired' state by progressing monotonically
    through candidate -> published -> deprecated -> retired.
    """
    # Direct candidate -> retired transition is forbidden
    with pytest.raises(LifecycleError, match="cannot transition lifecycle from 'candidate' to 'retired'"):
        validate_lifecycle_transition(LifecycleState.candidate, LifecycleState.retired)

    # Monotonic lifecycle transitions succeed
    validate_lifecycle_transition(LifecycleState.candidate, LifecycleState.published)
    validate_lifecycle_transition(LifecycleState.published, LifecycleState.deprecated)
    validate_lifecycle_transition(LifecycleState.deprecated, LifecycleState.retired)


def test_formal_active_consumer_never_references_retired() -> None:
    """Invariant: ActiveConsumerNeverReferencesRetired.

    Active consumers referencing retired versions must be surfaced as high-severity findings
    blocking safe retirement.
    """
    lifecycle = parse_lifecycle_document(
        {
            "$schema": "modelable.lifecycle/v1",
            "entries": [
                {"identity": "catalog.Product@1", "state": "retired"},
                {"identity": "catalog.Product@2", "state": "published"},
            ],
        }
    )

    objects = [
        {"identity": "billing.Invoice@1", "dependencies": ["catalog.Product@1"]},
        {"identity": "shipping.Delivery@1", "dependencies": ["catalog.Product@2"]},
    ]

    findings = find_lifecycle_reference_findings(objects, lifecycle)
    assert findings == [
        {"source": "billing.Invoice@1", "target": "catalog.Product@1", "state": "retired"},
    ]


def test_formal_resolution_is_exact() -> None:
    """Invariant: ResolutionIsExact.

    Persisted resolution of a model reference is always a concrete, exact version,
    never an open range or mutable tag.
    """
    mdl = parse_text_to_ir(
        """
        domain billing {
          owner: "billing-team"
          entity Account @ 1 (additive) {
            @key id: uuid
          }
          entity Account @ 2 (additive) {
            @key id: uuid
            name?: string
          }
        }
        """
    )

    exact = resolved_version_spec(mdl, "billing.Account", VersionMin(min_inclusive=1))
    assert isinstance(exact, VersionExact)
    assert exact.version == 2


def test_formal_compatibility_is_explicit_breaking_blocks() -> None:
    """Invariant: CompatibilityIsExplicit.

    Missing compatibility is never assumed compatible; breaking changes explicitly block
    range resolution.
    """
    mdl = parse_text_to_ir(
        """
        domain payments {
          owner: "payments-team"
          entity Payment @ 1 (additive) {
            @key paymentId: uuid
          }
          entity Payment @ 2 (breaking) {
            @key paymentId: uuid
            requiredToken: string
          }
        }
        """
    )

    # Range >=1 <3 encounters breaking change at v2 and must fail resolution
    with pytest.raises(LookupError, match="breaking change at version 2 blocks automatic resolution"):
        resolve_model_ref(mdl, "payments.Payment", VersionRange(min_inclusive=1, max_exclusive=3))


def test_formal_no_evidence_is_not_safety() -> None:
    """Invariant: NoEvidenceIsNotSafety.

    An empty recorded usage set alone cannot autorun or justify retirement; retirement
    requires an explicit authoritative lifecycle metadata document with state 'retired'.
    """
    # Without explicit retirement in the lifecycle document, state remains published or deprecated
    lifecycle = parse_lifecycle_document(
        {
            "$schema": "modelable.lifecycle/v1",
            "entries": [
                {"identity": "users.User@1", "state": "deprecated"},
            ],
        }
    )
    # Even when no consumer objects exist, the declaration is NOT retired
    objects: list[dict[str, object]] = []
    findings = find_lifecycle_reference_findings(objects, lifecycle)
    assert findings == []
    assert lifecycle["entries"][0]["state"] == "deprecated"


def test_formal_deterministic_resolution() -> None:
    """Invariant: DeterministicResolution.

    Resolving a requirement across multiple candidate versions must deterministically
    select the maximum matching compatible version.
    """
    mdl = parse_text_to_ir(
        """
        domain inventory {
          owner: "inv-team"
          entity Stock @ 1 (additive) {
            @key id: uuid
          }
          entity Stock @ 2 (additive) {
            @key id: uuid
            qty?: int
          }
          entity Stock @ 3 (additive) {
            @key id: uuid
            qty?: int
            warehouse?: string
          }
        }
        """
    )

    resolved_decl = resolve_declaration(mdl, "inventory.Stock", VersionMin(min_inclusive=1))
    assert resolved_decl.version_number == 3

    resolved_min = resolve_model_ref(mdl, "inventory.Stock", VersionMin(min_inclusive=1))
    assert resolved_min.version.version == 3

    resolved_range = resolve_model_ref(mdl, "inventory.Stock", VersionRange(min_inclusive=1, max_exclusive=3))
    assert resolved_range.version.version == 2


def test_formal_tlc_counterexample_trace_safe_retirement_gate() -> None:
    """Regression test corresponding to TLC counterexample 1.

    Sequence:
    1. Candidate v1 admitted & published.
    2. Deprecate v1.
    3. Consumer c1 resolves and records dependency on v1.
    4. Gating check before retirement must detect c1 dependency and reject retirement.
    """
    # Consumer c1 recorded
    consumer_objects = [
        {"identity": "orders.OrderService@1", "dependencies": ["catalog.Product@1"]},
    ]

    # Proposed lifecycle state: retired
    proposed_lifecycle = {
        "$schema": "modelable.lifecycle/v1",
        "entries": [
            {"identity": "catalog.Product@1", "state": "retired"},
        ],
    }

    # Gate check
    findings = find_lifecycle_reference_findings(consumer_objects, proposed_lifecycle)
    assert len(findings) == 1
    assert findings[0]["target"] == "catalog.Product@1"
    assert findings[0]["state"] == "retired"
    # The active consumer prevents safe retirement!
