# Semantic-Type / Type-Alias Mechanism First Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `semantic <Name> : <underlying-type> { registry: bool }` declaration that names a scoped nominal wrapper over a primitive, `decimal(p,s)`, `binary(N)`, or another `semantic` type, and generate a Rust newtype for it — the first implementation slice of Modelable 1.3.

**Architecture:** This is structurally different from the two previous 1.2 slices (which extended the existing primitive-mapping-dict pattern). `semantic` is a new **domain-level declaration**, not a new field type shape — it lives beside `model_decl`/`projection_decl` inside `domain_item`, not inside `type_expr`. Field references to a semantic type reuse the existing, already-working bare-`IDENT` → `NamedType` → flat-workspace-search path with zero grammar changes on the reference side; all new grammar is on the declaration side. See
[docs/superpowers/specs/2026-07-07-modelable-feature-gaps-response-design.md](../specs/2026-07-07-modelable-feature-gaps-response-design.md)
section 6 for the full design, including three corrections made to the original text while researching this plan (no domain-scoped or dotted resolution exists to reuse; no `BOOL` terminal exists; no cycle-detection pass exists to reuse).

**Tech Stack:** Python 3.14, Lark (Earley) grammar, Pydantic IR, pytest, ruff.

---

## Scope And Version Boundary

This is Modelable 1.3 work, following the two 1.2 slices (fixed-width
integers, fixed-length binary — both shipped). Per the response design
doc, this first slice is **Rust-only** for code generation — every other
target's `semantic` handling (Go, Java, C#, Python, TypeScript newtypes;
`x-modelable-semantic-type` vendor metadata for structural targets) is
explicitly deferred to follow-up slices, matching the design doc's own
stated scope (unlike the two 1.2 slices, which covered every implemented
target from the start).

Out of scope for this first slice:

- Every non-Rust emitter mapping listed in the design doc as "follow-up."
- CEL nominal-typing validation (comparing/assigning across distinct
  semantic types in expressions) — explicitly deferred in the design doc.
- Dotted (`Domain.Name`) semantic-type references — no such mechanism
  exists for any `NamedType` reference today; see the design doc
  correction.
- Anything acting on `registry: true` — gap 4 (registry ID allocation,
  Modelable 1.4) is what consumes that flag; this slice only stores it.
- Deleting the handwritten Rust adapter layer in Scalable's own repo —
  that's Scalable's follow-up once this ships, not part of this PR.

## File Structure

- Modify `cli/src/modelable/grammar/modelable.lark`: add `semantic_decl`,
  `semantic_body`, `semantic_item`, `bool_literal` productions; add
  `semantic_decl` to `domain_item`.
- Modify `cli/src/modelable/parser/transformer.py`: add transformer
  methods for the above, plus `domain_decl`'s dispatch loop gains a
  `"semantic"` tag.
- Modify `cli/src/modelable/parser/ir.py`: add `SemanticTypeDecl`; add
  `semantic_types: list[SemanticTypeDecl]` to `DomainDef`.
- Modify `cli/src/modelable/validation/semantic.py`: underlying-type-kind
  check, dangling-reference check, chain-depth/cycle check, duplicate-name
  check (within a domain, and against model names).
- Modify `cli/src/modelable/emitters/rust.py`: emit one newtype file per
  `semantic` declaration; extend `_resolve_named_type_map` (or its
  equivalent call site) to recognize semantic-type names.
- Modify `docs/language-reference.md`, `docs/compiler-reference.md`,
  `ROADMAP.md`, `CHANGELOG.md`.
- Create/modify test files: `cli/tests/test_grammar.py`,
  `cli/tests/test_semantic.py`, `cli/tests/test_emit_rust.py`.

## Task 1: Grammar, Transformer, And IR

**Files:**
- Modify: `cli/src/modelable/grammar/modelable.lark`
- Modify: `cli/src/modelable/parser/transformer.py`
- Modify: `cli/src/modelable/parser/ir.py`
- Modify: `cli/tests/test_grammar.py`

- [ ] **Step 1: Write the failing parse and IR tests**

Append to `cli/tests/test_grammar.py`:

```python
def test_parse_semantic_type_decl():
    tree = parse_text("""
    domain platform {
      owner: "platform-team"

      semantic ModuleId : u32 {
        registry: true
      }

      semantic Identity128 : u128

      entity Schema @ 1 (additive) {
        @key moduleId: ModuleId
      }
    }
    """)
    assert tree.data == "start"


def test_semantic_type_decl_ir_shape():
    ir = parse_text_to_ir("""
    domain platform {
      owner: "platform-team"

      semantic ModuleId : u32 {
        registry: true
      }

      semantic Identity128 : u128
    }
    """)
    domain = ir.domains[0]
    by_name = {s.name: s for s in domain.semantic_types}
    assert by_name["ModuleId"].underlying.kind == "u32"
    assert by_name["ModuleId"].registry is True
    assert by_name["Identity128"].underlying.kind == "u128"
    assert by_name["Identity128"].registry is False


def test_field_referencing_semantic_type_is_named_type():
    ir = parse_text_to_ir("""
    domain platform {
      owner: "platform-team"

      semantic ModuleId : u32

      entity Schema @ 1 (additive) {
        @key moduleId: ModuleId
      }
    }
    """)
    field = ir.domains[0].models["Schema"][0].fields[0]
    assert field.type.kind == "named"
    assert field.type.name == "ModuleId"
```

- [ ] **Step 2: Verify the tests fail**

Run from `cli/`: `uv run pytest tests/test_grammar.py -k semantic_type -q`.
Expected: `test_parse_semantic_type_decl` fails to parse (`semantic` isn't
a recognized `domain_item`); the other two fail with `AttributeError` on
`domain.semantic_types` not existing. `test_field_referencing_semantic_type_is_named_type`
should actually already pass on its own — bare `IDENT` field types
already become `NamedType` today with zero changes; keep it in this task
as a regression guard on that existing behavior, not a new one.

- [ ] **Step 3: Extend the grammar**

In `modelable.lark`, add to `domain_item`:

```
domain_item: owner_attr
           | contact_attr
           | desc_attr
           | model_decl
           | projection_decl
           | auto_projections_decl
           | generate_block
           | semantic_decl
```

Add new productions (near `auto_projections_decl`):

```
semantic_decl: "semantic" IDENT ":" type_expr semantic_body?
semantic_body: "{" semantic_item* "}"
semantic_item: "registry" ":" bool_literal
bool_literal: "true"  -> bl_true
            | "false" -> bl_false
```

- [ ] **Step 4: Add transformer methods**

In `transformer.py`:

```python
    def bl_true(self, _items: list[object]) -> bool:
        return True

    def bl_false(self, _items: list[object]) -> bool:
        return False

    def bool_literal(self, items: list[object]) -> bool:
        return items[0]

    def semantic_item(self, items: list[object]) -> tuple[str, bool]:
        return ("registry", items[0])

    def semantic_body(self, items: list[object]) -> dict[str, bool]:
        return dict(items)

    def semantic_decl(self, items: list[object]) -> tuple[str, SemanticTypeDecl]:
        name = str(items[0])
        underlying = items[1]
        body = items[2] if len(items) > 2 and isinstance(items[2], dict) else {}
        return ("semantic", SemanticTypeDecl(
            name=name,
            underlying=underlying,
            registry=body.get("registry", False),
        ))
```

Add `SemanticTypeDecl` to the `modelable.parser.ir` import list. Wire the
new tag into `domain_decl`'s dispatch loop (alongside the existing
`"model"`/`"projection"`/`"auto_projection"`/`"generate"` branches):

```python
        semantic_types: list[SemanticTypeDecl] = []
        ...
            elif tag == "semantic":
                semantic_types.append(value)
        ...
        return DomainDef(
            ...
            semantic_types=semantic_types,
        )
```

- [ ] **Step 5: Add the IR node**

In `parser/ir.py`, add near `AutoProjectionDecl`:

```python
class SemanticTypeDecl(BaseModel):
    name: str
    underlying: FieldType
    registry: bool = False
```

Add `semantic_types: list[SemanticTypeDecl] = Field(default_factory=list)`
to `DomainDef`.

- [ ] **Step 6: Verify the tests pass**

Run from `cli/`: `uv run pytest tests/test_grammar.py -k semantic_type -q`,
then the full file: `uv run pytest tests/test_grammar.py -q`.

## Task 2: Validation

**Files:**
- Modify: `cli/src/modelable/validation/semantic.py`
- Modify: `cli/tests/test_semantic.py`

- [ ] **Step 1: Write the failing validation tests**

Append to `cli/tests/test_semantic.py`:

```python
def test_semantic_type_rejects_array_underlying():
    mdl = parse_text_to_ir("""
    domain platform {
      owner: "test-team"
      semantic Bad : array<string>
    }
    """)
    errors = validate(mdl)
    assert any("Bad" in e for e in errors)


def test_semantic_type_chained_underlying_is_valid():
    mdl = parse_text_to_ir("""
    domain platform {
      owner: "test-team"
      semantic Base : u32
      semantic Wrapped : Base
    }
    """)
    assert validate(mdl) == []


def test_semantic_type_dangling_underlying_reference_is_error():
    mdl = parse_text_to_ir("""
    domain platform {
      owner: "test-team"
      semantic Wrapped : DoesNotExist
    }
    """)
    errors = validate(mdl)
    assert any("Wrapped" in e and "DoesNotExist" in e for e in errors)


def test_semantic_type_cycle_is_error():
    mdl = parse_text_to_ir("""
    domain platform {
      owner: "test-team"
      semantic A : B
      semantic B : A
    }
    """)
    errors = validate(mdl)
    assert any("cycle" in e.lower() for e in errors)


def test_semantic_type_duplicate_name_in_domain_is_error():
    mdl = parse_text_to_ir("""
    domain platform {
      owner: "test-team"
      semantic ModuleId : u32
      semantic ModuleId : u64
    }
    """)
    errors = validate(mdl)
    assert any("ModuleId" in e for e in errors)


def test_semantic_type_name_colliding_with_model_is_error():
    mdl = parse_text_to_ir("""
    domain platform {
      owner: "test-team"
      semantic Schema : u32
      entity Schema @ 1 (additive) {
        @key id: uuid
      }
    }
    """)
    errors = validate(mdl)
    assert any("Schema" in e for e in errors)
```

- [ ] **Step 2: Verify the tests fail**

Run from `cli/`: `uv run pytest tests/test_semantic.py -k semantic_type -q`.
Expected: all fail — no validation exists yet, so every case (including
the ones that should be errors) currently passes validation silently.

- [ ] **Step 3: Add the validation pass**

In `validation/semantic.py`, add a new top-level function
`_validate_semantic_types(domain_name, domain, all_domains, diagnostics, path)`
called once per domain from `validate_diagnostics` (alongside the existing
`_validate_models`/`_validate_projections` calls — this needs the full
`MdlFile.domains` list, not just one domain, to check the workspace-wide
flat-search collision/resolution rules described in the design doc).

Logic:

1. Duplicate names within the domain: group `domain.semantic_types` by
   `.name`; any name with more than one declaration is an error.
2. Model-name collision: any `semantic_types` name that also appears in
   `domain.models` is an error.
3. Underlying-kind check: for each declaration, `underlying` must be
   `PrimitiveType`, `DecimalType`, `FixedBinaryType`, or `NamedType`.
   Anything else (`ArrayType`, `MapType`, `RefType`, `EnumType`,
   `ObjectType`) is an error naming the declaration and the rejected kind.
4. Chain resolution: build a `name -> SemanticTypeDecl` map across *all*
   domains (matching the flat-search precedent). For each declaration
   whose `underlying` is a `NamedType`, walk the chain: if the referenced
   name isn't in the map, that's a dangling-reference error; otherwise
   continue to that declaration's own `underlying`. Track visited names
   in the current walk — revisiting one is a cycle error naming the
   cycle. Cap the walk at 32 steps as a depth-bound safety net independent
   of the cycle check.

Follow this file's existing `_diag("SEM", f"...", path)` pattern and
message style throughout (check how `_validate_default_value_range` and
`_validate_fixed_binary_length`, both added by the previous two slices,
are worded and structured before adding new messages, for consistency).

- [ ] **Step 4: Verify the tests pass**

Run from `cli/`: `uv run pytest tests/test_semantic.py -k semantic_type -q`,
then the full file: `uv run pytest tests/test_semantic.py -q`.

## Task 3: Rust Emitter

**Files:**
- Modify: `cli/src/modelable/emitters/rust.py`
- Modify: `cli/tests/test_emit_rust.py`

- [ ] **Step 1: Write the failing tests**

Append to `cli/tests/test_emit_rust.py`:

```python
def test_emit_rust_semantic_type_newtype(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text(
        """
domain platform {
  owner: "test-team"

  semantic ModuleId : u32
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_rust(workspace, tmp_path / "out")
    art = next(a for a in artifacts if a.ref == "platform.ModuleId")
    assert art.path == tmp_path / "out" / "platform" / "module_id.rs"
    assert "pub struct ModuleId(pub u32);" in art.content
    assert "impl From<u32> for ModuleId" in art.content
    assert "impl From<ModuleId> for u32" in art.content
    assert "impl std::ops::Deref for ModuleId" in art.content
    assert "type Target = u32;" in art.content


def test_emit_rust_field_referencing_semantic_type_uses_newtype(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text(
        """
domain platform {
  owner: "test-team"

  semantic ModuleId : u32

  entity Schema @ 1 (additive) {
    @key moduleId: ModuleId
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_rust(workspace, tmp_path / "out")
    art = next(a for a in artifacts if a.ref == "platform.Schema@1")
    assert "use super::module_id::ModuleId;" in art.content
    assert "pub module_id: ModuleId," in art.content
```

- [ ] **Step 2: Verify the tests fail**

Run from `cli/`: `uv run pytest tests/test_emit_rust.py -k semantic_type -q`.
Expected: the first test fails because `emit_rust` never emits an
artifact with `ref == "platform.ModuleId"`; the second fails because the
field falls through to whatever `rust.py` currently does for an
unresolved `NamedType` today (check what that actually renders — likely
a `missing_metadata`-warned fallback — before assuming the exact current
output, since this is the baseline the test is guarding against).

- [ ] **Step 3: Emit the newtype**

Add an `_emit_semantic_type(domain, decl, out_dir) -> EmittedArtifact`
function to `rust.py` and call it from `emit_rust` for every
`domain.semantic_types` entry, alongside the existing per-model and
per-projection emission loops. Resolve `decl.underlying` to a Rust type
name via the *existing* primitive/decimal/fixed-binary mapping functions
this file already has (`_primitive_to_rust`, the decimal `"String"` case,
the fixed-binary `[u8; N]` case) — reuse them directly rather than
duplicating the mapping; a `NamedType` underlying (chained semantic type)
resolves to that other semantic type's struct name and needs its own
`use super::...` import line in the generated file.

Render:

```rust
// @generated by Modelable
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, serde::Serialize, serde::Deserialize)]
#[serde(transparent)]
pub struct ModuleId(pub u32);

impl From<u32> for ModuleId {
    fn from(value: u32) -> Self {
        ModuleId(value)
    }
}

impl From<ModuleId> for u32 {
    fn from(value: ModuleId) -> Self {
        value.0
    }
}

impl std::ops::Deref for ModuleId {
    type Target = u32;

    fn deref(&self) -> &u32 {
        &self.0
    }
}
```

Use `Copy`/`Eq`/`Hash` only when the underlying Rust type itself supports
them (primitive integers do; `String`/`Vec<u8>`/`[u8; N]` don't all — check
each underlying mapping's actual Rust type before hardcoding this derive
list, and drop `Copy`/`Eq`/`Hash` for underlying types that don't support
them, e.g. `String` for decimal or `Vec<u8>` for `binary`). Artifact
`ref` is `f"{domain.name}.{decl.name}"` (no version, matching the IR),
`artifact_id` the same, path `out_dir / snake_case(domain.name) / f"{snake_case(decl.name)}.rs"`.

- [ ] **Step 4: Verify the newtype test passes**

Run from `cli/`: `uv run pytest tests/test_emit_rust.py -k test_emit_rust_semantic_type_newtype -q`.

- [ ] **Step 5: Resolve field references to the newtype**

Find where `rust.py` collects and resolves `NamedType` references today
(`_collect_named_type_refs` and `_resolve_named_type_map`, per the
Architecture section of this plan). Extend `_resolve_named_type_map` (or
add a parallel lookup folded into the same result map) to also search
each domain's `semantic_types` list, not just `.models` — producing the
struct name and a `use super::<snake_name>::<StructName>;` import
pointing at the semantic type's own file instead of a model file. Models
take precedence on a name collision only if Task 2's duplicate/collision
validation somehow doesn't fire first (it should always fire first;
treat this as defense in depth, not the primary safeguard).

- [ ] **Step 6: Verify both tests pass**

Run from `cli/`: `uv run pytest tests/test_emit_rust.py -k semantic_type -q`,
then the full file: `uv run pytest tests/test_emit_rust.py -q`.

## Task 4: Documentation

**Files:**
- Modify: `docs/language-reference.md`, `docs/compiler-reference.md`,
  `ROADMAP.md`, `CHANGELOG.md`

- [ ] **Step 1: Add a language reference section**

`docs/language-reference.md` doesn't have a home for domain-level
declarations beyond models/projections yet — add a new subsection (near
wherever `auto projections` is documented, as the closest existing
precedent for an unversioned domain-level declaration) covering
`semantic`'s syntax, the underlying-type restriction, and that it's
currently Rust-only for code generation.

- [ ] **Step 2: Update the compiler reference**

Document the Rust newtype shape (struct, `From`/`Deref`, file path
convention) in `docs/compiler-reference.md`'s Rust emitter section.

- [ ] **Step 3: Update ROADMAP and CHANGELOG**

Mark this slice shipped in `ROADMAP.md`'s feature-gaps response entry,
matching the wording style used for the two 1.2 slices. Add a
`CHANGELOG.md` entry under `[Unreleased]`, noting the Rust-only scope and
listing Go/Java/C#/Python/TypeScript/structural-target mappings as
explicit follow-ups (not silently omitted).

- [ ] **Step 4: Verify docs mention the new declaration**

Run from repo root: `rg -n "semantic <Name>|semantic ModuleId|SemanticTypeDecl" docs/language-reference.md docs/compiler-reference.md CHANGELOG.md ROADMAP.md`.

## Task 5: Final Verification

- [ ] **Step 1: Run all focused tests**

```bash
uv run pytest tests/test_grammar.py tests/test_semantic.py tests/test_emit_rust.py --tb=short -q
```

- [ ] **Step 2: Run the full suite, ruff, and the mypy baseline ratchet**

```bash
uv run ruff format --check .
uv run ruff check .
uv run pytest --tb=short
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
```

Regenerate `mypy-baseline.txt` from a fresh `uv run mypy ...` run — taken
**after** `ruff format` has made its final pass over every touched file,
not before (a prior slice's baseline briefly went stale in CI because a
post-regeneration `ruff format` line-wrap shifted line numbers after the
baseline was already written).

- [ ] **Step 3: Inspect the final diff**

```bash
git diff --stat
```

Expected: diff touches only the grammar, transformer, IR, validator,
`rust.py`, their tests, the four documentation files, and (if needed)
the mypy baseline.

## Self-Review

Spec coverage:

- Covered: `semantic` declaration parses; `SemanticTypeDecl` IR;
  underlying-kind, dangling-reference, cycle/depth, and duplicate/collision
  validation; Rust newtype emission with correctly-scoped derives; field
  references resolve to the newtype via the existing `NamedType` search
  path.
- Deferred by design (see the response design doc section 6 and this
  plan's Scope section): every non-Rust target, CEL nominal typing,
  dotted references, anything consuming `registry: true`.

Placeholder scan: none — every task ends with a green-test checkpoint.

Type consistency: `SemanticTypeDecl.underlying` reuses the existing
`FieldType` union with no changes to it; the only new Pydantic model is
`SemanticTypeDecl` itself, structurally parallel to `AutoProjectionDecl`.
