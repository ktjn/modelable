from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from modelable.emitters.sql import SQL_DIALECTS
from modelable.emitters.targets import CODEGEN_TARGETS
from modelable.parser.ir import ModelKind


class CapabilityStatus(StrEnum):
    """One of the five capability statuses exposed by Modelable."""

    implemented = "implemented"
    experimental = "experimental"
    deferred = "deferred"
    candidate = "candidate"
    removed = "removed"


@dataclass(frozen=True)
class Capability:
    name: str
    category: str
    status: CapabilityStatus
    description: str
    notes: str | None = None
    # Test references prove capability status against implementation. The historical
    # origin of this linkage is archived as ROADMAP.md Slice G3.
    test_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class CapabilityManifest:
    targets: tuple[Capability, ...]
    sql_dialects: tuple[Capability, ...]
    model_kinds: tuple[Capability, ...]
    annotations: tuple[Capability, ...]
    deferred_features: tuple[Capability, ...]

    def all(self) -> tuple[Capability, ...]:
        return self.targets + self.sql_dialects + self.model_kinds + self.annotations + self.deferred_features


_MODEL_KIND_DESCRIPTIONS: dict[str, str] = {
    "entity": "A model with a single stable identity, mutable over time",
    "aggregate": "A model composed of related entities under one consistency boundary",
    "event": "An immutable fact emitted at a point in time",
    "value": "A model with no independent identity, embedded within another model",
}

_ANNOTATION_DESCRIPTIONS: dict[str, str] = {
    "key": "Marks a field as the model's identity field",
    "pii": "Marks a field as personally identifiable information",
    "classification": "Sets a field's data-classification level",
    "deprecated": "Marks a field as deprecated in favor of a named replacement",
    "owner": "Attaches an owning team to a declaration",
    "server": "Marks a field as server-assigned, excluded from write models",
    "wire": "Attaches target-specific wire representation hints to a field",
    "pit_cutoff": "Attaches a point-in-time cutoff expression to a join",
    "latest_before": "Attaches a latest-before expression to a join",
    "latest_only": "Restricts a join to only the latest matching row",
    "custom": "Attaches an opaque, target-defined annotation",
}

_DEFERRED_FEATURES: tuple[Capability, ...] = (
    Capability(
        name="composite-keys",
        category="deferred_feature",
        status=CapabilityStatus.deferred,
        description="Multiple @key fields on a single entity or aggregate",
        notes=(
            "docs/architecture.md records the current invariant: exactly one @key field "
            "per entity/aggregate. Composite keys remain deferred; see ROADMAP.md Slice D5 "
            "(legacy mapping) and Phase 2 for declaration-model stabilization."
        ),
        test_refs=("test_semantic.py::test_composite_key_is_not_yet_supported",),
    ),
    Capability(
        name="model-lifecycle-status",
        category="deferred_feature",
        status=CapabilityStatus.deferred,
        description="Draft, published, deprecated, and retired version status",
        notes=(
            "docs/architecture.md explicitly records that lifecycle status is not represented "
            "in the current stable grammar or IR. See ROADMAP.md Slice D6 (legacy mapping)."
        ),
        test_refs=("test_capabilities.py::test_model_version_has_no_lifecycle_status_field",),
    ),
    Capability(
        name="nominal-semantic-types-beyond-rust",
        category="deferred_feature",
        status=CapabilityStatus.deferred,
        description="Preserving semantic-type nominal identity in targets other than Rust, Protobuf, and gRPC",
        notes=(
            "Other targets resolve a semantic type reference structurally today. "
            "See ROADMAP.md Slice F1 (legacy mapping) and Phase 5 capability negotiation. "
            "Not yet linked to a proving test; the intended output for each target needs "
            "target-specific scoping before implementation."
        ),
    ),
    Capability(
        name="workspace-registry",
        category="deferred_feature",
        status=CapabilityStatus.deferred,
        description="Workspace-level `registry {}` configuration",
        notes=(
            "Parses but is discarded before IR construction; has no effect on compilation. "
            "The stabilization disposition is retain + explicit DEFERRED diagnostic; see ROADMAP.md "
            "Current/deferred syntax disposition and legacy Slice B3."
        ),
        test_refs=("test_deferred_syntax.py::test_workspace_registry_block_produces_deferred_warning",),
    ),
    Capability(
        name="workspace-peers",
        category="deferred_feature",
        status=CapabilityStatus.deferred,
        description="Workspace-level `peers: [...]` federation declarations",
        notes=(
            "Parses but is discarded before IR construction; has no effect on compilation. "
            "Peer identifiers referenced elsewhere are checked by a separate editor-only text scan. "
            "The stabilization disposition is retain + explicit DEFERRED diagnostic; see legacy Slice B3."
        ),
        test_refs=("test_deferred_syntax.py::test_workspace_peers_block_produces_deferred_warning",),
    ),
    Capability(
        name="consumer-declarations",
        category="deferred_feature",
        status=CapabilityStatus.deferred,
        description="Top-level `consumer {}` declarations",
        notes=(
            "Parses but is discarded before IR construction; consumer registration and impact analysis "
            "have no effect. Retained with DEFERRED diagnostics for language stability; Phase 7 prefers "
            "derived usage evidence."
        ),
        test_refs=("test_deferred_syntax.py::test_top_level_consumer_declaration_produces_deferred_warning",),
    ),
    Capability(
        name="subscriptions",
        category="deferred_feature",
        status=CapabilityStatus.deferred,
        description="Per-projection and top-level `subscription {}` declarations",
        notes=(
            "Parses but is discarded before IR construction; no runtime subscription behavior is implemented. "
            "Retained with explicit DEFERRED diagnostics; runtime execution remains outside the core roadmap."
        ),
        test_refs=(
            "test_deferred_syntax.py::test_top_level_subscription_declaration_produces_deferred_warning",
            "test_deferred_syntax.py::test_projection_subscription_block_produces_deferred_warning",
        ),
    ),
    Capability(
        name="materialisation",
        category="deferred_feature",
        status=CapabilityStatus.deferred,
        description="Per-projection `materialisation {}` declarations",
        notes=(
            "Parses but is discarded before IR construction; no runtime materialization is implemented. "
            "Retained with explicit DEFERRED diagnostics; runtime execution remains outside the core roadmap."
        ),
        test_refs=("test_deferred_syntax.py::test_projection_materialisation_block_produces_deferred_warning",),
    ),
    Capability(
        name="binding-opaque-content",
        category="deferred_feature",
        status=CapabilityStatus.deferred,
        description="Unrecognized keys inside `binding {}` beyond `adapter`, `model`, and `table`",
        notes=(
            "Parses but is discarded before IR construction; only `adapter`, `model`, and `table` are honored today. "
            "Unsupported opaque content remains explicitly DEFERRED under the stabilization language-stability rule."
        ),
        test_refs=(
            "test_deferred_syntax.py::test_binding_opaque_content_produces_one_deferred_warning_per_unrecognized_key",
        ),
    ),
    Capability(
        name="projection-event-operation-coverage-compatibility",
        category="deferred_feature",
        status=CapabilityStatus.deferred,
        description="Comparing event operation coverage between two projection versions",
        notes=(
            "AutoProjectionTarget.operations only exists on the pre-expansion `auto projections {}` declaration "
            "and is discarded during expansion; it is not present on the resulting ProjectionVersion to diff. "
            "See legacy Slice C1 and Phase 10 layered compatibility. Not yet linked to a proving test."
        ),
    ),
)


def build_capability_manifest() -> CapabilityManifest:
    targets = tuple(
        Capability(
            name=target.name,
            category="target",
            status=CapabilityStatus.implemented if target.status == "implemented" else CapabilityStatus.deferred,
            description=target.description,
        )
        for target in CODEGEN_TARGETS
    )
    sql_dialects = tuple(
        Capability(
            name=dialect.name,
            category="sql_dialect",
            status=CapabilityStatus.implemented,
            description=dialect.description,
        )
        for dialect in SQL_DIALECTS
    )
    model_kinds = tuple(
        Capability(
            name=kind.value,
            category="model_kind",
            status=CapabilityStatus.implemented,
            description=_MODEL_KIND_DESCRIPTIONS[kind.value],
        )
        for kind in ModelKind
    )
    annotations = tuple(
        Capability(
            name=name,
            category="annotation",
            status=CapabilityStatus.implemented,
            description=description,
        )
        for name, description in _ANNOTATION_DESCRIPTIONS.items()
    )
    return CapabilityManifest(
        targets=targets,
        sql_dialects=sql_dialects,
        model_kinds=model_kinds,
        annotations=annotations,
        deferred_features=_DEFERRED_FEATURES,
    )
