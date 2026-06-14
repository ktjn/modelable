from modelable.parser.parse import parse_text_to_ir
from modelable.parser.ir import VersionRange, VersionMin, VersionPinned
from modelable.registry.resolver import resolve_model_ref
from modelable.registry.signature import compute_version_signature


def test_version_range_resolves_to_highest_satisfying_version():
    mdl = parse_text_to_ir(
        """
        domain customer {
          owner: "test-team"
          entity Customer @ 1 (additive) { @key id: uuid }
          entity Customer @ 2 (additive) { @key id: uuid }
          entity Customer @ 3 (breaking) { @key id: uuid }
        }
        """
    )

    # Range [1, 3) should resolve to 2
    source_ref = "customer.Customer"
    version_range = VersionRange(min_inclusive=1, max_exclusive=3)
    resolved = resolve_model_ref(mdl, source_ref, version_range)
    assert resolved.version.version == 2


def test_version_range_resolution_with_exact_pin():
    mdl = parse_text_to_ir(
        """
        domain customer {
          owner: "test-team"
          entity Customer @ 1 (additive) { @key id: uuid }
          entity Customer @ 2 (additive) { @key id: uuid }
        }
        """
    )

    # Exact pin 1 (integer)
    source_ref = "customer.Customer"
    resolved = resolve_model_ref(mdl, source_ref, 1)
    assert resolved.version.version == 1


def test_version_range_resolution_unbounded_upper():
    mdl = parse_text_to_ir(
        """
        domain customer {
          owner: "test-team"
          entity Customer @ 1 (additive) { @key id: uuid }
          entity Customer @ 2 (additive) { @key id: uuid }
          entity Customer @ 5 (additive) { @key id: uuid }
        }
        """
    )

    # Range >=1 should resolve to 5
    source_ref = "customer.Customer"
    version_range = VersionMin(min_inclusive=1)
    resolved = resolve_model_ref(mdl, source_ref, version_range)
    assert resolved.version.version == 5


def test_version_pinned_resolves_with_matching_signature():
    mdl = parse_text_to_ir(
        """
        domain customer {
          owner: "test-team"
          entity Customer @ 1 (additive) { @key id: uuid }
        }
        """
    )
    v1 = mdl.domains[0].models["Customer"][0]
    signature = compute_version_signature("customer", "Customer", v1)

    source_ref = "customer.Customer"
    version_pinned = VersionPinned(version=1, content_hash=signature)
    resolved = resolve_model_ref(mdl, source_ref, version_pinned)
    assert resolved.version.version == 1


def test_version_range_resolution_fails_on_unsatisfied_range():
    mdl = parse_text_to_ir(
        """
        domain customer {
          owner: "test-team"
          entity Customer @ 1 (additive) { @key id: uuid }
        }
        """
    )

    import pytest
    source_ref = "customer.Customer"
    version_range = VersionMin(min_inclusive=2)
    with pytest.raises(LookupError, match="unresolved model reference"):
        resolve_model_ref(mdl, source_ref, version_range)


def test_version_range_resolution_fails_if_breaking_change_in_range():
    mdl = parse_text_to_ir(
        """
        domain customer {
          owner: "test-team"
          entity Customer @ 1 (additive) { @key id: uuid }
          entity Customer @ 2 (breaking) { @key id: uuid }
          entity Customer @ 3 (additive) { @key id: uuid }
        }
        """
    )

    import pytest
    source_ref = "customer.Customer"
    # Range >=1 should find 3, but 2 is breaking relative to 1.
    # So it should not automatically resolve past 2.
    version_range = VersionMin(min_inclusive=1)
    
    # Current implementation might just take the max. Let's see.
    with pytest.raises(LookupError, match="breaking change"):
        resolve_model_ref(mdl, source_ref, version_range)
