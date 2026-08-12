# Expression Position Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the gap where `projection` `where` clauses, `group by` keys, and join predicates parse successfully but are never run through CEL validation — so an unknown alias, unknown field, or non-boolean filter in those positions compiles silently today.

**Architecture:** `compiler/workspace.py:_validate_cel` already validates computed fields and join predicates for alias/field existence via `modelable.expressions.cel.validate_cel_expr`, but never touches `pv.where`/`pv.group_by` at all, and never checks that a filter/predicate is actually boolean-shaped. This plan adds a new structural `looks_boolean()` check to `expressions/cel.py` (there is no field-type-aware type checker in this compiler, so it only rejects expressions provably non-boolean — arithmetic, non-boolean literals, known non-boolean functions — and stays permissive on bare field references, to avoid false positives against real boolean-typed source fields), then wires `where`, `group_by`, and join predicates into `_validate_cel`.

**Tech Stack:** Python 3.14, pytest (`uv run pytest`), existing `modelable.expressions.cel` parser/validator.

## Global Constraints

- This is Slice A3 of `docs/correction-and-capability-plan.md`. Full purpose/scope/acceptance-criteria text lives there under "Slice A3 — validate all expression positions"; this plan implements it.
- **Explicitly deferred, not in this plan** (document these in the PR description too):
  - `@pitCutoff`/`@latestBefore` expression-bearing annotations (`parser/ir.py:116-123`) stay unvalidated. They attach at multiple grammar points (`field_decl`, `join_clause`, `proj_field`) with genuinely different validation contexts at each — a model-field attachment has no projection alias scope at all. There is zero existing test/usage precedent to anchor correct semantics against, so guessing the validation context risks encoding wrong behavior. Left for a follow-up slice once a concrete usage exists to validate against.
  - "Computed result types are resolved where supported" (from A3's scope text) is not attempted — there is no existing computed-field type-inference facility anywhere in the compiler (`ComputedMapping` carries only `expression: str`; emitters hardcode `"unknown"` for computed field types). Building one is a real type-inference project, not a validation-completeness fix, and is out of scope here.
  - This plan does not change `ComputedMapping`/`ProjectionField`/`JoinRef` shapes — only `compiler/workspace.py` and `expressions/cel.py` are touched.
- `_validate_cel` runs once, in `load_workspace_from_sources` (`compiler/workspace.py:98`), which is the single entry point for both the CLI (`load_workspace`) and the LSP (`language/workspace.py:70,123`) — there is no separate validation path to also update.
- Diagnostic codes in this file follow the existing "CELNNN: description" convention (CEL001 parse error, CEL002 unknown alias/field, CEL005 unsupported function, CEL006 aggregate without group by, CEL007 non-deterministic function — CEL003/CEL004 are not in use). This plan introduces **CEL008: expression must be a boolean predicate**.
- Run `uv run ruff format --check <files>`, `uv run ruff check <files>`, and the mypy baseline ratchet (`uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes`, from `cli/`) before each commit.
- All commands below assume the current working directory is `cli/` inside the repo checkout.

---

### Task 1: Add a structural `looks_boolean` check to `expressions/cel.py`

**Files:**
- Modify: `cli/src/modelable/expressions/cel.py`
- Test: `cli/tests/test_cel_validation.py`

**Interfaces:**
- Consumes: existing AST node classes `BinaryOp`, `UnaryOp`, `TernaryOp`, `Literal`, `FunctionCall`, `ListLiteral`, `ObjectLiteral`, `WildcardRef`, `FieldRef`, `RuntimeRef`, `CelExpr`, and the existing `_SCALAR_FUNCTIONS`/`_AGGREGATE_FUNCTIONS` frozensets already defined in this file.
- Produces (used by Tasks 2-4): `looks_boolean(expr: CelExpr) -> bool`.

Background: confirmed operator strings from the parser (`expressions/cel.py:213-263`): comparison/logical `BinaryOp.op` values are `"=="`, `"!="`, `"<"`, `"<="`, `">"`, `">="`, `"in"`, `"&&"`, `"||"`; arithmetic ones are `"+"`, `"-"`, `"*"`, `"/"`, `"%"`. `UnaryOp.op` is `"!"` for logical negation or `"-"` for numeric negation. `Literal.value` is a plain `str | int | float | bool | None`, and Python's `isinstance(x, bool)` correctly excludes `int`/`float`/`str`/`None` (booleans are the only values matching `isinstance(x, bool)` among these). There is no field-type information available in `CelContext` (it only has `source_fields: dict[str, set[str]]`, field *names* not types), so a bare `FieldRef`/`RuntimeRef` or an unrecognized function name must be treated as "cannot tell" (return `True`, i.e. don't flag it) rather than assumed non-boolean — otherwise a real boolean-typed field like `where c.isActive` would be wrongly rejected.

- [ ] **Step 1: Write the failing tests**

Add to `cli/tests/test_cel_validation.py`, in a new section before "End-to-end via workspace":

```python
# ── Boolean-shape tests ─────────────────────────────────────────────────────


def test_looks_boolean_comparison_is_boolean():
    ast, _ = parse_cel('c.status == "active"')
    assert looks_boolean(ast) is True


def test_looks_boolean_logical_and_is_boolean():
    ast, _ = parse_cel('c.a == "x" && c.b == "y"')
    assert looks_boolean(ast) is True


def test_looks_boolean_in_operator_is_boolean():
    ast, _ = parse_cel('c.status in ["active", "pending"]')
    assert looks_boolean(ast) is True


def test_looks_boolean_arithmetic_is_not_boolean():
    ast, _ = parse_cel("c.amount + 1")
    assert looks_boolean(ast) is False


def test_looks_boolean_negation_is_boolean():
    ast, _ = parse_cel("!c.flag")
    assert looks_boolean(ast) is True


def test_looks_boolean_numeric_negation_is_not_boolean():
    ast, _ = parse_cel("-c.amount")
    assert looks_boolean(ast) is False


def test_looks_boolean_ternary_with_boolean_branches_is_boolean():
    ast, _ = parse_cel("c.a == 1 ? c.b == 2 : c.c == 3")
    assert looks_boolean(ast) is True


def test_looks_boolean_ternary_with_non_boolean_branch_is_not_boolean():
    ast, _ = parse_cel('c.flag ? "yes" : "no"')
    assert looks_boolean(ast) is False


def test_looks_boolean_true_literal_is_boolean():
    ast, _ = parse_cel("true")
    assert looks_boolean(ast) is True


def test_looks_boolean_string_literal_is_not_boolean():
    ast, _ = parse_cel('"active"')
    assert looks_boolean(ast) is False


def test_looks_boolean_int_literal_is_not_boolean():
    ast, _ = parse_cel("5")
    assert looks_boolean(ast) is False


def test_looks_boolean_null_literal_is_not_boolean():
    ast, _ = parse_cel("null")
    assert looks_boolean(ast) is False


def test_looks_boolean_contains_function_is_boolean():
    ast, _ = parse_cel('contains(c.name, "smith")')
    assert looks_boolean(ast) is True


def test_looks_boolean_scalar_function_is_not_boolean():
    ast, _ = parse_cel("lower(c.name)")
    assert looks_boolean(ast) is False


def test_looks_boolean_aggregate_function_is_not_boolean():
    ast, _ = parse_cel("count(c.id)")
    assert looks_boolean(ast) is False


def test_looks_boolean_unrecognized_function_is_permissive():
    ast, _ = parse_cel("someCustomFn(c.id)")
    assert looks_boolean(ast) is True


def test_looks_boolean_bare_field_ref_is_permissive():
    ast, _ = parse_cel("c.isActive")
    assert looks_boolean(ast) is True


def test_looks_boolean_list_literal_is_not_boolean():
    ast, _ = parse_cel("[1, 2, 3]")
    assert looks_boolean(ast) is False
```

And add `looks_boolean` to the import block at the top of the file:

```python
from modelable.expressions.cel import (
    BinaryOp,
    CelContext,
    FieldRef,
    FunctionCall,
    Literal,
    TernaryOp,
    extract_field_refs,
    looks_boolean,
    parse_cel,
    validate_cel_expr,
)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_cel_validation.py -k looks_boolean -v`
Expected: every test fails with `ImportError: cannot import name 'looks_boolean' from 'modelable.expressions.cel'`.

- [ ] **Step 3: Write the implementation**

In `cli/src/modelable/expressions/cel.py`, add after the `extract_field_refs`/`_collect_refs` block at the end of the file (after line ~539, the end of `_collect_refs`):

```python
# ── Boolean-shape check ─────────────────────────────────────────────────────

_BOOLEAN_BINARY_OPS = frozenset({"==", "!=", "<", "<=", ">", ">=", "in", "&&", "||"})
_BOOLEAN_FUNCTIONS = frozenset({"contains", "startsWith", "endsWith"})


def looks_boolean(expr: CelExpr) -> bool:
    """Structural check for whether a CEL expression could be a boolean predicate.

    There is no field-type-aware CEL type checker in this compiler, so this only
    rejects expressions provably not boolean (arithmetic, a non-boolean literal, a
    list/object literal, a wildcard, or a function known to return something other
    than a boolean). A bare field reference or an unrecognized function name is
    treated as "cannot tell" rather than flagged, so a real boolean-typed source
    field like `c.isActive` is never wrongly rejected.
    """
    if isinstance(expr, BinaryOp):
        return expr.op in _BOOLEAN_BINARY_OPS
    if isinstance(expr, UnaryOp):
        return expr.op == "!"
    if isinstance(expr, TernaryOp):
        return looks_boolean(expr.then_) and looks_boolean(expr.else_)
    if isinstance(expr, Literal):
        return isinstance(expr.value, bool)
    if isinstance(expr, FunctionCall):
        if expr.name in _BOOLEAN_FUNCTIONS:
            return True
        if expr.name in _SCALAR_FUNCTIONS or expr.name in _AGGREGATE_FUNCTIONS:
            return False
        return True
    if isinstance(expr, (ListLiteral, ObjectLiteral, WildcardRef)):
        return False
    return True
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_cel_validation.py -v`
Expected: all tests in the file PASS (the new `looks_boolean` tests plus every pre-existing test in this file, unaffected).

- [ ] **Step 5: Lint and type-check**

```bash
uv run ruff format --check src/modelable/expressions/cel.py tests/test_cel_validation.py
uv run ruff check src/modelable/expressions/cel.py tests/test_cel_validation.py
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
```

- [ ] **Step 6: Commit**

```bash
git add src/modelable/expressions/cel.py tests/test_cel_validation.py
git commit -m "feat(cel): add structural boolean-shape check (Slice A3)"
```

---

### Task 2: Validate `where` clauses

**Files:**
- Modify: `cli/src/modelable/compiler/workspace.py:255-333` (`_validate_cel`)
- Test: `cli/tests/test_cel_validation.py`

**Interfaces:**
- Consumes: `modelable.expressions.cel.looks_boolean` (Task 1), and the existing `ctx: CelContext` already built per-projection inside `_validate_cel` (`workspace.py:276-280`).
- Produces: no new public function — `_validate_cel`'s error list now includes `where`-clause diagnostics.

Today `_validate_cel` builds `ctx` (alias → field-name set) once per projection version and uses it only for computed fields and join predicates; `pv.where` is never read in this function at all (confirmed by grep — no file in `cli/src` runs `pv.where` through CEL validation).

- [ ] **Step 1: Write the failing tests**

Add to `cli/tests/test_cel_validation.py`, in the "End-to-end via workspace" section, using the exact `load_workspace`/`tempfile`/`textwrap` pattern `test_workspace_rejects_invalid_cel` already uses:

```python
def test_workspace_rejects_unknown_alias_in_where():
    import tempfile
    import textwrap
    from pathlib import Path

    from modelable.compiler.workspace import load_workspace

    mdl_text = textwrap.dedent("""\
        domain customer {
          owner: "test-team"
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            status: string
          }
        }
        domain billing {
          owner: "test-team"
          projection BadProj @ 1
            from customer.Customer @ 1 as c
            where x.status == "active"
          {
            id <- c.customerId
          }
        }
    """)
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "test.mdl").write_text(mdl_text, encoding="utf-8")
        ws = load_workspace(tmp)
    assert any("CEL002" in diagnostic.message and "unknown alias 'x'" in diagnostic.message for diagnostic in ws.errors)


def test_workspace_rejects_unknown_field_in_where():
    import tempfile
    import textwrap
    from pathlib import Path

    from modelable.compiler.workspace import load_workspace

    mdl_text = textwrap.dedent("""\
        domain customer {
          owner: "test-team"
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            status: string
          }
        }
        domain billing {
          owner: "test-team"
          projection BadProj @ 1
            from customer.Customer @ 1 as c
            where c.nonExistentField == "active"
          {
            id <- c.customerId
          }
        }
    """)
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "test.mdl").write_text(mdl_text, encoding="utf-8")
        ws = load_workspace(tmp)
    assert any("CEL002" in diagnostic.message and "nonExistentField" in diagnostic.message for diagnostic in ws.errors)


def test_workspace_rejects_non_boolean_where():
    import tempfile
    import textwrap
    from pathlib import Path

    from modelable.compiler.workspace import load_workspace

    mdl_text = textwrap.dedent("""\
        domain customer {
          owner: "test-team"
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            status: string
          }
        }
        domain billing {
          owner: "test-team"
          projection BadProj @ 1
            from customer.Customer @ 1 as c
            where lower(c.status)
          {
            id <- c.customerId
          }
        }
    """)
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "test.mdl").write_text(mdl_text, encoding="utf-8")
        ws = load_workspace(tmp)
    assert any("CEL008" in diagnostic.message for diagnostic in ws.errors)


def test_workspace_accepts_valid_where():
    import tempfile
    import textwrap
    from pathlib import Path

    from modelable.compiler.workspace import load_workspace

    mdl_text = textwrap.dedent("""\
        domain customer {
          owner: "test-team"
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            status: string
          }
        }
        domain billing {
          owner: "test-team"
          projection GoodProj @ 1
            from customer.Customer @ 1 as c
            where c.status == "active"
          {
            id <- c.customerId
          }
        }
    """)
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "test.mdl").write_text(mdl_text, encoding="utf-8")
        ws = load_workspace(tmp)
    cel_errors = [d.message for d in ws.errors if "CEL" in d.code]
    assert cel_errors == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_cel_validation.py -k where -v`
Expected: `test_workspace_rejects_unknown_alias_in_where`, `test_workspace_rejects_unknown_field_in_where`, and `test_workspace_rejects_non_boolean_where` all FAIL (empty `ws.errors` for CEL codes, since `pv.where` is never validated today). `test_workspace_accepts_valid_where` passes already (nothing rejects it yet) — that's expected and fine, it's a guard against a future regression, not a RED test for new behavior.

- [ ] **Step 3: Write the minimal implementation**

In `cli/src/modelable/compiler/workspace.py`:
1. Add `looks_boolean` to the existing import line (line 8):
   ```python
   from modelable.expressions.cel import CelContext, looks_boolean, parse_cel, validate_cel_expr
   ```
2. Insert a `where`-validation block into `_validate_cel`, right after the `ctx = CelContext(...)` construction (after line 280, before the `for proj_field in pv.fields:` loop at line 282):

```python
                if pv.where:
                    ast, parse_errors = parse_cel(pv.where)
                    for err in parse_errors:
                        errors.append(
                            Diagnostic(
                                code="CEL",
                                message=f"{fqn} where: {err}",
                                severity="error",
                                path="<workspace>",
                            )
                        )
                    if ast is not None:
                        result = validate_cel_expr(ast, ctx)
                        for err in result.errors:
                            errors.append(
                                Diagnostic(
                                    code="CEL",
                                    message=f"{fqn} where: {err}",
                                    severity="error",
                                    path="<workspace>",
                                )
                            )
                        if not looks_boolean(ast):
                            errors.append(
                                Diagnostic(
                                    code="CEL",
                                    message=f"{fqn} where: CEL008: expression must be a boolean predicate",
                                    severity="error",
                                    path="<workspace>",
                                )
                            )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_cel_validation.py -v`
Expected: all tests in the file PASS, including all four new `where` tests and every pre-existing test.

- [ ] **Step 5: Lint and type-check**

```bash
uv run ruff format --check src/modelable/compiler/workspace.py tests/test_cel_validation.py
uv run ruff check src/modelable/compiler/workspace.py tests/test_cel_validation.py
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
```

- [ ] **Step 6: Commit**

```bash
git add src/modelable/compiler/workspace.py tests/test_cel_validation.py
git commit -m "fix(compiler): validate projection where clauses through CEL"
```

---

### Task 3: Validate `group by` expressions

**Files:**
- Modify: `cli/src/modelable/compiler/workspace.py` (`_validate_cel`, right after Task 2's `where` block)
- Test: `cli/tests/test_cel_validation.py`

**Interfaces:**
- Consumes: existing `CelContext`, `parse_cel`, `validate_cel_expr` (no new function needed — group-by keys are not required to be boolean, so `looks_boolean` is not used here).
- Produces: `_validate_cel`'s error list now includes `group by`-clause diagnostics.

A group-by key must reference existing aliases/fields (same check as everywhere else) and must not itself contain an aggregate function (grouping happens *before* aggregation, so `group by count(o.orderId)` is nonsensical). The existing `validate_cel_expr`/`_walk` already raises `CEL006: aggregate function used in projection without group by` whenever a `CelContext` has `has_group_by=False` and the expression contains an aggregate call (`expressions/cel.py:491-492`) — reusing that check with a group-by-specific context (`has_group_by=False`, independent of whether the projection has a `group_by` clause) gets "no aggregates in group keys" for free without new logic in `cel.py`.

- [ ] **Step 1: Write the failing tests**

Add to `cli/tests/test_cel_validation.py`:

```python
def test_workspace_rejects_unknown_field_in_group_by():
    import tempfile
    import textwrap
    from pathlib import Path

    from modelable.compiler.workspace import load_workspace

    mdl_text = textwrap.dedent("""\
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            customerId: uuid
          }
        }
        domain billing {
          owner: "test-team"
          projection BadProj @ 1
            from orders.Order @ 1 as o
            group by o.nonExistentField
          {
            orderCount = count(o.orderId)
          }
        }
    """)
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "test.mdl").write_text(mdl_text, encoding="utf-8")
        ws = load_workspace(tmp)
    assert any("CEL002" in diagnostic.message and "nonExistentField" in diagnostic.message for diagnostic in ws.errors)


def test_workspace_rejects_aggregate_inside_group_by():
    import tempfile
    import textwrap
    from pathlib import Path

    from modelable.compiler.workspace import load_workspace

    mdl_text = textwrap.dedent("""\
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            customerId: uuid
          }
        }
        domain billing {
          owner: "test-team"
          projection BadProj @ 1
            from orders.Order @ 1 as o
            group by count(o.orderId)
          {
            orderCount = count(o.orderId)
          }
        }
    """)
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "test.mdl").write_text(mdl_text, encoding="utf-8")
        ws = load_workspace(tmp)
    assert any("CEL006" in diagnostic.message for diagnostic in ws.errors)


def test_workspace_accepts_valid_group_by():
    import tempfile
    import textwrap
    from pathlib import Path

    from modelable.compiler.workspace import load_workspace

    mdl_text = textwrap.dedent("""\
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            customerId: uuid
          }
        }
        domain billing {
          owner: "test-team"
          projection GoodProj @ 1
            from orders.Order @ 1 as o
            group by o.customerId
          {
            customerId <- o.customerId
            orderCount = count(o.orderId)
          }
        }
    """)
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "test.mdl").write_text(mdl_text, encoding="utf-8")
        ws = load_workspace(tmp)
    cel_errors = [d.message for d in ws.errors if "CEL" in d.code]
    assert cel_errors == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_cel_validation.py -k group_by -v`
Expected: `test_workspace_rejects_unknown_field_in_group_by` and `test_workspace_rejects_aggregate_inside_group_by` FAIL (empty CEL errors — `pv.group_by` is never parsed as CEL today). `test_workspace_accepts_valid_group_by` already passes.

- [ ] **Step 3: Write the minimal implementation**

In `cli/src/modelable/compiler/workspace.py`, insert a `group by`-validation block into `_validate_cel`, right after Task 2's `where` block and before the `for proj_field in pv.fields:` loop:

```python
                if pv.group_by:
                    group_ctx = CelContext(source_fields=source_fields, has_group_by=False, fqn=fqn)
                    for group_expr in pv.group_by:
                        ast, parse_errors = parse_cel(group_expr)
                        for err in parse_errors:
                            errors.append(
                                Diagnostic(
                                    code="CEL",
                                    message=f"{fqn} group by: {err}",
                                    severity="error",
                                    path="<workspace>",
                                )
                            )
                        if ast is not None:
                            result = validate_cel_expr(ast, group_ctx)
                            for err in result.errors:
                                errors.append(
                                    Diagnostic(
                                        code="CEL",
                                        message=f"{fqn} group by: {err}",
                                        severity="error",
                                        path="<workspace>",
                                    )
                                )
```

Note `group_ctx` deliberately uses `has_group_by=False` (not the projection's own `bool(pv.group_by)`, which is always `True` inside this `if pv.group_by:` block) — this is what makes the existing `CEL006` aggregate check fire for an aggregate used *inside* a group-by key, regardless of the fact that the projection legitimately has a `group by` clause for its other (computed) fields.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_cel_validation.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Lint and type-check**

```bash
uv run ruff format --check src/modelable/compiler/workspace.py tests/test_cel_validation.py
uv run ruff check src/modelable/compiler/workspace.py tests/test_cel_validation.py
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
```

- [ ] **Step 6: Commit**

```bash
git add src/modelable/compiler/workspace.py tests/test_cel_validation.py
git commit -m "fix(compiler): validate projection group-by expressions through CEL"
```

---

### Task 4: Require join predicates to be boolean

**Files:**
- Modify: `cli/src/modelable/compiler/workspace.py` (`_validate_cel`'s existing join loop, `workspace.py:308-331` before Tasks 2-3 shift the line numbers)
- Test: `cli/tests/test_cel_validation.py`

**Interfaces:**
- Consumes: `looks_boolean` (Task 1).
- Produces: `_validate_cel`'s error list now also flags a non-boolean join `.on` predicate.

The join loop already validates alias/field existence for `join.on` (it was already wired through `validate_cel_expr`) — this task only adds the same `looks_boolean` check Task 2 added for `where`. There is currently no end-to-end test proving `join.on` alias/field validation actually works through `load_workspace` at all (the research found none), so this task also adds that missing coverage alongside the new boolean check.

- [ ] **Step 1: Write the failing tests**

Add to `cli/tests/test_cel_validation.py`:

```python
def test_workspace_rejects_unknown_field_in_join_predicate():
    import tempfile
    import textwrap
    from pathlib import Path

    from modelable.compiler.workspace import load_workspace

    mdl_text = textwrap.dedent("""\
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
          projection BadProj @ 1
            from orders.Order @ 1 as o
            join customer.Customer @ 1 as c on o.customerId == c.nonExistentField
          {
            orderId <- o.orderId
          }
        }
    """)
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "test.mdl").write_text(mdl_text, encoding="utf-8")
        ws = load_workspace(tmp)
    assert any("CEL002" in diagnostic.message and "nonExistentField" in diagnostic.message for diagnostic in ws.errors)


def test_workspace_rejects_non_boolean_join_predicate():
    import tempfile
    import textwrap
    from pathlib import Path

    from modelable.compiler.workspace import load_workspace

    mdl_text = textwrap.dedent("""\
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
          projection BadProj @ 1
            from orders.Order @ 1 as o
            join customer.Customer @ 1 as c on lower(c.customerId)
          {
            orderId <- o.orderId
          }
        }
    """)
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "test.mdl").write_text(mdl_text, encoding="utf-8")
        ws = load_workspace(tmp)
    assert any("CEL008" in diagnostic.message for diagnostic in ws.errors)


def test_workspace_accepts_valid_join_predicate():
    import tempfile
    import textwrap
    from pathlib import Path

    from modelable.compiler.workspace import load_workspace

    mdl_text = textwrap.dedent("""\
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
          projection GoodProj @ 1
            from orders.Order @ 1 as o
            join customer.Customer @ 1 as c on o.customerId == c.customerId
          {
            orderId <- o.orderId
          }
        }
    """)
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "test.mdl").write_text(mdl_text, encoding="utf-8")
        ws = load_workspace(tmp)
    cel_errors = [d.message for d in ws.errors if "CEL" in d.code]
    assert cel_errors == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_cel_validation.py -k join_predicate -v`
Expected: `test_workspace_rejects_unknown_field_in_join_predicate` PASSES already (alias/field validation for joins already exists — this confirms the plan's claim and gives this test's "RED" role to the *coverage gap*, not a code bug: it's a genuinely new regression test for already-correct behavior, not a bug fix). `test_workspace_rejects_non_boolean_join_predicate` FAILS (no boolean check exists yet for joins).

- [ ] **Step 3: Write the minimal implementation**

In `cli/src/modelable/compiler/workspace.py`, in the existing join loop (originally `workspace.py:308-331`, now shifted later in the file by Tasks 2-3's insertions), add the boolean check after the existing `result.errors` loop:

```python
                for join in pv.joins:
                    if not join.on:
                        continue
                    ast, parse_errors = parse_cel(join.on)
                    for err in parse_errors:
                        errors.append(
                            Diagnostic(
                                code="CEL",
                                message=f"{fqn} join on: {err}",
                                severity="error",
                                path="<workspace>",
                            )
                        )
                    if ast is not None:
                        result = validate_cel_expr(ast, ctx)
                        for err in result.errors:
                            errors.append(
                                Diagnostic(
                                    code="CEL",
                                    message=f"{fqn} join on: {err}",
                                    severity="error",
                                    path="<workspace>",
                                )
                            )
                        if not looks_boolean(ast):
                            errors.append(
                                Diagnostic(
                                    code="CEL",
                                    message=f"{fqn} join on: CEL008: expression must be a boolean predicate",
                                    severity="error",
                                    path="<workspace>",
                                )
                            )
```

(Everything above this block in the loop is unchanged from the current file — only the final `if not looks_boolean(ast):` block is new.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_cel_validation.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Lint and type-check**

```bash
uv run ruff format --check src/modelable/compiler/workspace.py tests/test_cel_validation.py
uv run ruff check src/modelable/compiler/workspace.py tests/test_cel_validation.py
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
```

- [ ] **Step 6: Commit**

```bash
git add src/modelable/compiler/workspace.py tests/test_cel_validation.py
git commit -m "fix(compiler): require join predicates to be boolean, add missing join CEL coverage"
```

---

### Task 5: Integration coverage — invalid computed expression and cross-position dependency extraction

**Files:**
- Test only: `cli/tests/test_cel_validation.py`

**Interfaces:**
- Consumes: `modelable.compiler.workspace.load_workspace` (existing), `modelable.dependency_graph.build_projection_dependencies` (Slice A2, already merged).
- Produces: no new production code — this task closes the remaining two items from A3's test list ("invalid computed expression" as a field-existence case distinct from the pre-existing unsupported-function case, and "dependency extraction from every expression position").

- [ ] **Step 1: Write the tests**

Add to `cli/tests/test_cel_validation.py`:

```python
def test_workspace_rejects_computed_field_referencing_unknown_field():
    import tempfile
    import textwrap
    from pathlib import Path

    from modelable.compiler.workspace import load_workspace

    mdl_text = textwrap.dedent("""\
        domain customer {
          owner: "test-team"
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            status: string
          }
        }
        domain billing {
          owner: "test-team"
          projection BadProj @ 1
            from customer.Customer @ 1 as c
          {
            isActive = c.nonExistentField == "active"
          }
        }
    """)
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "test.mdl").write_text(mdl_text, encoding="utf-8")
        ws = load_workspace(tmp)
    assert any("CEL002" in diagnostic.message and "nonExistentField" in diagnostic.message for diagnostic in ws.errors)


def test_valid_projection_with_every_expression_position_passes_validation_and_extracts_all_dependencies():
    import tempfile
    import textwrap
    from pathlib import Path

    from modelable.compiler.workspace import load_workspace
    from modelable.dependency_graph import build_projection_dependencies

    mdl_text = textwrap.dedent("""\
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
            region: string
          }
        }
        domain billing {
          owner: "test-team"
          projection FullCoverage @ 1
            from orders.Order @ 1 as o
            join customer.Customer @ 1 as c on o.customerId == c.customerId
            where c.status == "active"
            group by o.region
          {
            region <- o.region
            orderCount = count(o.orderId)
            isActive = c.status == "active"
          }
        }
    """)
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "test.mdl").write_text(mdl_text, encoding="utf-8")
        ws = load_workspace(tmp)

    cel_errors = [d.message for d in ws.errors if "CEL" in d.code]
    assert cel_errors == []

    domain = next(d for d in ws.mdl.domains if d.name == "billing")
    pv = domain.projections["FullCoverage"][0]
    deps = build_projection_dependencies(ws.mdl, "billing", "FullCoverage", pv)

    assert {dep.usage_kind for dep in deps} == {"direct", "computed", "join", "filter", "group"}
```

- [ ] **Step 2: Run the tests**

Run: `uv run pytest tests/test_cel_validation.py -v`
Expected: `test_workspace_rejects_computed_field_referencing_unknown_field` already passes (computed-field alias/field validation predates this plan) — this is a coverage addition, not a bug fix, same as the join alias/field test in Task 4. `test_valid_projection_with_every_expression_position_passes_validation_and_extracts_all_dependencies` should pass once Tasks 2-4 are done; if it fails, it means one of the earlier tasks has a defect — treat that as a real signal to go back and fix the relevant task, not to weaken this test.

- [ ] **Step 3: Run the full CEL/compiler regression suite**

Run: `uv run pytest tests/test_cel_validation.py tests/test_dependency_graph.py tests/test_workspace.py tests/test_language_workspace.py -v`
Expected: all PASS (confirms this plan's changes to `_validate_cel` didn't regress the compiler-workspace test suite, and that A2's dependency-graph tests are unaffected).

- [ ] **Step 4: Run the full CLI suite as a final safety net**

Run: `uv run pytest -q`
Expected: all PASS. (If the browser-wheel packaging test fails, it's unrelated to this plan — Task 1-4 only touch `compiler/workspace.py` and `expressions/cel.py`, both already-bundled browser-wheel trees, so no `INCLUDE_FILES` update should be needed this time. Investigate if it does fail.)

- [ ] **Step 5: Lint and type-check**

```bash
uv run ruff format --check tests/test_cel_validation.py
uv run ruff check tests/test_cel_validation.py
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
```

- [ ] **Step 6: Commit**

```bash
git add tests/test_cel_validation.py
git commit -m "test(cel): cover computed-field field validation and cross-position dependency extraction"
```

---

## Gaps the full-suite safety net actually caught

Running `uv run pytest -q` after Task 3 and again after Task 5 surfaced three real
issues no per-file test run would have found, since `samples/scenarios/**/*.mdl`
is exercised only by `tests/test_samples.py`'s repo-wide scan:

1. Real scenarios use SQL-style `group by cohortMonth` where `cohortMonth` is the
   projection's own computed field, not a source `alias.field` reference — Task 3's
   `_validate_cel` needed a bare-name-matches-own-field exception (implemented and
   tested as part of Task 5, since it was the integration/full-suite pass that
   caught it).
2. `samples/scenarios/03-order-saga-microservices/inventory.mdl` used
   `where oc.items.size() > 0` — method-call syntax the CEL subset never
   supported. Fixed by removing the clause (see commit), not by extending CEL.
3. `samples/scenarios/05-partner-marketplace-api/marketplace-api.mdl` used
   `where inv.quantityAvailable != inv.quantityAvailable_prev` — a `_prev`
   previous-value pseudo-field that was never a real, implemented construct.
   Fixed the same way.

Both (2) and (3) were silently accepted forever only because `where` clauses were
never validated at all — exactly the class of bug this plan exists to close.

## Explicitly deferred (not in this plan)

- `@pitCutoff`/`@latestBefore`/`AnnCustom.expression` annotation validation — see Global Constraints above.
- Full computed-field/where/group-by *type inference* (as opposed to the structural boolean-shape check this plan adds) — no existing facility to build on; real project-sized work for a future slice.
- `pv.where` is duplicated onto `SourceRef.where` by the transformer (`parser/transformer.py:623`) but appears otherwise unused; this plan validates `pv.where` only, consistent with how the rest of the compiler already reads it.
