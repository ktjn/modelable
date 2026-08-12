# Shared Property-Dependency Graph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the compiler's duplicated, incomplete source-property analysis with one compiler-owned dependency graph, and move compatibility impact analysis and the "who depends on this" lookup onto it.

**Architecture:** A new module `cli/src/modelable/dependency_graph.py` owns two functions: `resolve_projection_aliases` (the one canonical alias→resolved-source map, replacing five duplicated copies of the same walk) and `build_projection_dependencies` (walks direct mappings, computed expressions, join predicates, `where`, and `group by` — using the existing CEL extractor `extract_field_refs`, never re-parsing CEL independently). `compat/checker.py`'s `analyze_impact` and `find_projection_dependents` are rewired onto this graph and onto the existing canonical resolver (`registry/resolver.py`), fixing two real bugs along the way: computed/join/filter/group-by dependencies were invisible to compatibility impact analysis, and range/min/pinned-versioned sources were silently excluded from dependent lookup. `governance/checker.py`'s own duplicated alias-resolution helper is replaced with a call into the shared graph module, with no behavior change (verified by the existing governance test suite staying green).

**Tech Stack:** Python 3.14, pytest (via `uv run pytest`), existing `modelable.expressions.cel` CEL parser, existing `modelable.registry.resolver` canonical version resolver.

## Global Constraints

- This is Slice A2 of `docs/correction-and-capability-plan.md`. Full purpose/scope/acceptance-criteria text lives there under "Slice A2 — create one property-dependency graph"; this plan implements it.
- Version resolution must use the existing canonical resolver (`modelable.registry.resolver.resolve_model_ref`) — never re-derive version-matching logic.
- No subsystem may independently parse CEL merely to rediscover lineage — dependency extraction always goes through `modelable.expressions.cel.parse_cel` + `extract_field_refs`.
- Lineage reports (`planner/lineage.py`), graph export (`graph/export.py`), and the LSP/Playground "dependents" consumers are **out of scope for this plan** — they are real remaining duplicates (documented in the research below) but consolidating them is deferred to a follow-up slice so this change stays reviewable. Do not touch those files.
- Every new/changed function needs a test that fails before the implementation and passes after (TDD, per `superpowers:test-driven-development`).
- Run `uv run ruff format --check <files>`, `uv run ruff check <files>`, and the mypy baseline ratchet (`uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes`, run from `cli/`) before each commit, per this repo's CI convention.
- All commands below assume the current working directory is `cli/` inside the repo checkout.

---

### Task 1: Build the shared dependency graph module

**Files:**
- Create: `cli/src/modelable/dependency_graph.py`
- Test: `cli/tests/test_dependency_graph.py`

**Interfaces:**
- Consumes: `modelable.parser.ir.{MdlFile, ProjectionVersion, DirectMapping, ComputedMapping, VersionPinned}`, `modelable.parser.parse.parse_text_to_ir`, `modelable.expressions.cel.{parse_cel, extract_field_refs}`, `modelable.registry.resolver.{resolve_model_ref, ResolvedModelRef}`, `modelable.registry.signature.compute_version_signature`.
- Produces (used by Tasks 2-4):
  - `PropertyDependency` — frozen dataclass with fields `consumer_ref: str`, `target_property: str | None`, `usage_kind: Literal["direct", "computed", "join", "filter", "group"]`, `source_ref: str`, `source_property: str`.
  - `resolve_projection_aliases(pv: ProjectionVersion, mdl: MdlFile) -> dict[str, ResolvedModelRef]`
  - `build_projection_dependencies(mdl: MdlFile, domain_name: str, projection_name: str, pv: ProjectionVersion) -> list[PropertyDependency]`

Background: the current codebase has the exact same "walk `pv.source` + `pv.joins`, resolve each alias via `resolve_model_ref`, build `alias -> resolved`" logic duplicated in `governance/checker.py:_build_resolved_sources` (line 258), `planner/lineage.py:_build_alias_map` (line 76), `graph/export.py:_alias_map` (line 350), and inline in `compat/checker.py:analyze_impact` (lines 78-84) and `compiler/workspace.py:_validate_cel`. This task creates the one version everything should eventually call; Tasks 2-4 wire `compat/checker.py` and `governance/checker.py` onto it (lineage/graph-export stay untouched per the Global Constraints above).

The grammar (`cli/src/modelable/grammar/modelable.lark:137-158`) is:
```
source_clause: "from" dotted_ref "@" version_spec "as" IDENT join_clause* where_clause? group_clause?
where_clause: "where" FIELD_EXPRESSION
join_prefix: "join" dotted_ref "@" version_spec "as" IDENT "on" EXPRESSION
group_clause: "group" "by" group_item ("," group_item)*
```
`ProjectionVersion.where` and `group_by` are plain strings/list-of-strings (already trimmed by the transformer) — feed each through `parse_cel` + `extract_field_refs` exactly like `ComputedMapping.expression` already is.

- [ ] **Step 1: Write the failing tests**

Create `cli/tests/test_dependency_graph.py`:

```python
from pathlib import Path

from modelable.dependency_graph import PropertyDependency, build_projection_dependencies
from modelable.parser.ir import (
    DirectMapping,
    ProjectionField,
    ProjectionVersion,
    SourceRef,
    VersionMin,
    VersionPinned,
    VersionRange,
)
from modelable.parser.parse import parse_text_to_ir
from modelable.registry.signature import compute_version_signature

FIXTURES = Path(__file__).parent / "fixtures"


def _billing_projection(mdl, name="BillingCustomer"):
    domain = next(d for d in mdl.domains if d.name == "billing")
    return domain.projections[name][0]


def test_direct_mapping_dependency():
    mdl = parse_text_to_ir(
        """
        domain customer {
          owner: "test-team"
          entity Customer @ 1 (additive) {
            @key customerId: uuid
          }
        }
        domain billing {
          owner: "test-team"
          projection BillingCustomer @ 1
            from customer.Customer @ 1 as c
          {
            id <- c.customerId
          }
        }
        """
    )

    deps = build_projection_dependencies(mdl, "billing", "BillingCustomer", _billing_projection(mdl))

    assert deps == [
        PropertyDependency(
            consumer_ref="billing.BillingCustomer@1",
            target_property="id",
            usage_kind="direct",
            source_ref="customer.Customer@1",
            source_property="customerId",
        )
    ]


def test_computed_expression_dependency():
    mdl = parse_text_to_ir(
        """
        domain customer {
          owner: "test-team"
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            status: string
          }
        }
        domain billing {
          owner: "test-team"
          projection BillingCustomer @ 1
            from customer.Customer @ 1 as c
          {
            isBillable = c.status == "active"
          }
        }
        """
    )

    deps = build_projection_dependencies(mdl, "billing", "BillingCustomer", _billing_projection(mdl))

    assert deps == [
        PropertyDependency(
            consumer_ref="billing.BillingCustomer@1",
            target_property="isBillable",
            usage_kind="computed",
            source_ref="customer.Customer@1",
            source_property="status",
        )
    ]


def test_join_predicate_dependency():
    mdl = parse_text_to_ir(
        """
        domain customer {
          owner: "test-team"
          entity Customer @ 1 (additive) {
            @key customerId: uuid
          }
        }
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            customerId: uuid
          }
        }
        domain billing {
          owner: "test-team"
          projection OrderWithCustomer @ 1
            from orders.Order @ 1 as o
            join customer.Customer @ 1 as c on o.customerId == c.customerId
          {
            orderId <- o.orderId
          }
        }
        """
    )

    deps = build_projection_dependencies(mdl, "billing", "OrderWithCustomer", _billing_projection(mdl, "OrderWithCustomer"))
    join_deps = [dep for dep in deps if dep.usage_kind == "join"]

    assert join_deps == [
        PropertyDependency(
            consumer_ref="billing.OrderWithCustomer@1",
            target_property=None,
            usage_kind="join",
            source_ref="orders.Order@1",
            source_property="customerId",
        ),
        PropertyDependency(
            consumer_ref="billing.OrderWithCustomer@1",
            target_property=None,
            usage_kind="join",
            source_ref="customer.Customer@1",
            source_property="customerId",
        ),
    ]


def test_where_filter_dependency():
    mdl = parse_text_to_ir(
        """
        domain customer {
          owner: "test-team"
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            status: string
          }
        }
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            customerId: uuid
          }
        }
        domain billing {
          owner: "test-team"
          projection BillingCustomer @ 1
            from customer.Customer @ 1 as c
            left join orders.Order @ 1 as o on c.customerId == o.customerId
            where c.status == "active"
          {
            billingCustomerId <- c.customerId
          }
        }
        """
    )

    deps = build_projection_dependencies(mdl, "billing", "BillingCustomer", _billing_projection(mdl))
    filter_deps = [dep for dep in deps if dep.usage_kind == "filter"]

    assert filter_deps == [
        PropertyDependency(
            consumer_ref="billing.BillingCustomer@1",
            target_property=None,
            usage_kind="filter",
            source_ref="customer.Customer@1",
            source_property="status",
        )
    ]


def test_group_by_dependency():
    mdl = parse_text_to_ir(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            customerId: uuid
            totalAmount: decimal(10, 2)
          }
        }
        domain billing {
          owner: "test-team"
          projection CustomerOrderStats @ 1
            from orders.Order @ 1 as o
            group by o.customerId
          {
            customerId <- o.customerId
            totalSpent = sum(o.totalAmount)
          }
        }
        """
    )

    deps = build_projection_dependencies(mdl, "billing", "CustomerOrderStats", _billing_projection(mdl, "CustomerOrderStats"))
    group_deps = [dep for dep in deps if dep.usage_kind == "group"]

    assert group_deps == [
        PropertyDependency(
            consumer_ref="billing.CustomerOrderStats@1",
            target_property=None,
            usage_kind="group",
            source_ref="orders.Order@1",
            source_property="customerId",
        )
    ]


def test_range_source_resolves_to_highest_satisfying_version():
    mdl = parse_text_to_ir(
        """
        domain customer {
          owner: "test-team"
          entity Customer @ 1 (additive) { @key customerId: uuid }
          entity Customer @ 2 (additive) { @key customerId: uuid }
        }
        """
    )
    pv = ProjectionVersion(
        version=1,
        source=SourceRef(model="customer.Customer", version=VersionRange(min_inclusive=1, max_exclusive=3), alias="c"),
        fields=[ProjectionField(name="id", mapping=DirectMapping(source_alias="c", source_field="customerId"))],
    )

    deps = build_projection_dependencies(mdl, "billing", "BillingCustomer", pv)

    assert deps[0].source_ref == "customer.Customer@2"


def test_minimum_version_source_resolves_to_highest_available_version():
    mdl = parse_text_to_ir(
        """
        domain customer {
          owner: "test-team"
          entity Customer @ 1 (additive) { @key customerId: uuid }
          entity Customer @ 2 (additive) { @key customerId: uuid }
        }
        """
    )
    pv = ProjectionVersion(
        version=1,
        source=SourceRef(model="customer.Customer", version=VersionMin(min_inclusive=1), alias="c"),
        fields=[ProjectionField(name="id", mapping=DirectMapping(source_alias="c", source_field="customerId"))],
    )

    deps = build_projection_dependencies(mdl, "billing", "BillingCustomer", pv)

    assert deps[0].source_ref == "customer.Customer@2"


def test_pinned_source_resolves_when_signature_matches():
    mdl = parse_text_to_ir(
        """
        domain customer {
          owner: "test-team"
          entity Customer @ 1 (additive) { @key customerId: uuid }
        }
        """
    )
    v1 = mdl.domains[0].models["Customer"][0]
    signature = compute_version_signature("customer", "Customer", v1)
    pv = ProjectionVersion(
        version=1,
        source=SourceRef(model="customer.Customer", version=VersionPinned(version=1, content_hash=signature), alias="c"),
        fields=[ProjectionField(name="id", mapping=DirectMapping(source_alias="c", source_field="customerId"))],
    )

    deps = build_projection_dependencies(mdl, "billing", "BillingCustomer", pv)

    assert deps[0].source_ref == "customer.Customer@1"


def test_chained_projection_source_dependency():
    mdl = parse_text_to_ir((FIXTURES / "projection_of_projection.mdl").read_text())
    domain = next(d for d in mdl.domains if d.name == "billing")
    summary = domain.projections["BillingCustomerSummary"][0]

    deps = build_projection_dependencies(mdl, "billing", "BillingCustomerSummary", summary)

    # The chain is billing.BillingCustomerSummary -> billing.BillingCustomer -> customer.Customer.
    # This projection's own dependencies must resolve one hop, to the projection it sources
    # from directly, not flattened through to the root entity.
    assert all(dep.source_ref == "billing.BillingCustomer@1" for dep in deps)


def test_multi_source_property_usage():
    mdl = parse_text_to_ir((FIXTURES / "multi_domain_joins.mdl").read_text())
    domain = next(d for d in mdl.domains if d.name == "analytics")
    pv = domain.projections["CustomerOrderPayment"][0]

    deps = build_projection_dependencies(mdl, "analytics", "CustomerOrderPayment", pv)

    # orderTotal <- o.totalAmount (direct) and isFullyPaid = p.amount == o.totalAmount (computed)
    # both depend on orders.Order@1.totalAmount, via two different usage kinds.
    order_total_deps = [
        dep for dep in deps if dep.source_ref == "orders.Order@1" and dep.source_property == "totalAmount"
    ]
    assert {dep.usage_kind for dep in order_total_deps} == {"direct", "computed"}
    assert {dep.target_property for dep in order_total_deps} == {"orderTotal", "isFullyPaid"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_dependency_graph.py -v`
Expected: every test fails with `ModuleNotFoundError: No module named 'modelable.dependency_graph'`.

- [ ] **Step 3: Write the implementation**

Create `cli/src/modelable/dependency_graph.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from modelable.expressions.cel import extract_field_refs, parse_cel
from modelable.parser.ir import ComputedMapping, DirectMapping, MdlFile, ProjectionVersion
from modelable.registry.resolver import ResolvedModelRef, resolve_model_ref

UsageKind = Literal["direct", "computed", "join", "filter", "group"]


@dataclass(frozen=True)
class PropertyDependency:
    consumer_ref: str
    target_property: str | None
    usage_kind: UsageKind
    source_ref: str
    source_property: str


def resolve_projection_aliases(pv: ProjectionVersion, mdl: MdlFile) -> dict[str, ResolvedModelRef]:
    """Resolve every source/join alias on a projection version to its concrete source.

    This is the one canonical alias-resolution walk; every subsystem that needs
    "what does alias X refer to" for a projection should call this instead of
    re-walking `pv.source`/`pv.joins` itself.
    """
    aliases: dict[str, ResolvedModelRef] = {}
    sources = [(pv.source.model, pv.source.version, pv.source.alias)]
    sources.extend((join.model, join.version, join.alias) for join in pv.joins)

    for model_ref, version_spec, alias in sources:
        try:
            aliases[alias] = resolve_model_ref(mdl, model_ref, version_spec)
        except LookupError:
            continue

    return aliases


def build_projection_dependencies(
    mdl: MdlFile,
    domain_name: str,
    projection_name: str,
    pv: ProjectionVersion,
) -> list[PropertyDependency]:
    """Build the full set of source-property dependencies for one projection version.

    Covers direct mappings, computed expressions, join predicates, `where`
    filters, and `group by` keys — the complete set of positions a projection
    can reference a source property from.
    """
    consumer_ref = f"{domain_name}.{projection_name}@{pv.version}"
    aliases = resolve_projection_aliases(pv, mdl)
    dependencies: list[PropertyDependency] = []

    for field in pv.fields:
        mapping = field.mapping
        if isinstance(mapping, DirectMapping):
            resolved = aliases.get(mapping.source_alias)
            if resolved is not None:
                dependencies.append(
                    PropertyDependency(
                        consumer_ref=consumer_ref,
                        target_property=field.name,
                        usage_kind="direct",
                        source_ref=_source_ref(resolved),
                        source_property=mapping.source_field,
                    )
                )
        elif isinstance(mapping, ComputedMapping):
            dependencies.extend(
                _refs_from_expression(mapping.expression, aliases, consumer_ref, field.name, "computed")
            )

    for join in pv.joins:
        dependencies.extend(_refs_from_expression(join.on, aliases, consumer_ref, None, "join"))

    if pv.where:
        dependencies.extend(_refs_from_expression(pv.where, aliases, consumer_ref, None, "filter"))

    for group_expr in pv.group_by:
        dependencies.extend(_refs_from_expression(group_expr, aliases, consumer_ref, None, "group"))

    return dependencies


def _refs_from_expression(
    expression: str,
    aliases: dict[str, ResolvedModelRef],
    consumer_ref: str,
    target_property: str | None,
    usage_kind: UsageKind,
) -> list[PropertyDependency]:
    expr_ast, errors = parse_cel(expression)
    if expr_ast is None:
        return []

    dependencies: list[PropertyDependency] = []
    for alias, field_name in extract_field_refs(expr_ast):
        resolved = aliases.get(alias)
        if resolved is None:
            continue
        dependencies.append(
            PropertyDependency(
                consumer_ref=consumer_ref,
                target_property=target_property,
                usage_kind=usage_kind,
                source_ref=_source_ref(resolved),
                source_property=field_name,
            )
        )
    return dependencies


def _source_ref(resolved: ResolvedModelRef) -> str:
    return f"{resolved.domain_name}.{resolved.model_name}@{resolved.version.version}"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_dependency_graph.py -v`
Expected: all 10 tests PASS.

- [ ] **Step 5: Lint and type-check**

Run (from `cli/`):
```bash
uv run ruff format --check src/modelable/dependency_graph.py tests/test_dependency_graph.py
uv run ruff check src/modelable/dependency_graph.py tests/test_dependency_graph.py
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
```
Expected: ruff clean; mypy baseline ratchet passes with no new errors.

- [ ] **Step 6: Commit**

```bash
git add src/modelable/dependency_graph.py tests/test_dependency_graph.py
git commit -m "feat(compat): add shared property-dependency graph (Slice A2)"
```

---

### Task 2: Fix `find_projection_dependents` to use the canonical resolver

**Files:**
- Modify: `cli/src/modelable/compat/checker.py:132-147`
- Test: `cli/tests/test_compatibility.py`

**Interfaces:**
- Consumes: `modelable.registry.resolver.find_dependents(mdl, domain_name, model_name, version) -> list[tuple[str, str, int]]` (already exists and already correctly handles range/min/pinned sources via `resolve_model_ref` — see `registry/resolver.py:74-112`).
- Produces: `find_projection_dependents(mdl: MdlFile, ref: str) -> list[tuple[str, str, int]]` keeps its existing public signature (four call sites depend on it: `llm/workspace_query.py:113`, `llm/workspace_editor.py:1288,1298`, `browser/compatibility.py:36` — none of them change).

Background: `find_projection_dependents` currently does its own naive string matching (`compat/checker.py:132-147`) — `getattr(source_version, "version", None) == version` silently returns `None` (never matches) for `VersionRange`/`VersionMin` sources, since those classes have no `.version` attribute. `registry/resolver.py:find_dependents` already does this correctly by calling `resolve_model_ref` per candidate. This task deletes the duplicate and delegates.

- [ ] **Step 1: Write the failing test**

Add to `cli/tests/test_compatibility.py` (near `test_find_projection_dependents_is_public_and_includes_joined_sources`):

```python
def test_find_projection_dependents_includes_range_versioned_source():
    mdl = parse_text_to_ir(
        """
        domain customer {
          owner: "customer-team"
          entity Customer @ 1 (additive) {
            @key customerId: uuid
          }
          entity Customer @ 2 (additive) {
            @key customerId: uuid
          }
        }
        domain billing {
          owner: "billing-team"
          projection BillingCustomer @ 1
            from customer.Customer @ >=1 <3 as c
          {
            id <- c.customerId
          }
        }
        """
    )

    from modelable.compat.checker import find_projection_dependents

    # The range >=1 <3 resolves to version 2 today, so BillingCustomer depends
    # on customer.Customer@2, not @1.
    assert find_projection_dependents(mdl, "customer.Customer@2") == [("billing", "BillingCustomer", 1)]
    assert find_projection_dependents(mdl, "customer.Customer@1") == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_compatibility.py::test_find_projection_dependents_includes_range_versioned_source -v`
Expected: FAIL — `find_projection_dependents(mdl, "customer.Customer@2")` returns `[]` instead of `[("billing", "BillingCustomer", 1)]`, because the current naive matcher never matches a `VersionRange` source.

- [ ] **Step 3: Write the minimal implementation**

In `cli/src/modelable/compat/checker.py`, add the import and replace the function body:

```python
from modelable.registry.resolver import find_dependents
```//add to the existing import block near the top of the file

```python
def find_projection_dependents(mdl: MdlFile, ref: str) -> list[tuple[str, str, int]]:
    """Return projections that resolve to the exact model version in ``ref``."""
    model_ref, version_text = ref.rsplit("@", 1)
    domain_name, model_name = model_ref.split(".", 1)
    version = int(version_text)
    return find_dependents(mdl, domain_name, model_name, version)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_compatibility.py -v`
Expected: all tests in the file PASS, including the new one and the pre-existing `test_find_projection_dependents_is_public_and_includes_joined_sources`.

- [ ] **Step 5: Lint and type-check**

Run (from `cli/`):
```bash
uv run ruff format --check src/modelable/compat/checker.py tests/test_compatibility.py
uv run ruff check src/modelable/compat/checker.py tests/test_compatibility.py
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
```

- [ ] **Step 6: Commit**

```bash
git add src/modelable/compat/checker.py tests/test_compatibility.py
git commit -m "fix(compat): find_projection_dependents now resolves range/min/pinned sources"
```

---

### Task 3: Wire `analyze_impact` onto the shared dependency graph

**Files:**
- Modify: `cli/src/modelable/compat/checker.py:56-129`
- Test: `cli/tests/test_compatibility.py`

**Interfaces:**
- Consumes: `modelable.dependency_graph.build_projection_dependencies` (from Task 1).
- Produces: `analyze_impact` keeps its existing signature and `ProjectionImpact` return shape; only its internal field-matching logic changes. Existing callers (`commands/diff.py:56`, `browser/compatibility.py:38`, `llm/workspace_editor.py:401`) and the existing CLI-level test `tests/test_impact_analysis.py::test_diff_reports_impacted_projections` (which asserts the exact string `"uses field 'email' (removed_field)"`) must keep passing unchanged.

Background: `analyze_impact` currently only scans `DirectMapping` fields (`compat/checker.py:102-109`) to decide whether a breaking source change impacts a dependent projection. A field only referenced through a computed expression, a join predicate, a `where` filter, or a `group by` key is invisible to it — the impact silently degrades to the generic `"affected"` status instead of `"broken"`.

- [ ] **Step 1: Write the failing tests**

Add to `cli/tests/test_compatibility.py`:

```python
def _dependent_impact(mdl_text, from_version, to_version, dependent):
    mdl = parse_text_to_ir(mdl_text)

    from modelable.compat.checker import analyze_impact, check_model_version_compatibility

    report = check_model_version_compatibility(mdl, "customer", "Customer", from_version, to_version)
    return analyze_impact(mdl, report, dependent)


def test_analyze_impact_detects_computed_expression_dependency():
    impact = _dependent_impact(
        """
        domain customer {
          owner: "test-team"
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            status: string
          }
          entity Customer @ 2 (breaking) {
            @key customerId: uuid
          }
        }
        domain billing {
          owner: "test-team"
          projection BillingCustomer @ 1
            from customer.Customer @ 1 as c
          {
            id <- c.customerId
            isBillable = c.status == "active"
          }
        }
        """,
        1,
        2,
        ("billing", "BillingCustomer", 1),
    )

    assert impact.status == "broken"
    assert "field 'status' (removed_field)" in impact.reason


def test_analyze_impact_detects_join_predicate_dependency():
    impact = _dependent_impact(
        """
        domain customer {
          owner: "test-team"
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            legacyId: string
          }
          entity Customer @ 2 (breaking) {
            @key customerId: uuid
          }
        }
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            legacyCustomerId: string
          }
        }
        domain billing {
          owner: "test-team"
          projection OrderWithCustomer @ 1
            from orders.Order @ 1 as o
            join customer.Customer @ 1 as c on o.legacyCustomerId == c.legacyId
          {
            orderId <- o.orderId
          }
        }
        """,
        1,
        2,
        ("billing", "OrderWithCustomer", 1),
    )

    assert impact.status == "broken"
    assert "field 'legacyId' (removed_field)" in impact.reason


def test_analyze_impact_detects_where_filter_dependency():
    impact = _dependent_impact(
        """
        domain customer {
          owner: "test-team"
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            status: string
          }
          entity Customer @ 2 (breaking) {
            @key customerId: uuid
          }
        }
        domain billing {
          owner: "test-team"
          projection BillingCustomer @ 1
            from customer.Customer @ 1 as c
            where c.status == "active"
          {
            id <- c.customerId
          }
        }
        """,
        1,
        2,
        ("billing", "BillingCustomer", 1),
    )

    assert impact.status == "broken"
    assert "field 'status' (removed_field)" in impact.reason


def test_analyze_impact_detects_group_by_dependency():
    impact = _dependent_impact(
        """
        domain customer {
          owner: "test-team"
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            region: string
          }
          entity Customer @ 2 (breaking) {
            @key customerId: uuid
          }
        }
        domain billing {
          owner: "test-team"
          projection CustomersByRegion @ 1
            from customer.Customer @ 1 as c
            group by c.region
          {
            region <- c.region
            customerCount = count(c.customerId)
          }
        }
        """,
        1,
        2,
        ("billing", "CustomersByRegion", 1),
    )

    assert impact.status == "broken"
    assert "field 'region' (removed_field)" in impact.reason
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_compatibility.py -k "test_analyze_impact" -v`
Expected: all 4 new tests FAIL with `impact.status == "affected"` (not `"broken"`) — confirming today's `analyze_impact` misses computed/join/filter/group dependencies.

- [ ] **Step 3: Write the minimal implementation**

In `cli/src/modelable/compat/checker.py`:
1. Add the import: `from modelable.dependency_graph import build_projection_dependencies`
2. Remove the `DirectMapping` import from the top-level import line (no longer used directly in this file) — line 6 becomes:
   ```python
   from modelable.parser.ir import IndexDecl, MdlFile, ModelVersion
   ```
3. Replace lines 77-109 (the `aliases` build and the `impacted_fields` inner-loop) with:

```python
    source_model_ref = f"{report.domain_name}.{report.model_name}"
    dependencies = build_projection_dependencies(mdl, dep_domain_name, dep_proj_name, pv)
    dependency_source_fields = {
        dependency.source_property
        for dependency in dependencies
        if dependency.source_ref.rsplit("@", 1)[0] == source_model_ref
    }

    # Check if any breaking field change affects a property this projection depends on,
    # through any mapping kind (direct, computed, join predicate, filter, or group key).
    impacted_fields = []
    for change in report.changes:
        is_breaking_field = change.kind in {
            "removed_field",
            "renamed_field",
            "type_changed",
            "enum_changed",
            "identity_changed",
        }
        if change.kind == "added_field" and change.to_optional is False:
            is_breaking_field = True

        if not is_breaking_field:
            continue

        if change.field_name in dependency_source_fields:
            impacted_fields.append(f"field '{change.field_name}' ({change.kind})")
```

   Note the `f"uses {', '.join(impacted_fields)}"` return below this block (currently line 117) is unchanged — leave it as-is. The `source_ref` local variable used later at line 126 (`f"source {source_ref} is marked breaking"`) must be renamed to `source_model_ref` there too, since this step renames the variable.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_compatibility.py tests/test_impact_analysis.py -v`
Expected: all tests PASS, including the 4 new ones and the pre-existing `test_impact_analysis.py` CLI-level tests (their exact-string assertions like `"uses field 'email' (removed_field)"` must still match, since the message format is unchanged).

- [ ] **Step 5: Run the full compat-adjacent regression suite**

Run: `uv run pytest tests/test_compatibility.py tests/test_impact_analysis.py tests/test_workspace_editor.py tests/test_browser_compatibility.py -v`
Expected: all PASS. (`workspace_editor.py` and `browser/compatibility.py` both call `analyze_impact`/`find_projection_dependents` — this confirms neither Task 2 nor Task 3 regressed their callers.)

- [ ] **Step 6: Lint and type-check**

Run (from `cli/`):
```bash
uv run ruff format --check src/modelable/compat/checker.py tests/test_compatibility.py
uv run ruff check src/modelable/compat/checker.py tests/test_compatibility.py
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
```

- [ ] **Step 7: Commit**

```bash
git add src/modelable/compat/checker.py tests/test_compatibility.py
git commit -m "fix(compat): analyze_impact now sees computed/join/filter/group dependencies"
```

---

### Task 4: Dedupe governance's alias resolution onto the shared graph

**Files:**
- Modify: `cli/src/modelable/governance/checker.py:258-271`

**Interfaces:**
- Consumes: `modelable.dependency_graph.resolve_projection_aliases` (from Task 1).
- Produces: `_build_resolved_sources` keeps its existing return shape (`dict[str, tuple[str, ModelVersion]]`) and existing callers (`_check_computed_field_access`, `_check_projection_classification`) are untouched — this is a pure internal refactor with no behavior change.

Background: `governance/checker.py:_build_resolved_sources` (line 258-271) does the exact same "walk source+joins, resolve via `resolve_model_ref`, build alias map" work as `resolve_projection_aliases` from Task 1, just returning a differently-shaped dict (`(ref_string, ModelVersion)` tuples instead of `ResolvedModelRef` objects). This task makes it a thin adapter over the shared function instead of a fourth independent copy. No governance *behavior* changes — the existing `tests/test_governance.py` suite is the regression check, run unchanged.

- [ ] **Step 1: Confirm the regression baseline passes before changing anything**

Run: `uv run pytest tests/test_governance.py tests/test_browser_governance.py -v`
Expected: all PASS (this is the existing coverage this refactor must not break — there is no new test to write here since behavior is intentionally unchanged; TDD's red/green cycle for this task is "baseline green before" / "still green after").

- [ ] **Step 2: Replace the implementation**

In `cli/src/modelable/governance/checker.py`:
1. Add the import: `from modelable.dependency_graph import resolve_projection_aliases`
2. Remove `from modelable.registry.resolver import resolve_model_ref` (no longer called directly in this file).
3. Replace the `_build_resolved_sources` function body (lines 258-271):

```python
def _build_resolved_sources(pv: ProjectionVersion, mdl: MdlFile) -> dict[str, tuple[str, ModelVersion]]:
    resolved_sources: dict[str, tuple[str, ModelVersion]] = {}
    for alias, resolved in resolve_projection_aliases(pv, mdl).items():
        ref = f"{resolved.domain_name}.{resolved.model_name}@{resolved.version.version}"
        resolved_sources[alias] = (ref, resolved.version)
    return resolved_sources
```

- [ ] **Step 3: Run the regression suite to verify it is still green**

Run: `uv run pytest tests/test_governance.py tests/test_browser_governance.py -v`
Expected: all PASS, identical results to Step 1.

- [ ] **Step 4: Run the full CLI suite as a final safety net**

Run: `uv run pytest -q`
Expected: all tests PASS (no regressions anywhere else in the codebase from this plan's four tasks combined).

- [ ] **Step 5: Lint and type-check**

Run (from `cli/`):
```bash
uv run ruff format --check src/modelable/governance/checker.py
uv run ruff check src/modelable/governance/checker.py
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
```

- [ ] **Step 6: Commit**

```bash
git add src/modelable/governance/checker.py
git commit -m "refactor(governance): reuse shared dependency-graph alias resolution"
```

---

## Explicitly deferred (not in this plan)

- `planner/lineage.py:_build_alias_map`, `graph/export.py:_alias_map`/`_resolve_direct_mapping_ref`, and `compiler/workspace.py:_validate_cel`'s inline alias build are three more duplicates of the same pattern, and `graph/export.py` never creates a dependency edge for computed fields at all. Consolidating these onto `resolve_projection_aliases`/`build_projection_dependencies` is real follow-up work but is left for a separate slice so this plan stays a reviewable size.
- `llm/engine.py:_classify_attach_change_kind` has its own (already-correct) copy of the optional→required breaking check from Slice A1 — also left alone for the same reason.
- `language/references.py` (LSP go-to-references) is text/regex-based by design for position-based lookups, not a lineage consumer — it should stay as-is.
