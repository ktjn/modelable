"""Slice G3: capability-manifest-to-test linkage.

Before this file, a `Capability.notes` string could claim a deferred status
that no longer matched the compiler (or never did), and nothing would catch
the drift -- `test_capabilities.py` checks the manifest is internally
consistent, not that a `deferred` entry's claim is actually demonstrated by
a passing test. This file resolves every `Capability.test_refs` entry to a
real, collected test function, and requires every `deferred_feature`
capability to either carry one or be explicitly acknowledged as not yet
linked in `_KNOWN_UNLINKED_DEFERRED_FEATURES` below.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from modelable.capabilities import CapabilityStatus, build_capability_manifest

# Deferred features not yet linked to a proving test. Each entry here is a
# known, acknowledged gap (see capabilities.py's `notes` for why), not a
# silent one -- adding a new deferred_feature capability without either a
# test_refs entry or an entry here fails test_every_deferred_feature_is_linked_or_acknowledged.
_KNOWN_UNLINKED_DEFERRED_FEATURES = {
    "nominal-semantic-types-beyond-rust",
    "projection-event-operation-coverage-compatibility",
}


def _resolve_test_ref(test_ref: str):
    file_part, separator, func_name = test_ref.partition("::")
    assert separator == "::", f"test_ref {test_ref!r} must be 'test_file.py::test_function_name'"
    module_name = Path(file_part).stem
    module = importlib.import_module(module_name)
    return getattr(module, func_name)


def test_every_test_ref_resolves_to_a_real_test_function():
    manifest = build_capability_manifest()

    for capability in manifest.all():
        for test_ref in capability.test_refs:
            func = _resolve_test_ref(test_ref)
            assert callable(func), f"{capability.name}'s test_ref {test_ref!r} is not callable"
            assert func.__name__.startswith("test_"), (
                f"{capability.name}'s test_ref {test_ref!r} does not point at a test function"
            )


def test_every_deferred_feature_is_linked_or_acknowledged():
    manifest = build_capability_manifest()
    deferred_names = {capability.name for capability in manifest.deferred_features}

    unlinked = {
        capability.name
        for capability in manifest.deferred_features
        if capability.status is CapabilityStatus.deferred and not capability.test_refs
    }

    assert unlinked == _KNOWN_UNLINKED_DEFERRED_FEATURES

    # The acknowledged-gap list itself must not rot: every name in it should
    # still be a real, currently-unlinked deferred capability.
    stale = _KNOWN_UNLINKED_DEFERRED_FEATURES - deferred_names
    assert stale == set(), f"acknowledged as unlinked but no longer in the manifest: {stale}"


@pytest.mark.parametrize(
    "name",
    [
        "composite-keys",
        "model-lifecycle-status",
        "workspace-registry",
        "workspace-peers",
        "consumer-declarations",
        "subscriptions",
        "materialisation",
        "binding-opaque-content",
    ],
)
def test_named_deferred_feature_has_at_least_one_test_ref(name: str):
    manifest = build_capability_manifest()
    capability = next(c for c in manifest.deferred_features if c.name == name)

    assert capability.test_refs
