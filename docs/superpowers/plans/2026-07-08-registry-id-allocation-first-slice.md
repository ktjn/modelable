# Deterministic Small-Integer Registry ID Allocation First Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consume the `registry: true` marker on `semantic` declarations (added inert in Modelable 1.3) by allocating small, stable, monotonically-increasing integer ids, persisted in a new git-tracked ledger file `registry-ids.lock` — the first implementation slice of Modelable 1.4.

**Architecture:** Allocation state cannot live only in the disposable, rebuild-from-scratch `registry.db` (`docs/architecture.md` line 830: "Deleting it and re-running `compile` must produce an identical result"). A monotonic counter recomputed purely from declaration order would silently renumber ids the moment a new `registry: true` declaration is added earlier in file order than an existing one — that violates "never reassigned or reused." So the ledger is a new committed JSON file at the workspace root, read/updated/written by `modelable compile` before it (re)builds `registry.db`. `registry.db` gains a `registry_ids` table populated as a **read-through cache** of the lock file, keeping it queryable via any SQL tool without becoming the source of truth. See
[docs/superpowers/specs/2026-07-07-modelable-feature-gaps-response-design.md](../specs/2026-07-07-modelable-feature-gaps-response-design.md)
section 7 for the full design.

**Tech Stack:** Python 3.14, Click, sqlite3, Pydantic IR, pytest, ruff.

---

## Scope And Version Boundary

This is Modelable 1.4 work, following the three shipped slices of 1.2/1.3
(fixed-width integers, fixed-length binary, semantic type-alias mechanism —
all shipped). This first slice covers the mechanism end-to-end for the one
target that already understands semantic types (Rust) plus the core
allocation/persistence/CLI surface, which is target-independent.

Out of scope for this first slice:

- **Protobuf schema manifest exposure.** The design doc names this as a
  manifest that should expose the allocated id, but `protobuf.py` has *zero*
  semantic-type awareness today (it never resolves a `NamedType` field
  reference to a `SemanticTypeDecl` the way `rust.py` does) — teaching it
  about semantic types at all is a bigger prerequisite than this slice's
  scope. Deferred as a follow-up once protobuf gains semantic-type support.
- **New `modelable inspect` CLI surface for id lookup.** The design doc's
  stated purpose for the `registry_ids` table is to keep `registry.db`
  "queryable... without making it the source of truth" — an ordinary SQLite
  table already satisfies that via any SQL client (`sqlite3 .modelable/registry.db
  "select * from registry_ids"`). Purpose-built `inspect` UX for it is a
  separate, optional CLI ergonomics improvement, not required for the
  mechanism to work correctly, and is deferred.
- Non-Rust emitters' equivalent of the doc-comment exposure (Go doc
  comments, Java Javadoc, etc.) — the design doc only names Rust and
  protobuf; other targets don't have semantic-type support yet regardless
  (see the semantic-type-alias-mechanism plan's own deferred list).
- OCI/distributed-registry distribution of `registry-ids.lock` — the design
  doc only discusses a workspace-root file; no remote-registry story exists
  for it and none is needed for a single-workspace compile.

## File Structure

- Create `cli/src/modelable/registry/ids.py`: lock-file read/write and the
  allocation algorithm.
- Modify `cli/src/modelable/registry/schema.sql`: add `registry_ids` table.
- Modify `cli/src/modelable/registry/index.py`: `build_registry` accepts an
  optional `registry_ids` map and populates the new table.
- Modify `cli/src/modelable/commands/compile.py`: read/allocate/write the
  lock file before building the registry; add `--registry-ids` and
  `--allow-orphaned-registry-ids` options; pass the allocated map into
  `emit_rust`.
- Modify `cli/src/modelable/emitters/rust.py`: `emit_rust` and
  `_emit_semantic_type` accept an optional id map and emit a `///` doc
  comment when a declaration has an allocated id.
- Modify `docs/cli-reference.md`, `docs/getting-started.md`,
  `docs/compiler-reference.md`, `docs/language-reference.md`,
  `ROADMAP.md`, `CHANGELOG.md`.
- Create `cli/tests/test_registry_ids.py`. Modify
  `cli/tests/test_registry_index.py`, `cli/tests/test_cli.py`,
  `cli/tests/test_emit_rust.py`.

## Task 1: Allocation Module And Lock File I/O

**Files:**
- Create: `cli/src/modelable/registry/ids.py`
- Create: `cli/tests/test_registry_ids.py`

- [ ] **Step 1: Write the failing tests**

Create `cli/tests/test_registry_ids.py`:

```python
import json

from modelable.compiler.workspace import load_workspace
from modelable.registry.ids import allocate_registry_ids, read_lock_file, write_lock_file


def _write_mdl(path, text):
    path.write_text(text, encoding="utf-8")


def test_allocate_assigns_ids_in_domain_then_name_order(tmp_path):
    mdl_path = tmp_path / "test.mdl"
    _write_mdl(
        mdl_path,
        """
domain platform {
  owner: "test-team"
  semantic SchemaId : u32 { registry: true }
  semantic CommandId : u32 { registry: true }
}

domain billing {
  owner: "test-team"
  semantic InvoiceKind : u8 { registry: true }
}
""",
    )
    workspace = load_workspace(mdl_path)
    ids = allocate_registry_ids(workspace.mdl, {})
    assert ids == {
        "billing.InvoiceKind": 1,
        "platform.CommandId": 2,
        "platform.SchemaId": 3,
    }


def test_allocate_never_reassigns_existing_ids(tmp_path):
    mdl_path = tmp_path / "test.mdl"
    _write_mdl(
        mdl_path,
        """
domain platform {
  owner: "test-team"
  semantic SchemaId : u32 { registry: true }
  semantic CommandId : u32 { registry: true }
}
""",
    )
    workspace = load_workspace(mdl_path)
    ids = allocate_registry_ids(workspace.mdl, {"platform.SchemaId": 7})
    assert ids["platform.SchemaId"] == 7
    assert ids["platform.CommandId"] == 8


def test_allocate_ignores_non_registry_semantic_types(tmp_path):
    mdl_path = tmp_path / "test.mdl"
    _write_mdl(
        mdl_path,
        """
domain platform {
  owner: "test-team"
  semantic ModuleId : u32
  semantic SchemaId : u32 { registry: true }
}
""",
    )
    workspace = load_workspace(mdl_path)
    ids = allocate_registry_ids(workspace.mdl, {})
    assert ids == {"platform.SchemaId": 1}


def test_allocate_raises_on_orphaned_id_by_default(tmp_path):
    mdl_path = tmp_path / "test.mdl"
    _write_mdl(
        mdl_path,
        """
domain platform {
  owner: "test-team"
  semantic SchemaId : u32 { registry: true }
}
""",
    )
    workspace = load_workspace(mdl_path)
    try:
        allocate_registry_ids(workspace.mdl, {"platform.CommandId": 1, "platform.SchemaId": 2})
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "platform.CommandId" in str(exc)


def test_allocate_keeps_orphaned_id_unreused_when_allowed(tmp_path):
    mdl_path = tmp_path / "test.mdl"
    _write_mdl(
        mdl_path,
        """
domain platform {
  owner: "test-team"
  semantic SchemaId : u32 { registry: true }
}
""",
    )
    workspace = load_workspace(mdl_path)
    ids = allocate_registry_ids(
        workspace.mdl,
        {"platform.CommandId": 1, "platform.SchemaId": 2},
        allow_orphaned=True,
    )
    assert ids == {"platform.CommandId": 1, "platform.SchemaId": 2}
    # A later new registration must not reuse the orphaned id.
    _write_mdl(
        mdl_path,
        """
domain platform {
  owner: "test-team"
  semantic SchemaId : u32 { registry: true }
  semantic EventId : u32 { registry: true }
}
""",
    )
    workspace2 = load_workspace(mdl_path)
    ids2 = allocate_registry_ids(workspace2.mdl, ids, allow_orphaned=True)
    assert ids2["platform.EventId"] == 3


def test_read_lock_file_missing_returns_empty(tmp_path):
    assert read_lock_file(tmp_path / "registry-ids.lock") == {}


def test_write_then_read_lock_file_round_trips_sorted_by_id(tmp_path):
    path = tmp_path / "registry-ids.lock"
    write_lock_file(path, {"b.Z": 2, "a.A": 1})
    raw = path.read_text(encoding="utf-8")
    assert list(json.loads(raw).keys()) == ["a.A", "b.Z"]
    assert read_lock_file(path) == {"a.A": 1, "b.Z": 2}
```

- [ ] **Step 2: Verify the tests fail**

Run from `cli/`: `uv run pytest tests/test_registry_ids.py -q`. Expected:
`ModuleNotFoundError` / `ImportError` — `modelable.registry.ids` doesn't
exist yet.

- [ ] **Step 3: Implement the module**

Create `cli/src/modelable/registry/ids.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from modelable.parser.ir import MdlFile


def _qualified_registry_names(mdl: MdlFile) -> list[str]:
    return sorted(
        f"{domain.name}.{decl.name}"
        for domain in mdl.domains
        for decl in domain.semantic_types
        if decl.registry
    )


def allocate_registry_ids(
    mdl: MdlFile,
    existing: dict[str, int],
    *,
    allow_orphaned: bool = False,
) -> dict[str, int]:
    """Allocate deterministic small-integer ids for every `registry: true`
    semantic type, never reassigning or reusing an id already in `existing`.
    """
    declared = set(_qualified_registry_names(mdl))
    orphaned = sorted(name for name in existing if name not in declared)
    if orphaned and not allow_orphaned:
        joined = ", ".join(orphaned)
        raise ValueError(
            f"registry-ids.lock has {len(orphaned)} orphaned id(s) with no matching "
            f"'registry: true' semantic type declaration: {joined}. Pass "
            "--allow-orphaned-registry-ids to keep them reserved (they are never reused)."
        )

    updated = dict(existing)
    next_id = max(existing.values(), default=0) + 1
    for name in sorted(declared - existing.keys()):
        updated[name] = next_id
        next_id += 1
    return updated


def read_lock_file(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_lock_file(path: Path, ids: dict[str, int]) -> None:
    ordered = dict(sorted(ids.items(), key=lambda item: item[1]))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ordered, indent=2) + "\n", encoding="utf-8")
```

- [ ] **Step 4: Verify the tests pass**

Run from `cli/`: `uv run pytest tests/test_registry_ids.py -q`.

## Task 2: Wire Into `compile`

**Files:**
- Modify: `cli/src/modelable/commands/compile.py`
- Modify: `cli/tests/test_cli.py`

- [ ] **Step 1: Write the failing CLI tests**

Append to `cli/tests/test_cli.py` (check the existing imports at the top of
the file — `CliRunner`, `Path`, `cli` — before adding new tests; reuse
them):

```python
def test_compile_allocates_and_persists_registry_ids(tmp_path):
    mdl = tmp_path / "platform.mdl"
    mdl.write_text(
        """
domain platform {
  owner: "test-team"
  semantic SchemaId : u32 { registry: true }
}
""",
        encoding="utf-8",
    )

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            cli,
            ["compile", str(mdl), "--target", "rust", "--out", str(tmp_path / "dist")],
        )

        assert result.exit_code == 0
        lock_path = Path("registry-ids.lock")
        assert lock_path.exists()
        import json

        assert json.loads(lock_path.read_text(encoding="utf-8")) == {"platform.SchemaId": 1}


def test_compile_is_stable_across_repeated_runs(tmp_path):
    mdl = tmp_path / "platform.mdl"
    mdl.write_text(
        """
domain platform {
  owner: "test-team"
  semantic SchemaId : u32 { registry: true }
}
""",
        encoding="utf-8",
    )

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        for _ in range(2):
            result = runner.invoke(
                cli,
                ["compile", str(mdl), "--target", "rust", "--out", str(tmp_path / "dist")],
            )
            assert result.exit_code == 0

        import json

        assert json.loads(Path("registry-ids.lock").read_text(encoding="utf-8")) == {"platform.SchemaId": 1}


def test_compile_rejects_orphaned_registry_id_without_flag(tmp_path):
    mdl = tmp_path / "platform.mdl"
    mdl.write_text(
        """
domain platform {
  owner: "test-team"
  semantic SchemaId : u32 { registry: true }
}
""",
        encoding="utf-8",
    )

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        Path("registry-ids.lock").write_text(
            '{"platform.RemovedId": 1, "platform.SchemaId": 2}\n', encoding="utf-8"
        )
        result = runner.invoke(
            cli,
            ["compile", str(mdl), "--target", "rust", "--out", str(tmp_path / "dist")],
        )
        assert result.exit_code != 0
        assert "platform.RemovedId" in result.output

        result_allowed = runner.invoke(
            cli,
            [
                "compile",
                str(mdl),
                "--target",
                "rust",
                "--out",
                str(tmp_path / "dist"),
                "--allow-orphaned-registry-ids",
            ],
        )
        assert result_allowed.exit_code == 0
```

- [ ] **Step 2: Verify the tests fail**

Run from `cli/`: `uv run pytest tests/test_cli.py -k registry_id -q`.
Expected: no `registry-ids.lock` is ever written today, and there's no
`--allow-orphaned-registry-ids` option (Click will error on the unknown
option in the last case).

- [ ] **Step 3: Wire allocation into `compile`**

In `compile.py`, add two options to the `compile` command (near the
existing `--registry` option):

```python
@click.option(
    "--registry-ids",
    "registry_ids_path",
    type=click.Path(path_type=Path),
    default=Path("registry-ids.lock"),
    help="Path to the registry id allocation ledger (must be committed to git).",
)
@click.option(
    "--allow-orphaned-registry-ids",
    is_flag=True,
    help="Tolerate ledger entries with no matching 'registry: true' declaration instead of erroring.",
)
def compile(
    source: Path,
    target: str,
    out_dir: Path | None,
    registry_path: str,
    registry_ids_path: Path,
    allow_orphaned_registry_ids: bool,
) -> None:
```

Right after `workspace = load_workspace_or_exit(source)` and before the
`get_registry`/`build_registry` block, add:

```python
    from modelable.registry.ids import allocate_registry_ids, read_lock_file, write_lock_file

    existing_ids = read_lock_file(registry_ids_path)
    try:
        registry_ids = allocate_registry_ids(
            workspace.mdl, existing_ids, allow_orphaned=allow_orphaned_registry_ids
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    write_lock_file(registry_ids_path, registry_ids)
```

(Move the `from modelable.registry.ids import ...` line to the top-level
import block with the rest of the file's imports instead of inline —
inline imports aren't this file's existing style; only written inline
here to show the insertion point clearly.)

Pass `registry_ids` into `build_registry(...)` (Task 3) and into the
`emit_rust(...)` call specifically (Task 4) — every other target's
`emit_*` call is unchanged, since only Rust consumes it in this slice.

- [ ] **Step 4: Verify the tests pass**

Run from `cli/`: `uv run pytest tests/test_cli.py -k registry_id -q`, then
the full file: `uv run pytest tests/test_cli.py -q`.

## Task 3: `registry.db` Read-Through Cache

**Files:**
- Modify: `cli/src/modelable/registry/schema.sql`
- Modify: `cli/src/modelable/registry/index.py`
- Modify: `cli/tests/test_registry_index.py`

- [ ] **Step 1: Write the failing test**

Append to `cli/tests/test_registry_index.py`:

```python
def test_build_registry_populates_registry_ids_table(tmp_path):
    source = tmp_path / "platform.mdl"
    source.write_text(
        """
domain platform {
  owner: "test-team"
  semantic SchemaId : u32 { registry: true }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(source)
    registry_path = build_registry(
        workspace, tmp_path / ".modelable", registry_ids={"platform.SchemaId": 1}
    )

    with sqlite3.connect(registry_path) as conn:
        assert conn.execute(
            "select name, allocated_id from registry_ids"
        ).fetchall() == [("platform.SchemaId", 1)]
```

- [ ] **Step 2: Verify the test fails**

Run from `cli/`: `uv run pytest tests/test_registry_index.py -k registry_ids_table -q`.
Expected: `TypeError` — `build_registry` has no `registry_ids` keyword yet;
after adding the keyword, `sqlite3.OperationalError: no such table:
registry_ids`.

- [ ] **Step 3: Add the table and populate it**

In `schema.sql`, add (matching the existing lowercase, unquoted style):

```sql
create table registry_ids (
  name text primary key,
  allocated_id integer unique not null,
  first_registered_at text
);
```

`first_registered_at` is nullable in this slice — the lock file itself has
no timestamp field, and inventing one that doesn't round-trip through
`registry-ids.lock` would make the "read-through cache" claim false. Leave
it `NULL` on every insert; do not add a `datetime('now')` default that
would make `registry.db` non-reproducible from the same lock file (that
would violate the "deleting and re-running compile must produce an
identical result" invariant this whole design exists to preserve).

In `index.py`, add a `registry_ids: dict[str, int] | None = None` keyword
parameter to `build_registry`, and thread it to a new
`_insert_registry_ids(conn, registry_ids)` helper called once inside the
`with sqlite3.connect(...)` block, alongside `_insert_workspace`:

```python
def _insert_registry_ids(conn: sqlite3.Connection, registry_ids: dict[str, int] | None) -> None:
    if not registry_ids:
        return
    for name, allocated_id in registry_ids.items():
        conn.execute(
            "insert into registry_ids (name, allocated_id, first_registered_at) values (?, ?, ?)",
            (name, allocated_id, None),
        )
```

- [ ] **Step 4: Verify the test passes**

Run from `cli/`: `uv run pytest tests/test_registry_index.py -q` (full
file — confirm no regression to the pre-existing tests that call
`build_registry` without the new keyword).

## Task 4: Rust Doc-Comment Exposure

**Files:**
- Modify: `cli/src/modelable/emitters/rust.py`
- Modify: `cli/tests/test_emit_rust.py`
- Modify: `cli/src/modelable/commands/compile.py` (thread `registry_ids` into the `emit_rust` call)

- [ ] **Step 1: Write the failing tests**

Append to `cli/tests/test_emit_rust.py`:

```python
def test_emit_rust_semantic_type_with_allocated_id_gets_doc_comment(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text(
        """
domain platform {
  owner: "test-team"

  semantic SchemaId : u32 { registry: true }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_rust(workspace, tmp_path / "out", registry_ids={"platform.SchemaId": 1})
    art = next(a for a in artifacts if a.ref == "platform.SchemaId")
    assert "/// registry id: 1" in art.content


def test_emit_rust_semantic_type_without_allocated_id_has_no_doc_comment(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text(
        """
domain platform {
  owner: "test-team"

  semantic SchemaId : u32 { registry: true }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_rust(workspace, tmp_path / "out")
    art = next(a for a in artifacts if a.ref == "platform.SchemaId")
    assert "registry id" not in art.content
```

- [ ] **Step 2: Verify the tests fail**

Run from `cli/`: `uv run pytest tests/test_emit_rust.py -k registry_id -q`.
Expected: `TypeError` — `emit_rust` has no `registry_ids` keyword yet.

- [ ] **Step 3: Thread the id map through**

In `rust.py`:

- `emit_rust(workspace: Workspace, out_dir: Path, *, registry_ids: dict[str, int] | None = None) -> list[EmittedArtifact]`
  — pass `registry_ids` through to `_emit_semantic_type`.
- `_emit_semantic_type(domain: DomainDef, decl: SemanticTypeDecl, out_dir: Path, *, allocated_id: int | None = None) -> EmittedArtifact`
  — the call site in `emit_rust` becomes:
  ```python
  qualified_name = f"{domain.name}.{decl.name}"
  allocated_id = (registry_ids or {}).get(qualified_name) if decl.registry else None
  artifacts.append(_emit_semantic_type(domain, decl, out_dir, allocated_id=allocated_id))
  ```
- Inside `_emit_semantic_type`, insert the doc comment immediately before
  the `#[derive(...)]` line, only when `allocated_id is not None`:
  ```python
  if allocated_id is not None:
      lines.append(f"/// registry id: {allocated_id}")
  lines.append(f"#[derive({', '.join(derives)})]")
  ```

- [ ] **Step 4: Verify the tests pass**

Run from `cli/`: `uv run pytest tests/test_emit_rust.py -k registry_id -q`,
then the full file: `uv run pytest tests/test_emit_rust.py -q`.

- [ ] **Step 5: Wire the id map into `compile`'s Rust branch**

In `compile.py`'s `elif target == "rust":` branch, change
`artifacts = emit_rust(workspace, output)` to
`artifacts = emit_rust(workspace, output, registry_ids=registry_ids)`.
Every other target's emitter call is unchanged.

## Task 5: Documentation

**Files:**
- Modify: `docs/cli-reference.md`, `docs/getting-started.md`,
  `docs/compiler-reference.md`, `docs/language-reference.md`,
  `ROADMAP.md`, `CHANGELOG.md`

- [ ] **Step 1: `docs/cli-reference.md` §5.5 `compile`**

Add a paragraph after the existing `registry.db`/plan-documents sentence
(the one ending "...should be added to `.gitignore`") explaining
`registry-ids.lock`: it is the ledger `compile` reads and updates for
every `semantic ... { registry: true }` declaration, allocated ids are
never reassigned or reused, and — unlike `registry.db` — **it must be
committed to git, not gitignored**. Add `--registry-ids` and
`--allow-orphaned-registry-ids` rows to the Options table. Don't touch the
per-target subsections (§5.20 `odcs`, §5.21 `protobuf`, etc.) that repeat
a trimmed Options table — this behavior is compile-wide, and duplicating
the note across every target subsection isn't proportionate to a one-slice
feature; the authoritative description belongs in §5.5.

- [ ] **Step 2: `docs/getting-started.md`**

The Quick Start section currently says (unconditionally) "Generated
artifacts are consumer contracts, not the source of truth. Commit `.mdl`
definitions; regenerate schemas, language bindings, and Markdown in CI...".
Add an explicit carve-out sentence immediately after it: `registry-ids.lock`
is the one exception — it is compiler-written but must be committed,
because it is the durable record of id allocation, not a regenerable
artifact.

- [ ] **Step 3: `docs/compiler-reference.md`**

Extend the semantic-types Rust note added in the previous slice (search
for "registry id" — it shouldn't currently return the compiler-reference.md
match; search `#[serde(transparent)]` to relocate the note) to mention the
`/// registry id: N` doc comment emitted when a declaration is
`registry: true` and has an allocated id.

- [ ] **Step 4: `docs/language-reference.md` §3.8**

The existing "Referencing a semantic type" / `registry: true` paragraph
currently says the marker "is parsed and validated but not yet consumed by
any emitter" (or similar wording — check the exact sentence before
editing). Update it: `registry: true` now triggers deterministic id
allocation into `registry-ids.lock`, with a one-line pointer to the CLI
reference for the mechanics rather than duplicating them.

- [ ] **Step 5: `ROADMAP.md` and `CHANGELOG.md`**

Mark this slice shipped in the feature-gaps response entry, following the
wording style of the three prior shipped-slice paragraphs. Add a
`CHANGELOG.md` `[Unreleased]` entry noting: the `registry-ids.lock` file
and its allocation guarantees, the new `registry_ids` table in
`registry.db`, the Rust doc-comment exposure, and explicitly listing the
protobuf-manifest exposure and `modelable inspect` id lookup as deferred
follow-ups (not silently omitted, matching this repo's established
changelog style for partial-scope slices).

- [ ] **Step 6: Verify docs mention the new mechanism**

Run from repo root:
`rg -n "registry-ids.lock|registry_ids|allow-orphaned-registry-ids" docs/cli-reference.md docs/getting-started.md docs/compiler-reference.md docs/language-reference.md CHANGELOG.md ROADMAP.md`.

## Task 6: Final Verification

- [ ] **Step 1: Run all focused tests**

```bash
uv run pytest tests/test_registry_ids.py tests/test_registry_index.py tests/test_cli.py tests/test_emit_rust.py --tb=short -q
```

- [ ] **Step 2: Run the full suite, ruff, and the mypy baseline ratchet**

```bash
uv run ruff format --check .
uv run ruff check .
uv run pytest --tb=short
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
```

Regenerate `mypy-baseline.txt` from a fresh `uv run mypy ...` run taken
**after** `ruff format`'s final pass, matching the lesson from the two
prior slices where regenerating before the final format pass caused a
line-shift CI failure.

- [ ] **Step 3: Confirm `registry-ids.lock` is not accidentally gitignored**

```bash
git check-ignore -v registry-ids.lock || echo "not ignored (expected)"
```

There is no existing `.gitignore` pattern that would catch a top-level
`registry-ids.lock` (it isn't inside `.modelable/` or `dist/`), but verify
directly rather than assuming, since this file **must** be committable —
that's the entire point of the design.

- [ ] **Step 4: Inspect the final diff**

```bash
git diff --stat
```

Expected: diff touches `registry/ids.py` (new), `registry/schema.sql`,
`registry/index.py`, `commands/compile.py`, `emitters/rust.py`, their
tests, the six documentation files, and the mypy baseline.

## Self-Review

Spec coverage:

- Covered: deterministic allocation (domain-then-name order), never
  reassigned/reused (including orphan detection and the
  `--allow-orphaned-registry-ids` escape hatch), `registry-ids.lock`
  persistence, `registry.db`'s `registry_ids` read-through cache table,
  Rust doc-comment exposure.
- Deferred by design (see Scope section above): protobuf schema-manifest
  exposure (blocked on protobuf gaining semantic-type support at all),
  `modelable inspect` CLI surface for id lookup (ordinary SQL access
  already satisfies the design doc's stated "queryable" requirement),
  non-Rust emitter doc-comment equivalents, OCI/remote distribution of the
  lock file.

Placeholder scan: none — every task ends with a green-test checkpoint.

Type consistency: no changes to the `FieldType` union or any existing
Pydantic model; `SemanticTypeDecl.registry` (already `bool`, added in the
prior slice) is read-only input to the new allocation module, which deals
entirely in `dict[str, int]` and raises `ValueError` on the one documented
error condition, matching `build_registry`'s own existing
`raise ValueError(...)` precedent for a workspace-level compile error.
