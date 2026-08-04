# Semantic-Type Namespace Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `semantic` type name resolution domain-aware and deterministic — a bare name resolves in the declaring domain first, a qualified `domain.Name` reference works everywhere, and a genuinely ambiguous bare reference is a clear error instead of a silent, iteration-order-dependent pick.

**Architecture:** One new canonical resolver, `resolve_semantic_type_ref(mdl, current_domain, name)` in `registry/resolver.py` (alongside the existing `resolve_model_ref`), replaces three independent, inconsistent implementations of the same "find the semantic type named X" lookup: a flat same-name dictionary in `validation/semantic.py` (used for underlying-chain/cycle validation), a first-domain-wins loop in `operations/compilation.py` (used for compile-preview impact analysis), and a first-domain-wins loop in `emitters/rust.py` (used for Rust code generation, with zero ambiguity detection and zero test coverage today). `emitters/protobuf.py` already has its own correct, tested, domain-aware resolution (`_SemanticIndex`) and is deliberately left untouched. A grammar change lets `type_expr` accept a dotted reference (`orders.Id`) anywhere a semantic-type name is written, reusing the `dotted_ref` rule already used by `ref<Domain.Model>` — verified to require no IR/transformer changes, since `dotted_ref` already collapses to a single string for both bare and dotted forms.

**Tech Stack:** Python 3.14, Lark grammar, pytest (`uv run pytest`).

## Global Constraints

- This is Slice A4 of `docs/correction-and-capability-plan.md`. Full purpose/scope/acceptance-criteria text lives there under "Slice A4 — fix semantic-type resolution ambiguity"; this plan implements it.
- **Resolution rules** (from the correction plan, verbatim):
  1. A bare name resolves in the current domain first.
  2. A qualified name such as `orders.Id` resolves across domains.
  3. A bare name may fall back to a workspace-wide match only when exactly one declaration exists.
  4. Ambiguity is a compile error.
- **Explicitly deferred, not in this plan** (document these in the PR description too):
  - `emitters/protobuf.py`'s `_SemanticIndex`/`_unique_semantic_decl` and `operations/compilation.py`'s `_find_domain_scope_violations`/`_semantic_domains_defining` (the `--domain`-scoped Protobuf/gRPC ambiguity check) are **already correct and already tested** (`tests/test_emit_protobuf.py`, `tests/test_emit_grpc.py`). Refactoring them onto the new shared resolver is real follow-up de-duplication work, but touching already-correct, well-tested code isn't needed to fix the actual bug and is left alone to keep this PR reviewable.
  - Hover, completion, definition, and rename support for semantic types (`language/hover.py`, `language/completion.py`, `language/definition.py`, `language/rename.py`) currently have **zero** semantic-type-specific logic at all — not broken, just nonexistent. Building these is a new LSP feature, not a fix to broken resolution behavior; left for a follow-up slice.
  - Import handling (dbt/FHIR/ODCS importers) never creates or references `semantic` declarations — confirmed not applicable, no work needed.
  - Full canonical-signature *text* qualification (making `compiler/render.py` always render a semantic-type field as `domain.Name` instead of bare `Name`) is not attempted. Once ambiguity is a hard compile error (this plan's core fix), any semantic-type reference that survives to reach signature rendering is, by construction, already unambiguous — so there is no live disambiguation need left in signature text, and changing `render.py`'s output format is a separate, higher-risk change (it would touch every existing model's canonical signature hash) that this plan does not need to make.
  - `NamedType` is also used for model/`value`-kind-model references (not just semantic types) and there is currently no general "does every field's `NamedType` resolve to *something*" validation pass at all. This plan does not add one — it only fixes resolution at the specific call sites that already exist and already specifically resolve a name against `domain.semantic_types`.
- Run `uv run ruff format --check <files>`, `uv run ruff check <files>`, and the mypy baseline ratchet (`uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes`, from `cli/`) before each commit.
- All commands below assume the current working directory is `cli/` inside the repo checkout, unless stated otherwise.
- After every task, run `uv run pytest -q` (the full suite, not just the touched files) — Slice A3 caught real regressions in unrelated snapshot/sample tests that no per-file run would have found, and this task's grammar change already turned up one (Task 1 below).

---

### Task 1: Grammar — accept qualified semantic-type references

**Status:** Implemented and verified during planning (see Step 3-5 below for what was actually done and observed) — this task's steps document that work precisely so it can be re-verified/re-applied cleanly.

**Files:**
- Modify: `cli/src/modelable/grammar/modelable.lark:88`
- Modify (regenerated snapshot, not hand-edited): `cli/tests/conformance/browser/snapshots/invalid-parse.json`
- Test: `cli/tests/test_transformer.py`

**Interfaces:**
- Consumes: the existing `dotted_ref: IDENT ("." IDENT)*` rule (`modelable.lark:280`) and its existing transformer (`dotted_ref` → `".".join(...)`, `transformer.py:566-567`).
- Produces: `type_expr` can now parse `orders.Id` the same way it already parses bare `Id` — both become `NamedType(name=...)` via the existing, **unmodified** `type_expr` transformer (`transformer.py:465-469`), since `dotted_ref` already returns a single joined string for both the zero-dot and multi-dot case. No IR shape change.

- [ ] **Step 1: Write the failing test**

Add to `cli/tests/test_transformer.py`:

```python
def test_qualified_semantic_type_reference_parses_as_named_type():
    mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      semantic Id: uuid
    }
    domain billing {
      owner: "test-team"
      entity Invoice @ 1 (additive) {
        @key invoiceId: uuid
        customerId: orders.Id
      }
    }
    """)

    billing = next(d for d in mdl.domains if d.name == "billing")
    field = next(f for f in billing.models["Invoice"][0].fields if f.name == "customerId")
    assert field.type.kind == "named"
    assert field.type.name == "orders.Id"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_transformer.py::test_qualified_semantic_type_reference_parses_as_named_type -v`
Expected: FAIL with a Lark parse error (`orders.Id` isn't valid where a bare `IDENT` type reference is expected — the `.` is unconsumed).

- [ ] **Step 3: Change the grammar**

In `cli/src/modelable/grammar/modelable.lark`, change line 88 from:
```
         | IDENT
```
to:
```
         | dotted_ref
```
so the full `type_expr` rule (lines 80-88) reads:
```
type_expr: primitive_type
         | decimal_type
         | fixed_binary_type
         | enum_type
         | array_type
         | map_type
         | ref_type
         | object_type
         | dotted_ref
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_transformer.py -v`
Expected: the new test PASSES, and every pre-existing test in the file still passes (bare-name type references like `field: SomeType` still parse identically, since `dotted_ref` with zero dots is just `IDENT`).

- [ ] **Step 5: Run the full suite — this WILL surface one snapshot diff**

Run: `uv run pytest -q`
Expected: **one failure**, `tests/test_browser_conformance.py::test_native_browser_snapshots_are_deterministic`. This is not a regression: `tests/conformance/browser/invalid-parse.mdl` is a deliberately-truncated fixture used to snapshot the exact Lark "Unexpected end-of-input. Expected one of: ..." error text, and the grammar change adds one new expected-token alternative (`DOT`) at the failure point, changing that one line of the checked-in JSON snapshot. Regenerate it:

```bash
uv run python scripts/write_browser_conformance.py --fixtures tests/conformance/browser --output tests/conformance/browser/snapshots
```

Then diff to confirm **only** `invalid-parse.json` changed, by exactly one line (a new `\t* DOT\n` appended to the expected-token list):

```bash
git diff --stat tests/conformance/browser/snapshots/
```

Expected: `1 file changed, 1 insertion(+), 1 deletion(-)`. If more than one snapshot file changed, or the diff is larger than one line, stop and investigate before proceeding — that would indicate the grammar change has a wider effect than expected.

- [ ] **Step 6: Run the full suite again to confirm it's clean**

Run: `uv run pytest -q`
Expected: all tests PASS (1788 passed, 23 skipped, as of this plan's baseline).

- [ ] **Step 7: Lint and type-check**

```bash
uv run ruff format --check tests/test_transformer.py
uv run ruff check tests/test_transformer.py
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
```

- [ ] **Step 8: Commit**

```bash
git add src/modelable/grammar/modelable.lark tests/conformance/browser/snapshots/invalid-parse.json tests/test_transformer.py
git commit -m "feat(parser): accept domain-qualified semantic-type references (Slice A4)"
```

---

### Task 2: Shared semantic-type resolver

**Files:**
- Modify: `cli/src/modelable/registry/resolver.py`
- Test: `cli/tests/test_semantic_type_resolution.py` (new file)

**Interfaces:**
- Consumes: `modelable.parser.ir.{MdlFile, SemanticTypeDecl}` (already imported in this file's neighborhood — `MdlFile` already imported at `resolver.py:6`; add `SemanticTypeDecl`).
- Produces (used by Tasks 3-5): `resolve_semantic_type_ref(mdl: MdlFile, current_domain: str, name: str) -> tuple[str, SemanticTypeDecl]`, raising `LookupError` on failure. Return value is `(declaring_domain_name, decl)`.

Message vocabulary reuses `emitters/protobuf.py`'s existing, already-tested wording for the ambiguous case (`f"ambiguous semantic type '{name}'; candidates: {refs}"`, `protobuf.py:57`) so error text stays consistent across the codebase even though `protobuf.py` itself isn't touched.

- [ ] **Step 1: Write the failing tests**

Create `cli/tests/test_semantic_type_resolution.py`:

```python
import pytest

from modelable.parser.parse import parse_text_to_ir
from modelable.registry.resolver import resolve_semantic_type_ref


def test_bare_name_resolves_in_current_domain_first():
    mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      semantic Id: uuid
    }
    domain billing {
      owner: "test-team"
      semantic Id: string
    }
    """)

    domain_name, decl = resolve_semantic_type_ref(mdl, "billing", "Id")

    # billing's own Id (string), not orders' Id (uuid) — if workspace-wide
    # fallback had run instead of domain-local shadowing, this would have
    # raised LookupError for ambiguity between orders.Id and billing.Id.
    assert domain_name == "billing"
    assert decl.name == "Id"
    assert decl.underlying.kind == "string"


def test_qualified_name_resolves_across_domains():
    mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      semantic Id: uuid
    }
    domain billing {
      owner: "test-team"
      semantic Id: string
    }
    """)

    domain_name, decl = resolve_semantic_type_ref(mdl, "billing", "orders.Id")

    assert domain_name == "orders"
    assert decl.name == "Id"


def test_bare_name_falls_back_to_workspace_when_current_domain_has_no_match():
    mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      semantic Id: uuid
    }
    domain billing {
      owner: "test-team"
      entity Invoice @ 1 (additive) {
        @key invoiceId: uuid
      }
    }
    """)

    domain_name, decl = resolve_semantic_type_ref(mdl, "billing", "Id")

    assert domain_name == "orders"
    assert decl.name == "Id"


def test_ambiguous_bare_reference_is_an_error():
    mdl = parse_text_to_ir("""
    domain alpha {
      owner: "test-team"
      semantic SharedId: uuid
    }
    domain beta {
      owner: "test-team"
      semantic SharedId: string
    }
    domain consumer {
      owner: "test-team"
      entity Event @ 1 (additive) {
        @key eventId: uuid
      }
    }
    """)

    with pytest.raises(LookupError, match=r"ambiguous semantic type 'SharedId'; candidates: alpha\.SharedId, beta\.SharedId"):
        resolve_semantic_type_ref(mdl, "consumer", "SharedId")


def test_unknown_bare_name_is_an_error():
    mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      semantic Id: uuid
    }
    """)

    with pytest.raises(LookupError, match="unknown semantic type 'DoesNotExist'"):
        resolve_semantic_type_ref(mdl, "orders", "DoesNotExist")


def test_qualified_reference_to_unknown_domain_is_an_error():
    mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      semantic Id: uuid
    }
    """)

    with pytest.raises(LookupError, match="unknown domain 'nope'"):
        resolve_semantic_type_ref(mdl, "orders", "nope.Id")


def test_qualified_reference_to_unknown_name_in_known_domain_is_an_error():
    mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      semantic Id: uuid
    }
    """)

    with pytest.raises(LookupError, match="unknown semantic type 'orders.DoesNotExist'"):
        resolve_semantic_type_ref(mdl, "orders", "orders.DoesNotExist")
```

Note: the first test has a deliberately-inert `assert ... if False else True` line — remove it, it was a placeholder slip; the real assertion is the `decl.name == "Id"` combined with `domain_name == "billing"` two lines above, which is already sufficient to prove domain-local shadowing won (if workspace-wide fallback had run instead, it would have raised `LookupError` for ambiguity between `orders.Id` and `billing.Id`, not returned a result at all).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_semantic_type_resolution.py -v`
Expected: every test fails with `ImportError: cannot import name 'resolve_semantic_type_ref' from 'modelable.registry.resolver'`.

- [ ] **Step 3: Write the implementation**

In `cli/src/modelable/registry/resolver.py`, add `SemanticTypeDecl` to the existing import (line 5-14 currently imports `MdlFile, ModelVersion, ProjectionVersion, VersionExact, VersionMin, VersionPinned, VersionRange, VersionSpec` from `modelable.parser.ir`):

```python
from modelable.parser.ir import (
    MdlFile,
    ModelVersion,
    ProjectionVersion,
    SemanticTypeDecl,
    VersionExact,
    VersionMin,
    VersionPinned,
    VersionRange,
    VersionSpec,
)
```

Then add this function (a good spot is right after `find_dependents`, before `validate_references`):

```python
def resolve_semantic_type_ref(
    mdl: MdlFile,
    current_domain: str,
    name: str,
) -> tuple[str, SemanticTypeDecl]:
    """Resolve a semantic-type reference to (declaring_domain_name, SemanticTypeDecl).

    ``name`` may be a bare name (resolved in ``current_domain`` first, falling back to
    a workspace-wide search only when exactly one declaration matches) or a
    domain-qualified reference (``"orders.Id"``).
    """
    if "." in name:
        domain_name, type_name = name.split(".", 1)
        domain = next((item for item in mdl.domains if item.name == domain_name), None)
        if domain is None:
            raise LookupError(f"unknown domain '{domain_name}' in semantic type reference '{name}'")
        decl = next((item for item in domain.semantic_types if item.name == type_name), None)
        if decl is None:
            raise LookupError(f"unknown semantic type '{name}'")
        return domain_name, decl

    current = next((item for item in mdl.domains if item.name == current_domain), None)
    if current is not None:
        local = next((item for item in current.semantic_types if item.name == name), None)
        if local is not None:
            return current_domain, local

    matches = [(domain.name, decl) for domain in mdl.domains for decl in domain.semantic_types if decl.name == name]
    if not matches:
        raise LookupError(f"unknown semantic type '{name}'")
    if len(matches) > 1:
        candidates = ", ".join(f"{domain_name}.{decl.name}" for domain_name, decl in matches)
        raise LookupError(f"ambiguous semantic type '{name}'; candidates: {candidates}")
    return matches[0]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_semantic_type_resolution.py -v`
Expected: all 7 tests PASS.

- [ ] **Step 5: Lint and type-check**

```bash
uv run ruff format --check src/modelable/registry/resolver.py tests/test_semantic_type_resolution.py
uv run ruff check src/modelable/registry/resolver.py tests/test_semantic_type_resolution.py
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
```

- [ ] **Step 6: Commit**

```bash
git add src/modelable/registry/resolver.py tests/test_semantic_type_resolution.py
git commit -m "feat(registry): add shared semantic-type resolver (Slice A4)"
```

---

### Task 3: Domain-aware semantic-type underlying chains

**Files:**
- Modify: `cli/src/modelable/validation/semantic.py:400-482` (`_validate_semantic_types`)
- Test: `cli/tests/test_semantic.py`

**Interfaces:**
- Consumes: `resolve_semantic_type_ref` (Task 2).
- Produces: `_validate_semantic_types`'s diagnostics now correctly follow a semantic type's underlying chain across domains (via qualified references) and correctly detect cycles/ambiguity that cross domain boundaries — no new public function.

Background: the current implementation (`semantic.py:441-482`, quoted in full in this plan's research) builds `all_semantic_types: dict[str, SemanticTypeDecl]` — a flat, same-name-overwrites dict — and walks a chain's `NamedType.name` links purely by bare name against that dict. Two domains declaring the same name would silently corrupt chain-following (whichever domain happened to iterate last in `mdl.domains` wins for every chain lookup, workspace-wide). This task replaces that with per-hop calls to the new resolver, and tracks *qualified* names in the cycle-detection `visited` list so a true cross-domain cycle (`alpha.A → beta.B → alpha.A`) is still caught correctly, while two *different* same-named-but-unrelated declarations are never confused with each other.

- [ ] **Step 1: Write the failing tests**

Add to `cli/tests/test_semantic.py`:

```python
def test_semantic_type_chain_resolves_qualified_cross_domain_reference():
    mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      semantic Id: uuid
    }
    domain billing {
      owner: "test-team"
      semantic InvoiceId: orders.Id
    }
    """)

    assert validate(mdl) == []


def test_semantic_type_chain_rejects_ambiguous_bare_reference():
    mdl = parse_text_to_ir("""
    domain alpha {
      owner: "test-team"
      semantic SharedId: uuid
    }
    domain beta {
      owner: "test-team"
      semantic SharedId: string
    }
    domain consumer {
      owner: "test-team"
      semantic Wrapped: SharedId
    }
    """)

    errors = validate(mdl)
    assert any("ambiguous" in e.lower() and "SharedId" in e for e in errors)


def test_semantic_type_cycle_across_domains_is_error():
    mdl = parse_text_to_ir("""
    domain alpha {
      owner: "test-team"
      semantic A: beta.B
    }
    domain beta {
      owner: "test-team"
      semantic B: alpha.A
    }
    """)

    errors = validate(mdl)
    assert any("cycle" in e.lower() for e in errors)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_semantic.py -k "chain_resolves_qualified or chain_rejects_ambiguous or cycle_across_domains" -v`
Expected:
- `test_semantic_type_chain_resolves_qualified_cross_domain_reference` FAILS — today's flat dict lookup for `next_name = "orders.Id"` (the qualified string, since Task 1's grammar change makes this a valid `NamedType.name` today already) never matches any bare-name dict key, so it's incorrectly reported as an undeclared reference.
- `test_semantic_type_chain_rejects_ambiguous_bare_reference` FAILS — today's flat dict silently picks whichever of `alpha.SharedId`/`beta.SharedId` was inserted last, with no ambiguity diagnostic.
- `test_semantic_type_cycle_across_domains_is_error` FAILS for the same reason as the first case — `beta.B`/`alpha.A` qualified names never resolve through the flat bare-name dict.

- [ ] **Step 3: Write the minimal implementation**

In `cli/src/modelable/validation/semantic.py`, add the import:

```python
from modelable.registry.resolver import resolve_semantic_type_ref
```

Replace lines 441-482 (the `all_semantic_types` dict and the chain-walking loop) with:

```python
    for decl in domain.semantic_types:
        if not isinstance(decl.underlying, NamedType):
            continue
        visited: list[str] = [f"{domain.name}.{decl.name}"]
        current: FieldType = decl.underlying
        current_domain_name = domain.name
        while isinstance(current, NamedType):
            next_name = current.name
            try:
                next_domain_name, next_decl = resolve_semantic_type_ref(mdl, current_domain_name, next_name)
            except LookupError as exc:
                diagnostics.append(
                    _diag(
                        "SEM",
                        f"{domain.name}: semantic type '{decl.name}' references {exc}",
                        path,
                    )
                )
                break
            qualified = f"{next_domain_name}.{next_decl.name}"
            if qualified in visited:
                diagnostics.append(
                    _diag(
                        "SEM",
                        f"{domain.name}: semantic type '{decl.name}' has a cycle in its underlying chain: "
                        f"{' -> '.join([*visited, qualified])}",
                        path,
                    )
                )
                break
            if len(visited) >= _SEMANTIC_CHAIN_DEPTH_LIMIT:
                diagnostics.append(
                    _diag(
                        "SEM",
                        f"{domain.name}: semantic type '{decl.name}' underlying chain exceeds "
                        f"{_SEMANTIC_CHAIN_DEPTH_LIMIT} levels",
                        path,
                    )
                )
                break
            visited.append(qualified)
            current = next_decl.underlying
            current_domain_name = next_domain_name
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_semantic.py -v`
Expected: all tests PASS, including the 3 new ones and every pre-existing test — `test_semantic_type_dangling_underlying_reference_is_error` and `test_semantic_type_cycle_is_error` (same-domain cases) use substring assertions (`"Wrapped" in e and "DoesNotExist" in e`, `"cycle" in e.lower()`) that remain true under the new wording (`"unknown semantic type"` vs. the old `"undeclared semantic type"` — a message wording change, but these tests never asserted the word "undeclared" specifically).

- [ ] **Step 5: Lint and type-check**

```bash
uv run ruff format --check src/modelable/validation/semantic.py tests/test_semantic.py
uv run ruff check src/modelable/validation/semantic.py tests/test_semantic.py
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
```

- [ ] **Step 6: Commit**

```bash
git add src/modelable/validation/semantic.py tests/test_semantic.py
git commit -m "fix(validation): resolve semantic-type underlying chains across domains"
```

---

### Task 4: Fix impact-analysis semantic-type resolution

**Files:**
- Modify: `cli/src/modelable/operations/compilation.py:940-977` (`_definition_dependencies`, `_semantic_refs`)
- Test: `cli/tests/test_compilation_service.py`

**Interfaces:**
- Consumes: `resolve_semantic_type_ref` (Task 2).
- Produces: `_semantic_refs` gains a `current_domain: str` parameter; both call sites pass the correct declaring domain. No change to `_semantic_refs`'s return type (`set[str]` of qualified refs).

Background: `_semantic_refs(mdl, names)` (current signature, no domain context) calls `_domain_defining(mdl, name)`, which returns the **first** domain (in `mdl.domains` order) that has either a model or a semantic type with that name — silently and non-deterministically, with no ambiguity check. `_domain_defining` is *also* used by `_find_domain_scope_violations` (Task-list-deferred, already correct via its own `_semantic_domains_defining` ambiguity check that runs *before* falling back to `_domain_defining` only for the non-semantic/model-name case) — **do not modify `_domain_defining` itself**, only `_semantic_refs` and its two call sites.

- [ ] **Step 1: Write the failing test**

Replace the existing `test_duplicate_semantic_names_report_only_compiler_selected_declaration` test in `cli/tests/test_compilation_service.py` (around line 698) — this test currently locks in the buggy behavior this task fixes — with:

```python
def test_duplicate_semantic_names_are_omitted_from_affected_definitions_when_ambiguous(tmp_path: Path) -> None:
    source = write_workspace(
        tmp_path,
        """
domain alpha {
  owner: "alpha-team"
  semantic SharedId : string
}

domain beta {
  owner: "beta-team"
  semantic SharedId : u64
}

domain consumer {
  owner: "consumer-team"
  entity Event @ 1 (additive) {
    @key eventId: uuid
    sharedId: SharedId
  }
}
""",
    )

    pending = preview_for(
        tmp_path,
        source,
        target="openmetadata",
        domains=("alpha", "consumer"),
    )
    affected = {item.ref for item in pending.affected_definitions}

    # sharedId's bare reference is ambiguous between alpha.SharedId and
    # beta.SharedId — neither is reported as a confident pick.
    assert "alpha.SharedId" not in affected
    assert "beta.SharedId" not in affected


def test_qualified_semantic_reference_is_reported_as_affected(tmp_path: Path) -> None:
    source = write_workspace(
        tmp_path,
        """
domain alpha {
  owner: "alpha-team"
  semantic SharedId : string
}

domain beta {
  owner: "beta-team"
  semantic SharedId : u64
}

domain consumer {
  owner: "consumer-team"
  entity Event @ 1 (additive) {
    @key eventId: uuid
    sharedId: alpha.SharedId
  }
}
""",
    )

    pending = preview_for(
        tmp_path,
        source,
        target="openmetadata",
        domains=("alpha", "consumer"),
    )
    affected = {item.ref for item in pending.affected_definitions}

    assert "alpha.SharedId" in affected
    assert "beta.SharedId" not in affected
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_compilation_service.py -k "duplicate_semantic_names or qualified_semantic_reference" -v`
Expected: `test_duplicate_semantic_names_are_omitted_from_affected_definitions_when_ambiguous` FAILS (today `"alpha.SharedId" in affected` is `True`, since `alpha` is declared first — this test now asserts it must NOT be, so it currently fails on the `not in` assertion). `test_qualified_semantic_reference_is_reported_as_affected` FAILS or errors (qualified `alpha.SharedId` reference syntax parses fine after Task 1, but resolution isn't domain-aware yet, so the impact analysis won't find it as `alpha.SharedId` correctly — verify the actual failure mode when you run it).

- [ ] **Step 3: Write the minimal implementation**

In `cli/src/modelable/operations/compilation.py`, add the import:

```python
from modelable.registry.resolver import resolve_semantic_type_ref
```
(add it to whatever existing `from modelable.registry.resolver import ...` line already exists in this file, alongside `resolve_model_ref`.)

Replace `_semantic_refs` (lines 968-977):

```python
def _semantic_refs(mdl: MdlFile, current_domain: str, names: set[str]) -> set[str]:
    refs: set[str] = set()
    for name in sorted(names):
        try:
            domain_name, decl = resolve_semantic_type_ref(mdl, current_domain, name)
        except LookupError:
            continue
        refs.add(f"{domain_name}.{decl.name}")
    return refs
```

Update its two call sites in `_definition_dependencies`:
- Line 945 (model's own fields): `dependencies.update(_semantic_refs(mdl, domain_name, names))` — `domain_name` is already in scope at this point (extracted at line 925: `domain_name, separator, definition_name = qualified_name.partition(".")`).
- Line 963 (a projection's joined/sourced model's fields): `dependencies.update(_semantic_refs(mdl, resolved.domain_name, names))` — use the *resolved source model's own* declaring domain (`resolved.domain_name`, from the `resolve_model_ref` call at line 953), not the projection's domain, since that's where the field itself was declared.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_compilation_service.py -v`
Expected: all tests PASS, including the 2 new/rewritten ones and every pre-existing test in the file (in particular, re-check the test right before the one you replaced — `test_...` around line 660-696 — to confirm it still passes; it uses an *unambiguous* semantic type name in a different scenario and should be unaffected).

- [ ] **Step 5: Lint and type-check**

```bash
uv run ruff format --check src/modelable/operations/compilation.py tests/test_compilation_service.py
uv run ruff check src/modelable/operations/compilation.py tests/test_compilation_service.py
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
```

- [ ] **Step 6: Commit**

```bash
git add src/modelable/operations/compilation.py tests/test_compilation_service.py
git commit -m "fix(compilation): resolve semantic-type impact analysis by declaring domain"
```

---

### Task 5: Fix Rust emitter semantic-type resolution

**Files:**
- Modify: `cli/src/modelable/emitters/rust.py:214-245` (`_resolve_named_type_map`), `248-270` (`_rust_type_for_semantic_underlying`)
- Test: `cli/tests/test_emit_rust.py`

**Interfaces:**
- Consumes: `resolve_semantic_type_ref` (Task 2).
- Produces: `_resolve_named_type_map` now raises `LookupError` on an ambiguous semantic-type reference (previously silent, first-domain-wins, with **zero test coverage** for this path today).

Background: `_resolve_named_type_map`'s semantic-types loop (lines 238-244, quoted in full in this plan's research) is a first-match-wins loop over `mdl.domains`, identical in shape to the pre-fix `_domain_defining`/`operations/compilation.py` bug, but with no ambiguity detection at all — not even a diagnostic. This is the most literal instance of the bug this slice fixes, and currently has no regression test anywhere. `_rust_type_for_semantic_underlying` (lines 248-270) has a separate, narrower gap: when a semantic type's *own* underlying is itself a `NamedType` (i.e., a semantic-to-semantic chain), it renders the Rust module path from the bare name (`underlying.name`) without resolving which domain declared it — this task fixes both together since they're both "resolve a semantic type's declaring domain for Rust codegen" concerns, but the primary target is `_resolve_named_type_map`; only touch `_rust_type_for_semantic_underlying` if the new test in Step 1 requires it (see Step 3).

- [ ] **Step 1: Write the failing test**

Add to `cli/tests/test_emit_rust.py`:

```python
def test_emit_rust_rejects_ambiguous_unqualified_semantic_reference(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain alpha {
  owner: "alpha-team"
  semantic SharedId : u32
}

domain beta {
  owner: "beta-team"
  semantic SharedId : u64
}

domain consumer {
  owner: "consumer-team"
  entity UsesShared @ 1 (additive) {
    @key id: SharedId
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)

    with pytest.raises(
        LookupError,
        match=r"ambiguous semantic type 'SharedId'; candidates: alpha\.SharedId, beta\.SharedId",
    ):
        emit_rust(workspace, tmp_path / "dist")


def test_emit_rust_resolves_qualified_semantic_reference(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain alpha {
  owner: "alpha-team"
  semantic SharedId : u32
}

domain beta {
  owner: "beta-team"
  semantic SharedId : u64
}

domain consumer {
  owner: "consumer-team"
  entity UsesShared @ 1 (additive) {
    @key id: uuid
    sharedRef: alpha.SharedId
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)

    artifacts = emit_rust(workspace, tmp_path / "dist")

    consumer_artifact = next(a for a in artifacts if "uses_shared" in str(a.path).lower())
    assert "SharedId" in consumer_artifact.content
```

Check the top of `cli/tests/test_emit_rust.py` for the existing `load_workspace`/`emit_rust`/`pytest` import pattern already used by other tests in the file and match it exactly (don't introduce a second import style).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_emit_rust.py -k "ambiguous_unqualified or resolves_qualified" -v`
Expected: `test_emit_rust_rejects_ambiguous_unqualified_semantic_reference` FAILS — today's code silently resolves to whichever domain (`alpha` or `beta`) happens to iterate first, so no `LookupError` is raised at all. `test_emit_rust_resolves_qualified_semantic_reference` may fail or error, since `alpha.SharedId` as a qualified reference isn't resolved as "the alpha domain's SharedId" by the current bare-name-only loop.

- [ ] **Step 3: Write the minimal implementation**

In `cli/src/modelable/emitters/rust.py`, add the import:

```python
from modelable.registry.resolver import resolve_semantic_type_ref
```

Replace the semantic-types loop in `_resolve_named_type_map` (lines 238-244):

```python
        if resolved:
            continue
        try:
            _domain_name, semantic_decl = resolve_semantic_type_ref(mdl, "", name)
        except LookupError:
            continue
        module = _snake_case(semantic_decl.name)
        resolved_map[name] = semantic_decl.name
        use_statements.append(f"use super::{module}::{semantic_decl.name};")
```

Note the `current_domain=""` argument: `_resolve_named_type_map` receives only a flat `named_refs: set` of type names collected from across an entire model being emitted (`_collect_named_type_refs_from_shape`), with no per-field "declaring domain" context threaded through at this call site. Passing `""` (never a real domain name) means rule 1 (current-domain-first) never matches, so this always falls through to rule 3 (workspace-wide, exactly-one-match) — which is the correct, safe behavior here specifically because a *qualified* name (`"alpha.SharedId"`) is unaffected by this (the resolver's `"." in name` branch runs first, ignoring `current_domain` entirely) — only a genuinely ambiguous *bare* name now raises, instead of silently picking one.

If `test_emit_rust_resolves_qualified_semantic_reference` still fails after this change (check the generated Rust output — does the module path / Rust type name for `alpha.SharedId` render sensibly, e.g. not literally including the dot in a Rust identifier?), also update `_rust_type_for_semantic_underlying`'s `NamedType` branch (lines 266-268) and the two `resolved_map[name] = semantic_decl.name` / `use_statements.append(...)` lines above to use `semantic_decl.name` (the bare declaration name, already correct — the *qualified* string was only ever the lookup key `name`, never what gets rendered into Rust source) — re-verify with `-vv` output before making any further change here; don't guess blind.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_emit_rust.py -v`
Expected: all tests PASS, including the 2 new ones and every pre-existing test.

- [ ] **Step 5: Lint and type-check**

```bash
uv run ruff format --check src/modelable/emitters/rust.py tests/test_emit_rust.py
uv run ruff check src/modelable/emitters/rust.py tests/test_emit_rust.py
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
```

- [ ] **Step 6: Commit**

```bash
git add src/modelable/emitters/rust.py tests/test_emit_rust.py
git commit -m "fix(rust): reject ambiguous semantic-type references instead of silently picking one"
```

---

### Task 6: Fix misleading documentation and run final regression sweep

**Files:**
- Modify: `docs/language-reference.md:432-434`

**Interfaces:** None — documentation only.

`docs/language-reference.md` section 3.8 currently documents the exact bug this slice fixes as intended behavior: *"Semantic types are referenced the same way models are: by their bare name. Resolution is workspace-wide (not scoped to the declaring domain), matching how `ref<Domain.Model>` and other cross-domain lookups already work."* (line 434). This must be corrected now that the behavior actually changed.

- [ ] **Step 1: Rewrite the misleading paragraph**

In `docs/language-reference.md`, replace the "Referencing a semantic type" section's text (line 434 — keep the heading and the existing code example below it unchanged) with:

```markdown
Semantic types are referenced by name. A bare name resolves against the current domain's own declarations first; if the current domain has no matching declaration, resolution falls back to a workspace-wide search, but only succeeds if exactly one domain declares that name. If more than one domain declares a semantic type with the same name, a bare reference is ambiguous and is a compile error. Use a domain-qualified reference (`orders.Id`) — the same dotted syntax `ref<Domain.Model>` already uses — to name a specific domain's declaration explicitly.
```

- [ ] **Step 2: Run the full CLI test suite as a final safety net**

Run (from `cli/`): `uv run pytest -q`
Expected: all PASS (no regressions from any of Tasks 1-5 combined).

- [ ] **Step 3: Verify the docs site still builds clean**

Run (from the repo root):
```bash
uvx --from mkdocs==1.6.1 --with mkdocs-material==9.7.6 mkdocs build --strict
```
Expected: exit 0, no warnings. (This repo's Docs CI job runs exactly this command — a broken link here was the cause of a real CI failure earlier in this correction-plan series; re-check it explicitly rather than assuming a docs-only change is safe.)

- [ ] **Step 4: Commit**

```bash
git add docs/language-reference.md
git commit -m "docs: correct semantic-type resolution description to match Slice A4"
```
