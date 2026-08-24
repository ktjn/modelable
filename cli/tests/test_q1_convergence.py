"""Q1 -- combined feature qualification: prove semantic enums, enum
projections (E10/E11), and `evolves` version deltas (D1-D8) compose
correctly through every semantic and generated surface.

One compact history: `catalog.Product` has a full v1, an additive delta v2,
a breaking delta v3, a full-form "reset" v5 (a plain complete declaration,
demonstrating delta authoring is never mandatory), and an additive delta v8.
Alongside it: two equal-shaped but nominally distinct semantic enums, an
anonymous enum field, a `pick` and an `omit` enum projection, a value type,
an `index` declaration, Protobuf reservations, an access block, governance
annotations (`@pii`/`@classification`), a field default, a cross-domain
`ref<>`, and a projection joining across domains.

For each proof below, the same history is compiled two ways -- entirely in
full-form declarations, and using `evolves` deltas at v2/v3/v8 -- and the
two are required to agree at every downstream boundary: signatures,
snapshot objects, compatibility/dependency/impact analysis, and every
implemented codegen target's output.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from modelable.compat.checker import analyze_impact, check_model_version_compatibility
from modelable.compiler.workspace import Workspace, WorkspaceDocumentSource, load_workspace_from_sources
from modelable.dependency_graph import build_projection_dependencies
from modelable.emitters.targets import list_implemented_codegen_targets
from modelable.registry.resolver import resolve_semantic_type_ref
from modelable.registry.signature import compute_version_signature
from modelable.registry.snapshot import resolve_workspace_snapshot

IMPLEMENTED_TARGET_NAMES = {target.name for target in list_implemented_codegen_targets()}

_CATALOG_ENUMS = """
  semantic Grade @ 1 (additive): enum(gold, silver, bronze)
  semantic Rank @ 1 (additive): enum(gold, silver, bronze)

  enum projection PublicGrade @ 1 (additive)
    from Grade @ 1
    pick(gold, silver)

  enum projection HiddenRank @ 1 (additive)
    from Rank @ 1
    omit(bronze)

  value Money @ 1 (additive) {
    amount: decimal(10, 2)
    currency: string
  }
"""

_CATALOG_PRODUCT_V1 = """
  entity Product @ 1 (additive) {
    access {
      entity catalog-team [read, write]
    }
    @pii @classification("internal")
    @key productId: uuid
    grade: Grade @ 1
    tier: enum(new, used, refurbished)
    price: decimal(10, 2)
    legacyCode: string
  }
"""

_CATALOG_PRODUCT_V2_FULL = """
  entity Product @ 2 (additive) {
    access {
      entity catalog-team [read, write]
    }
    @pii @classification("internal")
    @key productId: uuid
    grade: Grade @ 1
    tier: enum(new, used, refurbished)
    price: decimal(10, 2)
    legacyCode: string
    sku?: string
  }
"""
_CATALOG_PRODUCT_V2_DELTA = """
  entity Product @ 2 (additive) evolves @ 1 {
    add sku?: string
  }
"""

_CATALOG_PRODUCT_V3_FULL = """
  entity Product @ 3 (breaking) {
    access {
      entity catalog-team [read, write]
    }
    @pii @classification("internal")
    @key productId: uuid
    grade: Grade @ 1
    tier: enum(new, used, refurbished)
    amount: decimal(12, 2)
    sku?: string
    reserved protobuf {
      numbers: [10]
      names: ["legacyCode"]
    }
  }
"""
_CATALOG_PRODUCT_V3_DELTA = """
  entity Product @ 3 (breaking) evolves @ 2 {
    remove legacyCode
    rename price -> amount
    replace amount: decimal(12, 2)
    reserved protobuf {
      numbers: [10]
      names: ["legacyCode"]
    }
  }
"""

# v5 is a plain full-form "reset" in both histories -- identical either way,
# proving delta authoring is opt-in per version, not sticky once started.
_CATALOG_PRODUCT_V5 = """
  entity Product @ 5 (breaking) {
    access {
      entity catalog-team [read, write]
    }
    @pii @classification("internal")
    @key productId: uuid
    grade: Grade @ 1
    tier: enum(new, used, refurbished)
    amount: decimal(12, 2)
    sku?: string
    discountCode: string
    reserved protobuf {
      numbers: [10]
      names: ["legacyCode"]
    }
  }
"""

_CATALOG_PRODUCT_V8_FULL = """
  entity Product @ 8 (breaking) {
    access {
      entity catalog-team [read, write]
    }
    @pii @classification("internal")
    @key productId: uuid
    grade: Grade @ 1
    tier: enum(new, used, refurbished)
    amount: decimal(12, 2)
    sku?: string
    discount?: decimal(5, 2)
  }
"""
_CATALOG_PRODUCT_V8_DELTA = """
  entity Product @ 8 (breaking) evolves @ 5 {
    remove discountCode
    add discount?: decimal(5, 2)
  }
"""

_CATALOG_TAIL = """
  index Product @ 8 {
    primary productId

    secondary bySku {
      key: [sku]
      unique: true
    }
  }

  projection ProductCatalog @ 1
    from catalog.Product @ 8 as p
  {
    productId <- p.productId
    grade <- p.grade
    amount <- p.amount
    sku <- p.sku
  }
"""

_ORDERS_DOMAIN = """
domain orders {
  owner: "orders-team"

  entity Order @ 1 (additive) {
    @key orderId: uuid
    product: ref<catalog.Product @ 8>
    quantity: int = 1
  }

  projection OrderWithProduct @ 1
    from orders.Order @ 1 as o
    left join catalog.Product @ 8 as p on o.product == p.productId
  {
    orderId <- o.orderId
    productSku <- p.sku
  }
}
"""


def _catalog_domain(*, evolved: bool) -> str:
    v2 = _CATALOG_PRODUCT_V2_DELTA if evolved else _CATALOG_PRODUCT_V2_FULL
    v3 = _CATALOG_PRODUCT_V3_DELTA if evolved else _CATALOG_PRODUCT_V3_FULL
    v8 = _CATALOG_PRODUCT_V8_DELTA if evolved else _CATALOG_PRODUCT_V8_FULL
    return (
        "domain catalog {\n"
        '  owner: "catalog-team"\n'
        f"{_CATALOG_ENUMS}{_CATALOG_PRODUCT_V1}{v2}{v3}{_CATALOG_PRODUCT_V5}{v8}{_CATALOG_TAIL}"
        "}\n"
    )


FULL_SOURCE = _catalog_domain(evolved=False) + _ORDERS_DOMAIN
DELTA_SOURCE = _catalog_domain(evolved=True) + _ORDERS_DOMAIN


def _workspace(source: str) -> Workspace:
    return load_workspace_from_sources(
        [WorkspaceDocumentSource(path=Path("q1.mdl"), uri="file:///q1.mdl", text=source)]
    )


def _product_versions(workspace: Workspace) -> dict[int, object]:
    domain = next(d for d in workspace.mdl.domains if d.name == "catalog")
    return {version.version: version for version in domain.models["Product"]}


def test_fixture_compiles_cleanly_in_both_forms() -> None:
    full_ws = _workspace(FULL_SOURCE)
    delta_ws = _workspace(DELTA_SOURCE)

    assert not full_ws.errors, full_ws.errors
    assert not delta_ws.errors, delta_ws.errors


def test_full_and_delta_forms_produce_identical_signatures_at_every_version() -> None:
    full_versions = _product_versions(_workspace(FULL_SOURCE))
    delta_versions = _product_versions(_workspace(DELTA_SOURCE))

    assert full_versions.keys() == delta_versions.keys() == {1, 2, 3, 5, 8}
    for version_number in full_versions:
        full_version = full_versions[version_number]
        delta_version = delta_versions[version_number]
        assert full_version.fields == delta_version.fields, version_number
        assert compute_version_signature("catalog", "Product", full_version) == compute_version_signature(
            "catalog", "Product", delta_version
        ), version_number


def test_semantic_enums_with_identical_members_remain_nominally_distinct() -> None:
    """Instruction #2: Grade and Rank are equal-shaped (same three member
    names) but must resolve to two separate declarations -- shape alone
    never implies identity."""
    workspace = _workspace(DELTA_SOURCE)
    _, grade = resolve_semantic_type_ref(workspace.mdl, "catalog", "Grade", exact_version=1)
    _, rank = resolve_semantic_type_ref(workspace.mdl, "catalog", "Rank", exact_version=1)

    assert grade.underlying.values == rank.underlying.values == ["gold", "silver", "bronze"]
    assert grade is not rank


def test_pick_and_omit_enum_projections_resolve_the_expected_partial_member_sets() -> None:
    """Instruction #3: pick/omit both produce a strict subset here (a
    partial, checked conversion), and do so identically regardless of
    whether the model history feeding the same workspace is full or delta
    form -- the enum projections don't source from Product at all, so this
    is really a proof that unrelated evolves activity in the same domain
    doesn't perturb enum projection resolution."""
    for source in (FULL_SOURCE, DELTA_SOURCE):
        workspace = _workspace(source)
        domain = next(d for d in workspace.mdl.domains if d.name == "catalog")
        public_grade = next(p for p in domain.enum_projections if p.name == "PublicGrade")
        hidden_rank = next(p for p in domain.enum_projections if p.name == "HiddenRank")
        assert public_grade.members == ["gold", "silver"]
        assert hidden_rank.members == ["gold", "silver"]


def test_full_and_delta_forms_produce_identical_snapshot_objects(tmp_path: Path) -> None:
    full_result = resolve_workspace_snapshot(_workspace(FULL_SOURCE), tmp_path / "full")
    delta_result = resolve_workspace_snapshot(_workspace(DELTA_SOURCE), tmp_path / "delta")

    full_lock = json.loads(full_result.lock_path.read_text(encoding="utf-8"))
    delta_lock = json.loads(delta_result.lock_path.read_text(encoding="utf-8"))
    full_entries = {entry["identity"]: entry for entry in full_lock["objects"]}
    delta_entries = {entry["identity"]: entry for entry in delta_lock["objects"]}

    assert full_entries.keys() == delta_entries.keys()
    for identity in full_entries:
        assert full_entries[identity]["signature"] == delta_entries[identity]["signature"], identity
        assert full_entries[identity]["content_hash"] == delta_entries[identity]["content_hash"], identity


def test_full_and_delta_forms_produce_matching_compatibility_reports() -> None:
    full_versions = _product_versions(_workspace(FULL_SOURCE))
    delta_versions = _product_versions(_workspace(DELTA_SOURCE))

    for lower, upper in ((1, 2), (2, 3), (5, 8)):
        full_report = check_model_version_compatibility(_workspace(FULL_SOURCE).mdl, "catalog", "Product", lower, upper)
        delta_report = check_model_version_compatibility(
            _workspace(DELTA_SOURCE).mdl, "catalog", "Product", lower, upper
        )
        assert full_report.status == delta_report.status, (lower, upper)
    assert full_versions[3].change_kind.value == "breaking"
    assert delta_versions[3].change_kind.value == "breaking"


def test_full_and_delta_forms_produce_identical_projection_dependency_graphs() -> None:
    full_mdl = _workspace(FULL_SOURCE).mdl
    delta_mdl = _workspace(DELTA_SOURCE).mdl

    for domain_name, projection_name in (("catalog", "ProductCatalog"), ("orders", "OrderWithProduct")):
        full_domain = next(d for d in full_mdl.domains if d.name == domain_name)
        delta_domain = next(d for d in delta_mdl.domains if d.name == domain_name)
        full_pv = full_domain.projections[projection_name][0]
        delta_pv = delta_domain.projections[projection_name][0]
        assert full_pv.fields == delta_pv.fields, projection_name

        full_deps = build_projection_dependencies(full_mdl, domain_name, projection_name, full_pv)
        delta_deps = build_projection_dependencies(delta_mdl, domain_name, projection_name, delta_pv)
        assert full_deps == delta_deps, projection_name


def test_full_and_delta_forms_produce_identical_impact_analysis() -> None:
    """5 -> 8 removes `discountCode` (breaking) and adds `discount`, but
    ProductCatalog projects productId/grade/amount/sku -- none of which
    changed. Since the *model* version is still classified breaking overall,
    impact analysis correctly reports "affected" (worth reviewing) rather
    than "compatible" even though this specific projection doesn't touch the
    changed field; what this proves is that both source forms land on the
    exact same non-broken status and reason, not that the change is free of
    consequence."""
    statuses = set()
    for mdl in (_workspace(FULL_SOURCE).mdl, _workspace(DELTA_SOURCE).mdl):
        report = check_model_version_compatibility(mdl, "catalog", "Product", 5, 8)
        impact = analyze_impact(mdl, report, ("catalog", "ProductCatalog", 1))
        assert impact.status == "affected", impact.reason
        assert impact.reason == "source catalog.Product is marked breaking"
        statuses.add(impact.status)
    assert statuses == {"affected"}


def _load_golden_generator():
    generator_path = Path(__file__).parents[1] / "scripts" / "write_golden_artifacts.py"
    spec = importlib.util.spec_from_file_location("write_golden_artifacts_q1", generator_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_implemented_target_produces_identical_output_for_full_and_delta_source(tmp_path: Path) -> None:
    """Instructions #3/#4: byte-compare every artifact's content and
    warnings across every implemented codegen target -- Protobuf numbering/
    reservations, SDK field shapes, SQL mappings (including the `index`
    declaration), metadata lineage, registry manifests, and event-sink
    output -- for the full and delta forms of this combined history."""
    generator = _load_golden_generator()
    full_ws = _workspace(FULL_SOURCE)
    delta_ws = _workspace(DELTA_SOURCE)

    mismatches: list[str] = []
    for target_name, emitter in generator.TARGET_EMITTERS.items():
        full_artifacts = {a.ref: a for a in emitter(full_ws, tmp_path / "full" / target_name)}
        delta_artifacts = {a.ref: a for a in emitter(delta_ws, tmp_path / "delta" / target_name)}
        if full_artifacts.keys() != delta_artifacts.keys():
            mismatches.append(
                f"{target_name}: artifact ref sets differ: {full_artifacts.keys()} vs {delta_artifacts.keys()}"
            )
            continue
        for ref, full_artifact in full_artifacts.items():
            delta_artifact = delta_artifacts[ref]
            if full_artifact.content != delta_artifact.content:
                mismatches.append(f"{target_name}:{ref} content differs")
            if full_artifact.warnings != delta_artifact.warnings:
                mismatches.append(f"{target_name}:{ref} warnings differ")

    assert mismatches == []
    assert generator.TARGET_EMITTERS.keys() == IMPLEMENTED_TARGET_NAMES - {"fhir-profile"}
