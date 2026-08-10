# Multi-Package Code Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `modelable compile` able to split generated output into multiple independently-buildable packages (e.g., splitting the Marketplace sample into 7 crates for Scalable), with correct per-package `Cargo.toml`, `lib.rs`, and `use crate::`/`use other_pkg::` import paths. Backward-compatible: no `package {}` config → current flat behavior.

**Architecture:** New `package {}` block in `workspace.mdl` that maps domains to named output packages. Each target emitter translates "package" into its language's packaging: Rust gets `Cargo.toml` + `lib.rs`, TypeScript would get `package.json`, Protobuf would get organized `.proto` directories. A new `package_graph.py` module computes inter-package dependency edges from NamedType references. The Rust emitter gains a multi-package output mode with correct cross-package imports and per-package manifests. The CLI gets a `--package` flag for scoping generation to one package.

**Tech Stack:** Python 3.14, Pydantic v2 IR models, Lark grammar, pytest.

**Spec:** Issue [#314](https://github.com/anomalyco/Modellable/issues/314) — the issue body serves as the design specification.

## Global Constraints

- Do not modify the single-crate output path when no `package {}` blocks are defined — backward compatibility is mandatory.
- All 14 emitter targets have per-domain `_package_name(domain)` helpers that derive a target-language module name from the domain name. The multi-package mode introduces explicit user-defined package names; existing per-domain derivations remain as defaults for single-crate mode. In multi-package mode the user's `package {}` name replaces the derived name at the top level, but per-domain sub-module naming still uses the existing helpers.
- Cross-target package deps are out of scope — packages are per-target, not shared across Rust/TypeScript/Protobuf.
- Published version dependencies are out of scope — path deps only for now.
- Non-Rust package manifests are deferred to follow-up plans.
- Every new/changed file must pass `uv run ruff format --check .`, `uv run ruff check .`, and the mypy baseline ratchet before its task's commit.
- Branch: work happens on a feature branch created from `main` at the current commit. Do not commit directly to `main`.

---

### Task 1: Grammar + Parser + IR

**Files:**
- Modify: `cli/src/modelable/grammar/modelable.lark`
- Modify: `cli/src/modelable/parser/ir.py`
- Modify: `cli/src/modelable/parser/transformer.py`
- Modify: `cli/src/modelable/compiler/workspace.py`
- Test: `cli/tests/test_package_parsing.py` (new)

**Interfaces:**
- Produces: `PackageConfig` dataclass in `ir.py` (fields: `name: str`, `include: list[str]`, `description: str | None = None`); `packages: list[PackageConfig]` field on `WorkspaceDef`; `workspace.py::_validate_package_config(workspace: WorkspaceDef) -> None` — called during workspace loading.

- [ ] **Step 1: Write the failing tests**

Create `cli/tests/test_package_parsing.py`:

```python
from modelable.parser.parse import parse_text_to_ir
from modelable.parser.ir import PackageConfig


SINGLE_PACKAGE = """
workspace "test-workspace" {
  package "my-package" {
    include: ["dom1", "dom2"]
  }
}
"""


def test_parses_single_package_block():
    mdl = parse_text_to_ir(SINGLE_PACKAGE)
    assert mdl.workspace is not None
    assert len(mdl.workspace.packages) == 1
    pkg = mdl.workspace.packages[0]
    assert pkg.name == "my-package"
    assert pkg.include == ["dom1", "dom2"]


MULTI_PACKAGE = """
workspace "test-workspace" {
  package "pkg-a" {
    include: ["dom1"]
  }
  package "pkg-b" {
    include: ["dom2"]
    description: "Package B"
  }
}
"""


def test_parses_multiple_package_blocks():
    mdl = parse_text_to_ir(MULTI_PACKAGE)
    assert mdl.workspace is not None
    assert len(mdl.workspace.packages) == 2
    assert mdl.workspace.packages[0].name == "pkg-a"
    assert mdl.workspace.packages[1].name == "pkg-b"
    assert mdl.workspace.packages[1].description == "Package B"


EMPTY_INCLUDE = """
workspace "test-workspace" {
  package "empty-pkg" {
    include: []
  }
}
"""


def test_empty_include_list():
    mdl = parse_text_to_ir(EMPTY_INCLUDE)
    assert mdl.workspace is not None
    assert mdl.workspace.packages[0].include == []


NO_PACKAGES = """
workspace "test-workspace" {
  name: "test"
}
"""


def test_no_packages_is_valid():
    mdl = parse_text_to_ir(NO_PACKAGES)
    assert mdl.workspace is not None
    assert mdl.workspace.packages == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cli && uv run pytest tests/test_package_parsing.py -v`
Expected: FAIL with parse errors or `PackageConfig` not found

- [ ] **Step 3: Write the implementation**

In `cli/src/modelable/grammar/modelable.lark`, add a `package_block` rule. Insert before `workspace_decl` or inside the workspace block item rule:

```
package_block : "package" string "{" package_item* "}"
package_item  : "include" ":" "[" [string ("," string)*] "]"
              | "description" ":" string
```

The workspace block's items need to allow `package_block` as a valid item. Add `package_block` to the alternatives inside `workspace_block_items` or the workspace body rule.

In `cli/src/modelable/parser/ir.py`, add `PackageConfig`:

```python
@dataclass(frozen=True)
class PackageConfig:
    name: str
    include: list[str] = field(default_factory=list)
    description: str | None = None
```

Add a `packages` field to `WorkspaceDef`:

```python
packages: list[PackageConfig] = field(default_factory=list)
```

In `cli/src/modelable/parser/transformer.py`, add a `package_block` handler:

```python
@v_args(inline=True)
def package_block(self, name: Token, *items) -> PackageConfig:
    include: list[str] = []
    description: str | None = None
    for item in items:
        if isinstance(item, list):
            include = item
        elif isinstance(item, str):
            description = item
    return PackageConfig(name=str(name), include=include, description=description)
```

Update the `workspace_decl` handler to collect `PackageConfig` items from the workspace body (Lark returns mixed items from the workspace block; filter out `PackageConfig` instances and collect them into `WorkspaceDef.packages`).

In `cli/src/modelable/compiler/workspace.py`, add a validation function:

```python
def _validate_package_config(workspace: WorkspaceDef) -> None:
    """Validate package configuration rules."""
    if not workspace.packages:
        return
    all_domains: set[str] = set()
    for pkg in workspace.packages:
        for domain in pkg.include:
            if domain in all_domains:
                raise ValueError(f"domain '{domain}' assigned to multiple packages")
            all_domains.add(domain)
    # No cycle detection here — that happens in package_graph.py (Task 2)
    # because it needs inter-package edges computed from NamedType refs,
    # not just the include declarations.
```

Call `_validate_package_config` during `load_workspace_from_sources` or `validate_workspace`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cli && uv run pytest tests/test_package_parsing.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `cd cli && uv run pytest -q`
Expected: all previously-passing tests still pass

- [ ] **Step 6: Commit**

```bash
git add cli/src/modelable/grammar/modelable.lark cli/src/modelable/parser/ir.py cli/src/modelable/parser/transformer.py cli/src/modelable/compiler/workspace.py cli/tests/test_package_parsing.py
git commit -m "feat: add package {} grammar, IR, transformer, and workspace validation"
```

---

### Task 2: Package Dependency Resolution

**Files:**
- Create: `cli/src/modelable/emitters/package_graph.py`
- Test: `cli/tests/test_package_graph.py` (new)

**Interfaces:**
- Produces: `PackageGraph` dataclass (maps package names to dependency package names + external crate deps); `build_package_graph(mdl: MdlFile) -> PackageGraph` — used by Task 3.

- [ ] **Step 1: Write the failing tests**

Create `cli/tests/test_package_graph.py`:

```python
from modelable.parser.ir import MdlFile, PackageConfig
from modelable.emitters.package_graph import PackageGraph, build_package_graph
```

Tests needed:
- `test_no_packages_returns_empty_graph` — no `package {}` blocks
- `test_single_package_no_deps` — one package, one domain, no cross-domain refs
- `test_two_packages_with_dependency` — package A has a domain that refs a type in package B's domain
- `test_cross_package_enum_ref` — enum type in package B used by domain in package A
- `test_cycle_detection` — A→B→A reference cycle raises `ValueError`
- `test_transitive_dependency` — A→B→C resolved transitively

Each test creates an `MdlFile` with synthetic `DomainDef`/`NamedType`/`ProjectionVersion` objects (or uses `parse_text_to_ir` with carefully crafted `.mdl` text). The `PackageConfig` objects go on `MdlFile.workspace.packages`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cli && uv run pytest tests/test_package_graph.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

Create `cli/src/modelable/emitters/package_graph.py`:

```python
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from modelable.parser.ir import MdlFile


_RUST_EXTERNAL_CRATES: dict[str, str] = {
    "uuid": "1",
    "serde": "1",
    "chrono": "0.4",
    "ordered-float": "4",
}


@dataclass(frozen=True)
class PackageGraph:
    edges: dict[str, set[str]] = field(default_factory=dict)
    external_crates: dict[str, set[str]] = field(default_factory=dict)
    package_for_domain: dict[str, str] = field(default_factory=dict)


def build_package_graph(mdl: MdlFile) -> PackageGraph:
    if not mdl.workspace or not mdl.workspace.packages:
        return PackageGraph()

    package_for_domain: dict[str, str] = {}
    for pkg in mdl.workspace.packages:
        for domain_name in pkg.include:
            package_for_domain[domain_name] = pkg.name

    domain_by_name = {d.name: d for d in mdl.domains}
    deps: dict[str, set[str]] = {pkg.name: set() for pkg in mdl.workspace.packages}

    for pkg in mdl.workspace.packages:
        for domain_name in pkg.include:
            domain = domain_by_name.get(domain_name)
            if domain is None:
                continue
            _collect_domain_refs(domain, package_for_domain, domain_by_name, deps[pkg.name])

    _detect_cycles(deps, [pkg.name for pkg in mdl.workspace.packages])

    external_crates: dict[str, set[str]] = defaultdict(set)
    for pkg_name in deps:
        external_crates[pkg_name] = set(_RUST_EXTERNAL_CRATES.keys())

    return PackageGraph(
        edges={k: v for k, v in deps.items()},
        external_crates=dict(external_crates),
        package_for_domain=package_for_domain,
    )


def _collect_domain_refs(domain, package_for_domain, domain_by_name, into):
    for versions in domain.models.values():
        for version in versions:
            for field in version.fields:
                _check_field_type_for_domain_ref(field.type, domain.name, package_for_domain, into)

    for versions in domain.projections.values():
        for proj in versions:
            for join in proj.joins:
                join_domain = join.source.split(".")[0] if "." in join.source else domain.name
                _add_dep(join_domain, domain.name, package_for_domain, into)


def _check_field_type_for_domain_ref(field_type, current_domain, package_for_domain, into):
    if field_type is None:
        return
    if field_type.kind in ("entity_ref", "enum_ref"):
        ref_domain = field_type.domain or current_domain
        _add_dep(ref_domain, current_domain, package_for_domain, into)
    elif field_type.kind == "array" and field_type.items:
        _check_field_type_for_domain_ref(field_type.items, current_domain, package_for_domain, into)
    elif field_type.kind == "map" and field_type.value_type:
        _check_field_type_for_domain_ref(field_type.value_type, current_domain, package_for_domain, into)


def _add_dep(ref_domain, current_domain, package_for_domain, into):
    if ref_domain == current_domain:
        return
    ref_pkg = package_for_domain.get(ref_domain)
    current_pkg = package_for_domain.get(current_domain)
    if ref_pkg is not None and current_pkg is not None and ref_pkg != current_pkg:
        into.add(ref_pkg)


def _detect_cycles(deps, nodes):
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in nodes}

    def dfs(node):
        color[node] = GRAY
        for neighbor in deps.get(node, set()):
            if neighbor not in color:
                continue
            if color[neighbor] == GRAY:
                raise ValueError(f"package dependency cycle detected: {node} -> {neighbor}")
            if color[neighbor] == WHITE:
                dfs(neighbor)
        color[node] = BLACK

    for node in nodes:
        if color[node] == WHITE:
            dfs(node)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cli && uv run pytest tests/test_package_graph.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `cd cli && uv run pytest -q`
Expected: all previously-passing tests still pass

- [ ] **Step 6: Commit**

```bash
git add cli/src/modelable/emitters/package_graph.py cli/tests/test_package_graph.py
git commit -m "feat: add package dependency graph with cycle detection"
```

---

### Task 3: Rust Emitter — Multi-Package Mode

**Files:**
- Modify: `cli/src/modelable/emitters/rust.py`
- Test: `cli/tests/test_emit_rust.py` (new multi-package tests)

**Interfaces:**
- Consumes: `PackageGraph` from Task 2, `PackageConfig` from Task 1.
- Produces: Multi-package output layout when packages are configured.

- [ ] **Step 1: Write the failing tests**

Append to `cli/tests/test_emit_rust.py` (or create the file if it doesn't exist):

Multi-package tests needed:
- `test_multi_package_output_layout` — files go under `out_dir/{pkg}/src/{domain}/` instead of `out_dir/{domain}/`
- `test_multi_package_generates_cargo_toml` — each package gets a `Cargo.toml`
- `test_multi_package_generates_lib_rs` — each package gets a `src/lib.rs` with `mod` decls
- `test_same_package_imports_use_crate` — intra-package refs use `use crate::domain::Type`
- `test_cross_package_imports_use_package_name` — cross-package refs use `use other_pkg::Type`
- `test_no_packages_backward_compat` — no `package {}` blocks → current flat output
- `test_multi_package_from_impls` — cross-domain `From` impls generated with correct package paths

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cli && uv run pytest tests/test_emit_rust.py -v`
Expected: FAIL — multi-package tests fail because emit_rust has no package support

- [ ] **Step 3: Write the implementation**

Modify `cli/src/modelable/emitters/rust.py`:

1. Add a new `_emit_rust_packages()` function that takes the Workspace and PackageGraph, groups domains by package, and for each package:
   - Creates `out_dir/{pkg}/src/` directory structure
   - Calls existing per-domain emit functions with modified import paths
   - Generates `Cargo.toml` with path deps to other packages
   - Generates `src/lib.rs` with `mod` declarations for each domain
   - Generates per-domain `mod.rs` files

2. Add `_generate_cargo_toml(pkg_name, pkg_deps, external_crates) -> str`:
   ```toml
   [package]
   name = "{pkg_name}"
   version = "0.1.0"
   edition = "2021"

   [dependencies]
   serde = {{ version = "1", features = ["derive"] }}
   uuid = {{ version = "1", features = ["v4", "serde"] }}

   {pkg_name_underscored} = {{ path = "../{pkg_name}" }}
   ```

3. Add `_generate_lib_rs(domains_in_pkg) -> str` that emits `pub mod domain_name;`.

4. Modify existing `emit_rust()` to branch: if `PackageGraph` has packages, delegate to `_emit_rust_packages()`, otherwise use the existing single-crate path.

5. Modify import generation: existing helpers that produce `use super::module::Type;` need a new parameter for the package graph. When a cross-package ref is detected, produce `use other_pkg::module::Type;` instead. When same-package, produce `use crate::domain::module::Type;`.

6. Modify `From` impl generation to emit cross-domain impls with correct package-qualified paths.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cli && uv run pytest tests/test_emit_rust.py -v`
Expected: PASS (all tests, including existing single-crate tests)

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `cd cli && uv run pytest -q`
Expected: all previously-passing tests still pass

- [ ] **Step 6: Commit**

```bash
git add cli/src/modelable/emitters/rust.py cli/tests/test_emit_rust.py
git commit -m "feat: multi-package Rust emitter with Cargo.toml, lib.rs, and correct imports"
```

---

### Task 4: CLI Integration

**Files:**
- Modify: `cli/src/modelable/commands/compile.py`
- Modify: `cli/src/modelable/operations/compilation.py`
- Test: `cli/tests/test_cli.py`

**Interfaces:**
- Produces: `--package NAME` option on the `compile` command; package-aware dispatch in the compilation pipeline.

- [ ] **Step 1: Write the failing tests**

Append to `cli/tests/test_cli.py`:

```python
def test_compile_with_package_flag(tmp_path):
    # Create a workspace.mdl with package blocks
    # Run `modelable compile --target rust --package catalogue-types --out out_dir`
    # Assert only the specified package's files are emitted
    pass
```

- `test_compile_package_flag_filters_output` — only artifacts for `--package NAME` are emitted
- `test_compile_without_package_still_works` — no `package {}` blocks, no `--package` flag → existing behavior
- `test_compile_package_flag_errors_on_missing_package` — `--package nonexistent` raises clear error
- `test_compile_auto_enables_multi_package` — when `package {}` blocks exist and no `--package` is given, multi-package mode auto-enables

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cli && uv run pytest tests/test_cli.py -k compile_package -v`
Expected: FAIL — `--package` option doesn't exist

- [ ] **Step 3: Write the implementation**

In `cli/src/modelable/commands/compile.py`:
- Add `--package` click option (single value, repeatable)
- Pass the package filter through to the compilation operation

In `cli/src/modelable/operations/compilation.py`:
- Add a `package_filter: str | None` parameter
- When set, only generate artifacts for domains that belong to that package
- When packages are defined in workspace but no filter is set, generate all packages (multi-package mode)
- When no packages are defined, use existing single-crate mode regardless

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cli && uv run pytest tests/test_cli.py -k compile_package -v`
Expected: PASS

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `cd cli && uv run pytest -q`
Expected: all previously-passing tests still pass

- [ ] **Step 6: Commit**

```bash
git add cli/src/modelable/commands/compile.py cli/src/modelable/operations/compilation.py cli/tests/test_cli.py
git commit -m "feat: add --package flag to modelable compile for scoped generation"
```

---

### Task 5: Full Regression Sweep

**Files:**
- Modify: `cli/mypy-baseline.txt` (only if line-number shifts or new pre-existing-pattern errors appear)

- [ ] **Step 1: Run all checks**

From the `cli/` directory:

```bash
uv run ruff format --check .
uv run ruff check .
rm -rf .mypy_cache
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short -q
```

Expected: ruff format clean, ruff check clean, mypy baseline ratchet passes, pytest passes with increased test count. If mypy reports new errors, reconcile line-number shifts vs. genuinely new errors using the approach described in `AGENTS.md`.

- [ ] **Step 2: Commit any baseline adjustments**

```bash
git add cli/mypy-baseline.txt
git commit -m "chore: update mypy baseline for multi-package codegen changes"
```

---

## Self-Review Notes

- **Backward compatibility:** The plan preserves the existing single-crate output path when no `package {}` blocks are defined — existing users see zero behavior change.
- **Grammar isolation:** The `package_block` rule is syntactically valid only inside a `workspace` block, so existing `.mdl` files without workspaces are unaffected.
- **Validation ordering:** Domain-to-package uniqueness is validated in `workspace.py` (Task 1), while dependency cycle detection lives in `package_graph.py` (Task 2) because it requires the full dependency analysis.
- **Rust emitter scope:** Only the Rust target gets multi-package support in this slice. Other targets retain their existing per-domain behavior. Their multi-package support is deferred to follow-up plans.
- **Test coverage:** Each task's test file exercises both the new feature path and the backward-compatible path, ensuring no regression.
