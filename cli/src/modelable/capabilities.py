from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from modelable.emitters.sql import SQL_DIALECTS
from modelable.emitters.targets import CODEGEN_TARGETS
from modelable.parser.ir import ModelKind


class CapabilityStatus(StrEnum):
    """One of the five statuses docs/correction-and-capability-plan.md Slice B2 standardizes on."""

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
    # "test_file.py::test_function_name" references (Slice G3) that prove this
    # capability's status is accurate. Checked by test_capability_manifest_linkage.py,
    # so a status claim can't silently drift from what the test suite actually verifies.
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
            "docs/architecture.md describes this as supported; "
            "cli/src/modelable/validation/semantic.py requires exactly one @key field "
            "per entity/aggregate today. See Slice D5 in docs/correction-and-capability-plan.md."
        ),
        test_refs=("test_semantic.py::test_composite_key_is_not_yet_supported",),
    ),
    Capability(
        name="clickhouse-secondary-indexes",
        category="deferred_feature",
        status=CapabilityStatus.deferred,
        description="Secondary index declarations emitted as ClickHouse DDL",
        notes=(
            "Only the sql-postgres target emits index declarations today; "
            "sql-clickhouse emits a bare MergeTree table with no secondary indexes."
        ),
        test_refs=("test_emit_sql.py::test_clickhouse_ddl_does_not_include_secondary_index",),
    ),
    Capability(
        name="model-lifecycle-status",
        category="deferred_feature",
        status=CapabilityStatus.deferred,
        description="Draft, published, deprecated, and retired version status",
        notes=(
            "docs/architecture.md describes this lifecycle; it is not represented in the "
            "current stable grammar or IR. See Slice D6 in docs/correction-and-capability-plan.md."
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
            "See Slice F1 in docs/correction-and-capability-plan.md and ROADMAP.md Priority 4 item 4. "
            "Not yet linked to a proving test (see Slice G3 outcome note) -- what the other targets' "
            "output should look like structurally needs its own small scoping pass first."
        ),
    ),
    Capability(
        name="workspace-registry",
        category="deferred_feature",
        status=CapabilityStatus.deferred,
        description="Workspace-level `registry {}` configuration",
        notes=(
            "Parses but is discarded before IR construction; has no effect on compilation. "
            "See Slice B3 in docs/correction-and-capability-plan.md."
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
            "Peer identifiers referenced elsewhere are checked by a separate editor-only "
            "text scan, not this declaration. See Slice B3 in docs/correction-and-capability-plan.md."
        ),
        test_refs=("test_deferred_syntax.py::test_workspace_peers_block_produces_deferred_warning",),
    ),
    Capability(
        name="consumer-declarations",
        category="deferred_feature",
        status=CapabilityStatus.deferred,
        description="Top-level `consumer {}` declarations",
        notes=(
            "Parses but is discarded before IR construction; consumer registration and "
            "impact analysis have no effect. See Slice B3 in docs/correction-and-capability-plan.md."
        ),
        test_refs=("test_deferred_syntax.py::test_top_level_consumer_declaration_produces_deferred_warning",),
    ),
    Capability(
        name="subscriptions",
        category="deferred_feature",
        status=CapabilityStatus.deferred,
        description="Per-projection and top-level `subscription {}` declarations",
        notes=(
            "Parses but is discarded before IR construction; no runtime subscription "
            "behavior is implemented. See Slice B3 in docs/correction-and-capability-plan.md."
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
            "Parses but is discarded before IR construction; no runtime materialization "
            "is implemented. See Slice B3 in docs/correction-and-capability-plan.md."
        ),
        test_refs=("test_deferred_syntax.py::test_projection_materialisation_block_produces_deferred_warning",),
    ),
    Capability(
        name="binding-opaque-content",
        category="deferred_feature",
        status=CapabilityStatus.deferred,
        description="Unrecognized keys inside `binding {}` beyond `adapter`, `model`, and `table`",
        notes=(
            "Parses but is discarded before IR construction; only `adapter`, `model`, and "
            "`table` are honored today. See Slice B3 in docs/correction-and-capability-plan.md."
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
            "AutoProjectionTarget.operations only exists on the pre-expansion "
            "`auto projections {}` declaration and is discarded during "
            "expansion; it is not present on the resulting ProjectionVersion "
            "to diff. See Slice C1 in docs/correction-and-capability-plan.md. "
            "Not yet linked to a proving test (see Slice G3 outcome note)."
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
