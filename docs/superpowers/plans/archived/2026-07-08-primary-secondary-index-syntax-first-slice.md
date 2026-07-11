# Primary Key, Secondary Index, And Sort-Key Syntax First Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an `index <Model> @ <version> { primary ...; secondary ... }` declaration, bound to one model version, parallel in shape to `auto projections` — gap 7 of Scalable's feature-gaps request, the last of the seven concretely-scheduled gaps (gap 8 remains an open question with no accepted grammar).

**Architecture:** `index_decl` is a new domain-level declaration living beside `model_decl`/`auto_projections_decl` in `domain_item`, following the exact same "bound to one model version" shape `AutoProjectionDecl` already established (`model: str`, `version: int`, plus index-specific fields). See
[docs/superpowers/specs/2026-07-07-modelable-feature-gaps-response-design.md](../specs/2026-07-07-modelable-feature-gaps-response-design.md)
section 10 for the full design, including a correction found while planning this slice (see below).

**Tech Stack:** Python 3.14, Lark (Earley) grammar, Pydantic IR, pytest, ruff.

---

## Scope And Version Boundary

**Correction to the design doc, found during planning:** the design doc's
rationale for restating `primary` explicitly is "composite keys have an
explicit declared order." But `validation/semantic.py`'s existing
`_validate_models` already requires `entity`/`aggregate` model versions to
have **exactly one** `@key` field (`len(key_fields) != 1` is an error) —
composite `@key` sets aren't representable in the language today at all.
`primary`'s validation (set-equality against the model's `@key` field
names) is still real and worth keeping — it's forward-compatible if
composite keys are ever added, and it still catches a `primary` clause
that names the wrong field or a stale field after a rename — but in
practice every `primary` clause validated by this slice will be a
single-name list. The grammar still accepts a comma-separated list (no
reason to make it more restrictive than the design doc's own sketch), the
validation just won't currently exercise the multi-name case.

This first slice covers:

- Grammar/IR/validation for `index` declarations (`primary` and
  `secondary` blocks, `key`/`sort`/`unique`).
- `index_changed` visibility in `compat/diff.py`'s compatibility reports
  (not a compatibility *verdict* — see Task 3's scope note).
- Postgres `CREATE INDEX`/`CREATE UNIQUE INDEX` DDL generation in
  `sql.py`, attached to whichever projection's resolved table sources
  from the indexed model version.

Out of scope for this first slice:

- **ClickHouse index DDL.** ClickHouse's indexing model (data-skipping
  indexes, `ADD INDEX ... TYPE ...`) is structurally different from a
  B-tree secondary index and deserves its own design, not a mechanical
  port of the Postgres statement shape.
- **The protobuf/gRPC read-replica index model consuming `index_decl`
  directly.** The grpc emitter already reads `@key` fields directly for
  its existing index metadata (shipped separately, per
  `2026-07-04-scalable-protobuf-grpc-support-design.md`) — that's
  equivalent to `primary` in the only case the language currently
  supports (single-field keys), so there's no functional gap yet.
  Wiring `index_decl` in directly is a real follow-up once `grpc.py`'s
  existing index-metadata code is well understood, not a same-slice
  extension.
- **`validate-compat` CLI command / wire_compatible/read_compatible/
  requires_read_rebuild/requires_state_migration classification tiers.**
  None of that exists anywhere in the codebase today (`checker.py`'s
  `CompatibilityReport.status` is binary: `"breaking"` or `"compatible"`).
  This slice makes index changes **visible** in a compatibility report's
  `findings`/`changes` list (satisfying the literal "visible as a schema
  and rebuild event" requirement), but does not attempt to classify which
  specific index changes are wire-breaking vs. additive — that requires
  real analysis this slice doesn't have the evidence to assert
  confidently, so it isn't asserted.

## File Structure

- Modify `cli/src/modelable/grammar/modelable.lark`: add `index_decl`,
  `index_item`, `primary_index`, `secondary_index`,
  `secondary_index_item`, `sort_field`, `sort_dir` productions (reusing
  the existing `bool_literal` production for `unique:` — added in the
  semantic-type-alias slice, no new boolean-literal grammar needed this
  time).
- Modify `cli/src/modelable/parser/transformer.py`: transformer methods
  for the above; `domain_decl` dispatch gains an `"index"` tag.
- Modify `cli/src/modelable/parser/ir.py`: add `SortField`,
  `SecondaryIndexDecl`, `IndexDecl`; add `index_decls: list[IndexDecl]`
  to `DomainDef`.
- Modify `cli/src/modelable/validation/semantic.py`: new
  `_validate_index_decls` — model/version existence, entity/aggregate-only,
  `primary` set-equality against `@key` fields, secondary field-reference
  existence, duplicate secondary names, duplicate `index` blocks per
  model+version.
- Modify `cli/src/modelable/compat/diff.py`: new `compare_index_decls`
  function reusing the `FieldChange` dataclass with `kind="index_changed"`.
- Modify `cli/src/modelable/compat/checker.py`:
  `check_model_version_compatibility` looks up both versions' `IndexDecl`
  (if any) and folds `compare_index_decls`' output into `changes`.
- Modify `cli/src/modelable/emitters/sql.py`: Postgres-only `CREATE
  INDEX`/`CREATE UNIQUE INDEX` statements appended after `CREATE TABLE`
  when a projection's source model+version has a matching `index_decl`.
- Modify `docs/language-reference.md`, `docs/compiler-reference.md`,
  `ROADMAP.md`, `CHANGELOG.md`.
- Create/modify test files: `cli/tests/test_grammar.py`,
  `cli/tests/test_semantic.py`, `cli/tests/test_compat.py` (or wherever
  `compare_model_versions`/`check_model_version_compatibility` are
  already tested — check before assuming a new file is needed),
  `cli/tests/test_emit_sql.py`.

## Task 1: Grammar, Transformer, And IR

**Files:**
- Modify: `cli/src/modelable/grammar/modelable.lark`
- Modify: `cli/src/modelable/parser/transformer.py`
- Modify: `cli/src/modelable/parser/ir.py`
- Modify: `cli/tests/test_grammar.py`

- [ ] **Step 1: Write the failing parse and IR tests**

Append to `cli/tests/test_grammar.py`:

```python
def test_parse_index_decl():
    tree = parse_text("""
    domain platform {
      owner: "platform-team"
      entity Order @ 3 (additive) {
        @key   orderId:    uuid
               customerId: uuid
               status:     enum(pending, shipped, delivered)
               createdAt:  timestamp
      }

      index Order @ 3 {
        primary orderId

        secondary byCustomer {
          key:    [customerId]
          sort:   [createdAt desc]
          unique: false
        }

        secondary byStatus {
          key: [status, createdAt]
        }
      }
    }
    """)
    assert tree.data == "start"


def test_index_decl_ir_shape():
    ir = parse_text_to_ir("""
    domain platform {
      owner: "platform-team"
      entity Order @ 3 (additive) {
        @key   orderId:    uuid
               customerId: uuid
               status:     enum(pending, shipped, delivered)
               createdAt:  timestamp
      }

      index Order @ 3 {
        primary orderId

        secondary byCustomer {
          key:    [customerId]
          sort:   [createdAt desc]
          unique: false
        }

        secondary byStatus {
          key:    [status, createdAt]
          unique: true
        }
      }
    }
    """)
    decl = ir.domains[0].index_decls[0]
    assert decl.model == "Order"
    assert decl.version == 3
    assert decl.primary == ["orderId"]
    by_customer = next(s for s in decl.secondary if s.name == "byCustomer")
    assert by_customer.key == ["customerId"]
    assert by_customer.sort == [SortField(field="createdAt", direction="desc")]
    assert by_customer.unique is False
    by_status = next(s for s in decl.secondary if s.name == "byStatus")
    assert by_status.key == ["status", "createdAt"]
    assert by_status.sort == []
    assert by_status.unique is True
```

Add `SortField` to this test file's imports from `modelable.parser.ir`.

- [ ] **Step 2: Verify the tests fail**

Run from `cli/`: `uv run pytest tests/test_grammar.py -k index_decl -q`.
Expected: both fail — `index` isn't a recognized `domain_item` yet, and
`domain.index_decls` doesn't exist.

- [ ] **Step 3: Extend the grammar**

Add `index_decl` to `domain_item`, then add the new productions near
`auto_projections_decl`:

```
index_decl: "index" IDENT "@" INT "{" index_item* "}"
index_item: primary_index | secondary_index
primary_index: "primary" IDENT ("," IDENT)*
secondary_index: "secondary" IDENT "{" secondary_index_item* "}"
secondary_index_item: "key" ":" "[" IDENT ("," IDENT)* "]"
                    | "sort" ":" "[" sort_field ("," sort_field)* "]"
                    | "unique" ":" bool_literal
sort_field: IDENT sort_dir?
sort_dir: "asc"  -> sd_asc
        | "desc" -> sd_desc
```

`bool_literal` already exists (added for `semantic ... { registry: true
}`) — reuse it rather than inventing a second boolean-literal path.

- [ ] **Step 4: Add transformer methods**

```python
    def sd_asc(self, _items: list[object]) -> str:
        return "asc"

    def sd_desc(self, _items: list[object]) -> str:
        return "desc"

    def sort_dir(self, items: list[object]) -> str:
        return items[0]  # type: ignore[return-value]

    def sort_field(self, items: list[object]) -> SortField:
        direction = items[1] if len(items) > 1 else "asc"
        return SortField(field=str(items[0]), direction=direction)  # type: ignore[arg-type]

    def primary_index(self, items: list[object]) -> tuple[str, list[str]]:
        return ("primary", [str(item) for item in items])

    def secondary_index_item(self, items: list[object]) -> tuple[str, object]:
        # Grammar alternatives distinguish by shape: a list of plain
        # strings is `key`, a list of SortField is `sort`, a bare bool is
        # `unique`. Disambiguate on the parsed Python type, matching how
        # semantic_body already distinguishes its one item kind today —
        # this rule has three, so check SortField before falling back to
        # the plain-list/bool cases.
        value = items[0]
        if isinstance(value, bool):
            return ("unique", value)
        if isinstance(value, list) and value and isinstance(value[0], SortField):
            return ("sort", value)
        return ("key", [str(v) for v in value])  # type: ignore[union-attr]

    def secondary_index(self, items: list[object]) -> SecondaryIndexDecl:
        name = str(items[0])
        parts = dict(item for item in items[1:] if isinstance(item, tuple))
        return SecondaryIndexDecl(
            name=name,
            key=parts.get("key", []),
            sort=parts.get("sort", []),
            unique=parts.get("unique", False),
        )

    def index_item(self, items: list[object]) -> object:
        return items[0]

    def index_decl(self, items: list[object]) -> tuple[str, IndexDecl]:
        model = str(items[0])
        version = int(items[1])
        primary: list[str] = []
        secondary: list[SecondaryIndexDecl] = []
        for item in items[2:]:
            if isinstance(item, tuple) and item[0] == "primary":
                primary = item[1]
            elif isinstance(item, SecondaryIndexDecl):
                secondary.append(item)
        return (
            "index",
            IndexDecl(model=model, version=version, primary=primary, secondary=secondary),
        )
```

Double-check the actual shape of `secondary_index_item`'s parsed `items`
against a real parse tree before trusting the disambiguation logic above
verbatim — Lark's Earley parser may hand back the inner list/bool
differently than sketched here (e.g. wrapped vs. unwrapped) depending on
how `"[" IDENT ("," IDENT)* "]"` transforms without an explicit rule name
of its own. If `key`'s `"[" IDENT ("," IDENT)* "]"` and `sort`'s `"["
sort_field ("," sort_field)* "]"` need their own named rules to
disambiguate reliably (e.g. `key_list` / `sort_list` productions each
with their own transformer method returning a tagged tuple, mirroring
how `semantic_item` tags its one value), prefer that over shape-sniffing
— it's more robust and matches this file's existing tagged-tuple
dispatch convention better than type inspection would.

Add `SortField`, `SecondaryIndexDecl`, `IndexDecl` to the
`modelable.parser.ir` import list. Wire `"index"` into `domain_decl`'s
dispatch loop:

```python
        index_decls: list[IndexDecl] = []
        ...
            elif tag == "index":
                index_decls.append(value)
        ...
        return DomainDef(
            ...
            index_decls=index_decls,
        )
```

- [ ] **Step 5: Add the IR nodes**

In `parser/ir.py`, add near `AutoProjectionDecl`:

```python
class SortField(BaseModel):
    field: str
    direction: Literal["asc", "desc"] = "asc"


class SecondaryIndexDecl(BaseModel):
    name: str
    key: list[str] = Field(default_factory=list)
    sort: list[SortField] = Field(default_factory=list)
    unique: bool = False


class IndexDecl(BaseModel):
    model: str
    version: int
    primary: list[str] = Field(default_factory=list)
    secondary: list[SecondaryIndexDecl] = Field(default_factory=list)
```

Add `index_decls: list[IndexDecl] = Field(default_factory=list)` to
`DomainDef`.

- [ ] **Step 6: Verify the tests pass**

Run from `cli/`: `uv run pytest tests/test_grammar.py -k index_decl -q`,
then the full file: `uv run pytest tests/test_grammar.py -q`.

## Task 2: Validation

**Files:**
- Modify: `cli/src/modelable/validation/semantic.py`
- Modify: `cli/tests/test_semantic.py`

- [ ] **Step 1: Write the failing validation tests**

Append to `cli/tests/test_semantic.py` (base every fixture on an
`entity`/`aggregate` with exactly one `@key` field, matching the
single-key constraint documented in this plan's Scope section):

```python
def test_index_decl_primary_must_match_key_field():
    mdl = parse_text_to_ir("""
    domain platform {
      owner: "test-team"
      entity Order @ 1 (additive) {
        @key orderId: uuid
             status:  string
      }
      index Order @ 1 {
        primary status
      }
    }
    """)
    errors = validate(mdl)
    assert any("Order" in e and "primary" in e.lower() for e in errors)


def test_index_decl_valid_primary_and_secondary_is_valid():
    mdl = parse_text_to_ir("""
    domain platform {
      owner: "test-team"
      entity Order @ 1 (additive) {
        @key orderId: uuid
             status:  string
      }
      index Order @ 1 {
        primary orderId
        secondary byStatus {
          key: [status]
        }
      }
    }
    """)
    assert validate(mdl) == []


def test_index_decl_secondary_field_reference_must_exist():
    mdl = parse_text_to_ir("""
    domain platform {
      owner: "test-team"
      entity Order @ 1 (additive) {
        @key orderId: uuid
      }
      index Order @ 1 {
        primary orderId
        secondary byMissing {
          key: [doesNotExist]
        }
      }
    }
    """)
    errors = validate(mdl)
    assert any("doesNotExist" in e for e in errors)


def test_index_decl_duplicate_secondary_name_is_error():
    mdl = parse_text_to_ir("""
    domain platform {
      owner: "test-team"
      entity Order @ 1 (additive) {
        @key orderId: uuid
             status:  string
      }
      index Order @ 1 {
        primary orderId
        secondary byStatus {
          key: [status]
        }
        secondary byStatus {
          key: [status]
        }
      }
    }
    """)
    errors = validate(mdl)
    assert any("byStatus" in e for e in errors)


def test_index_decl_referencing_unknown_model_is_error():
    mdl = parse_text_to_ir("""
    domain platform {
      owner: "test-team"
      index DoesNotExist @ 1 {
        primary id
      }
    }
    """)
    errors = validate(mdl)
    assert any("DoesNotExist" in e for e in errors)


def test_index_decl_on_value_model_is_error():
    mdl = parse_text_to_ir("""
    domain platform {
      owner: "test-team"
      value Money @ 1 (additive) {
        amount: decimal(10, 2)
      }
      index Money @ 1 {
        primary amount
      }
    }
    """)
    errors = validate(mdl)
    assert any("Money" in e for e in errors)
```

- [ ] **Step 2: Verify the tests fail**

Run from `cli/`: `uv run pytest tests/test_semantic.py -k index_decl -q`.
Expected: every case passes validation silently today (no `index_decls`
validation exists yet), so all six assertions fail.

- [ ] **Step 3: Add the validation pass**

Add `_validate_index_decls(domain, diagnostics, path)` to
`validate_diagnostics`'s per-domain loop, alongside
`_validate_semantic_types`. Logic:

1. Model/version existence: look up `domain.models.get(decl.model)`, then
   the specific version; error if either is missing (message style
   matching `expand_auto_projections`'s existing
   `"references unknown model"` / `"which does not exist"` wording for
   consistency).
2. Model-kind check: the resolved model version's `model_kind` must be
   `entity` or `aggregate` (same restriction `auto projections` already
   documents for itself) — error naming the actual kind otherwise.
3. `primary` set-equality: `set(decl.primary) == {f.name for f in
   model_version.fields if f.is_key}` — error listing both sides if they
   differ (covers a typo'd field name and covers the always-true-today
   single-key case).
4. Secondary field references: every name in `sort.key` and every
   `SortField.field` in `secondary.sort` must be a real field name on
   that model version — error naming the missing field.
5. Duplicate secondary names within one `index` block — error.
6. Duplicate `index` blocks for the same `(model, version)` pair across
   `domain.index_decls` — error (mirrors treating this like a
   one-declaration-per-model-version concept, consistent with
   `auto_projections`' implicit one-per-kind-per-version shape).

Follow this file's existing `_diag("SEM", f"...", path)` pattern and
message style throughout.

- [ ] **Step 4: Verify the tests pass**

Run from `cli/`: `uv run pytest tests/test_semantic.py -k index_decl -q`,
then the full file: `uv run pytest tests/test_semantic.py -q`.

## Task 3: Compatibility Visibility

**Files:**
- Modify: `cli/src/modelable/compat/diff.py`
- Modify: `cli/src/modelable/compat/checker.py`
- Modify: whichever test file already covers `check_model_version_compatibility`
  (search for it before creating a new file)

- [ ] **Step 1: Find the existing compat test file and write failing tests**

`rg -l "check_model_version_compatibility\|compare_model_versions" cli/tests/`
to find the right file. Add tests there:

```python
def test_index_changed_is_visible_when_secondary_index_added():
    mdl = parse_text_to_ir("""
    domain platform {
      owner: "test-team"
      entity Order @ 1 (additive) {
        @key orderId: uuid
             status:  string
      }
      entity Order @ 2 (additive) {
        @key orderId: uuid
             status:  string
      }
      index Order @ 2 {
        primary orderId
        secondary byStatus {
          key: [status]
        }
      }
    }
    """)
    report = check_model_version_compatibility(mdl, "platform", "Order", 1, 2)
    assert any(change.kind == "index_changed" for change in report.changes)


def test_index_changed_is_not_flagged_when_neither_version_has_one():
    mdl = parse_text_to_ir("""
    domain platform {
      owner: "test-team"
      entity Order @ 1 (additive) {
        @key orderId: uuid
      }
      entity Order @ 2 (additive) {
        @key orderId: uuid
             status:  string
      }
    }
    """)
    report = check_model_version_compatibility(mdl, "platform", "Order", 1, 2)
    assert not any(change.kind == "index_changed" for change in report.changes)
```

- [ ] **Step 2: Verify the tests fail**

Expected: the first fails (no `index_changed` kind exists at all yet in
`compat/diff.py`), the second passes trivially (nothing to flag today
either way) — keep it anyway as a regression guard once the feature
exists, to pin "no index declared on either side" as a deliberate
no-op, not an oversight.

- [ ] **Step 3: Add `compare_index_decls` to `compat/diff.py`**

```python
def compare_index_decls(old_index: IndexDecl | None, new_index: IndexDecl | None) -> list[FieldChange]:
    """Surface index structure changes between two model versions.

    Does not classify whether a given change is wire-breaking — no
    `validate-compat` classification tiers exist in this codebase yet.
    This only makes index changes visible in a compatibility report's
    findings, per the source requirement.
    """
    if old_index is None and new_index is None:
        return []
    changes: list[FieldChange] = []
    old_primary = old_index.primary if old_index else []
    new_primary = new_index.primary if new_index else []
    if old_primary != new_primary:
        changes.append(FieldChange(kind="index_changed", field_name="primary"))

    old_secondary = {s.name: s for s in (old_index.secondary if old_index else [])}
    new_secondary = {s.name: s for s in (new_index.secondary if new_index else [])}
    for name in sorted(set(old_secondary) | set(new_secondary)):
        if old_secondary.get(name) != new_secondary.get(name):
            changes.append(FieldChange(kind="index_changed", field_name=name))
    return changes
```

Add `IndexDecl` to this file's `modelable.parser.ir` import list.

- [ ] **Step 4: Wire it into `check_model_version_compatibility`**

In `checker.py`, after `changes = compare_model_versions(old_version,
new_version)`, look up both versions' `IndexDecl` (search
`mdl.domains[...].index_decls` for `model == model_name and version ==
from_version` / `to_version`) and extend `changes` with
`compare_index_decls(old_index, new_index)`. Do **not** add
`"index_changed"` to `_has_breaking_change`'s kind set — per this slice's
scope, visibility only, no verdict.

- [ ] **Step 5: Verify the tests pass**

Run the compat test file, then the full suite once (`checker.py` is a
shared, high-traffic module — cheap insurance against an unexpected
interaction): `uv run pytest --tb=short -q` from `cli/`.

## Task 4: SQL Postgres Index DDL

**Files:**
- Modify: `cli/src/modelable/emitters/sql.py`
- Modify: `cli/tests/test_emit_sql.py`

- [ ] **Step 1: Write the failing tests**

Append to `cli/tests/test_emit_sql.py` (check existing imports/fixtures
first):

```python
def test_postgres_ddl_includes_secondary_index(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text(
        """
domain platform {
  owner: "test-team"

  entity Order @ 1 (additive) {
    @key orderId:    uuid
         customerId: uuid
         createdAt:  timestamp
  }

  index Order @ 1 {
    primary orderId
    secondary byCustomer {
      key:    [customerId]
      sort:   [createdAt desc]
      unique: false
    }
  }

  auto projections Order @ 1 {
    db
  }

  binding orderTable {
    model: platform.Order @ 1
    adapter: postgres
    table: orders
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_sql(workspace, tmp_path / "out", "postgres")
    art = next(a for a in artifacts if a.ref == "platform.OrderDb@1")
    assert "CREATE INDEX IF NOT EXISTS by_customer ON orders (customer_id);" in art.content


def test_postgres_ddl_unique_secondary_index_uses_unique_keyword(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text(
        """
domain platform {
  owner: "test-team"

  entity Order @ 1 (additive) {
    @key orderId: uuid
         email:   string
  }

  index Order @ 1 {
    primary orderId
    secondary byEmail {
      key:    [email]
      unique: true
    }
  }

  auto projections Order @ 1 {
    db
  }

  binding orderTable {
    model: platform.Order @ 1
    adapter: postgres
    table: orders
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_sql(workspace, tmp_path / "out", "postgres")
    art = next(a for a in artifacts if a.ref == "platform.OrderDb@1")
    assert "CREATE UNIQUE INDEX IF NOT EXISTS by_email ON orders (email);" in art.content
```

Check the actual `binding` declaration grammar (name/model/adapter/table
keywords and syntax) against an existing passing test in this file before
trusting the sketch above verbatim — copy a real working binding block
from an existing test rather than guessing its exact shape.

- [ ] **Step 2: Verify the tests fail**

Run from `cli/`: `uv run pytest tests/test_emit_sql.py -k secondary_index -q`.
Expected: no `CREATE INDEX` text exists anywhere in `sql.py`'s output
today.

- [ ] **Step 3: Add index DDL emission**

In `_emit_projection_ddl` (Postgres branch only), after building the
`CREATE TABLE` statement: find the `IndexDecl` (if any) whose `(model,
version)` matches `version.source.model`/`version.source.version`
(source model is a fully-qualified `domain.Model` string — split and
compare against `f"{domain.name}.{decl.model}"`). For each
`SecondaryIndexDecl`, resolve every referenced source-model field name to
its column name in *this projection*: search `version.fields` for a
`DirectMapping` whose `source_field` matches, and use that projection
field's own `_snake_case(name)` — if no such projection field exists
(the indexed field wasn't projected), skip that index and append a
`type_loss`-style warning naming the missing field rather than emitting
broken SQL referencing a nonexistent column. Render:

```sql
CREATE [UNIQUE] INDEX IF NOT EXISTS <snake_case(secondary.name)> ON <table_name> (<col1>[, <col2>...]);
```

`sort`'s direction (`asc`/`desc`) only matters if you choose to also
encode `ORDER BY`-equivalent column direction in the index expression
(Postgres supports `col DESC` inside `CREATE INDEX ... (col1, col2
DESC)`) — include it if straightforward, but don't let getting sort
direction exactly right block shipping the simpler, definitely-correct
`key`-only column list; note in the doc if direction ends up unsupported
in this first slice.

Skip entirely for the ClickHouse branch (`dialect != "postgres"`), per
Scope.

- [ ] **Step 4: Verify the tests pass**

Run from `cli/`: `uv run pytest tests/test_emit_sql.py -k secondary_index -q`,
then the full file: `uv run pytest tests/test_emit_sql.py -q`.

## Task 5: Documentation

**Files:**
- Modify: `docs/language-reference.md`, `docs/compiler-reference.md`,
  `ROADMAP.md`, `CHANGELOG.md`

- [ ] **Step 1: Add a language reference section**

New subsection near `auto projections` (§3.7/§3.8) covering `index`
syntax, the `primary`-must-match-`@key` constraint (and the current
single-`@key`-field reality this constraint operates under — don't
imply composite keys work today), `secondary` blocks, and that
`unique`/`sort` are optional with documented defaults.

- [ ] **Step 2: Update the compiler reference**

Document the Postgres `CREATE INDEX`/`CREATE UNIQUE INDEX` emission and
its field-resolution-through-projection-mapping behavior (including the
skip-with-warning case for an unprojected indexed field). Note ClickHouse
is out of scope for this slice.

- [ ] **Step 3: Update ROADMAP and CHANGELOG**

Mark gap 7 shipped, following the established wording style, explicitly
noting: the single-`@key`-field correction, the visibility-not-verdict
scope of `index_changed`, and the two deferred items (ClickHouse DDL,
`grpc.py` consumption).

- [ ] **Step 4: Verify docs mention the new declaration**

Run from repo root:
`rg -n "index <Model>|index Order|IndexDecl" docs/language-reference.md docs/compiler-reference.md CHANGELOG.md ROADMAP.md`.

## Task 6: Final Verification

- [ ] **Step 1: Run all focused tests**

```bash
uv run pytest tests/test_grammar.py tests/test_semantic.py tests/test_emit_sql.py --tb=short -q
uv run pytest -k "index_changed" --tb=short -q
```

- [ ] **Step 2: Run the full suite, ruff, and the mypy baseline ratchet**

```bash
uv run ruff format --check .
uv run ruff check .
uv run pytest --tb=short
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
```

Regenerate `mypy-baseline.txt` from a fresh `uv run mypy ...` run taken
**after** `ruff format`'s final pass, per the now-established lesson from
every prior slice.

- [ ] **Step 3: Inspect the final diff**

```bash
git diff --stat
```

Expected: diff touches the grammar, transformer, IR, validator,
`compat/diff.py`, `compat/checker.py`, `sql.py`, their tests, the four
documentation files, and the mypy baseline.

## Self-Review

Spec coverage:

- Covered: `index` declaration parses; `IndexDecl`/`SecondaryIndexDecl`/
  `SortField` IR; model/version-existence, entity/aggregate-only,
  `primary`-matches-`@key`, secondary-field-reference, duplicate-name
  validation; `index_changed` visibility in compatibility reports;
  Postgres `CREATE INDEX`/`CREATE UNIQUE INDEX` DDL.
- Deferred by design (see Scope section): ClickHouse index DDL, `grpc.py`
  direct consumption of `index_decl`, `validate-compat` classification
  tiers / breaking-vs-additive verdicts for index changes.

Placeholder scan: none — every task ends with a green-test checkpoint.

Type consistency: three new Pydantic models
(`SortField`/`SecondaryIndexDecl`/`IndexDecl`), structurally parallel to
`AutoProjectionTarget`/`AutoProjectionDecl`; `FieldChange` (a
`@dataclass`, not a Pydantic model) gains a new `kind` string value
(`"index_changed"`) rather than a new field — matches how
`"renamed_field"`/`"type_changed"`/etc. are already just string tags on
the same dataclass shape, no schema change needed.
