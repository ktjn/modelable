# Rust Emitter Correctness Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the `_pascalize` all-caps casing bug in the Rust and C# emitters, and add a repeatable `--domain` filter to `modelable compile` so diagnostics/artifacts can be scoped to a subset of a workspace.

**Architecture:** Two independent, additive changes. (1) A one-line fix to `_pascalize` in `rust.py` and `csharp.py` so it lowercases the remainder of each split token before re-capitalizing, fixing SCREAMING_SNAKE_CASE enum values emitted as non-idiomatic all-caps Rust/C# identifiers. (2) A new `--domain <name>` Click option on `compile` that, when given, validates the requested domain names exist and restricts the `Workspace` passed to the target emitter (not the registry/plan-writing steps, which stay workspace-wide) to just those domains.

**Tech Stack:** Python 3.14, Click, pydantic, pytest.

## Global Constraints

- Each emitter (`rust.py`, `csharp.py`, `go.py`, `java.py`, `python.py`, `typescript.py`) keeps its own private copy of `_pascalize` — do not extract a shared helper into `emitters/base.py`. Only the Rust and C# copies change in this plan; Go, Java, Python, TypeScript are explicitly left alone (see design doc `docs/superpowers/specs/2026-07-11-rust-emitter-correctness-fixes-design.md` § Finding 1 blast-radius table).
- The `--domain` filter changes only which domains are passed to the target emitter. Registry id allocation, registry push, and `.modelable/plans` writing must still run against the full, unfiltered workspace in every case — do not scope those to `--domain`.
- Omitting `--domain` must reproduce today's whole-workspace compile behavior byte-for-byte (existing tests in `test_emit_rust.py`, `test_emit_csharp.py`, and `test_wire_golden.py` must keep passing unmodified).

---

### Task 1: Fix `_pascalize` all-caps casing bug in the Rust emitter

**Files:**
- Modify: `cli/src/modelable/emitters/rust.py:168-170`
- Test: `cli/tests/test_emit_rust.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `_pascalize(value: str) -> str` in `modelable.emitters.rust` now title-cases every split token regardless of input casing (previously left tokens beyond the first character untouched, so an all-caps token stayed all-caps).

- [x] **Step 1: Write the failing tests**

Add to `cli/tests/test_emit_rust.py`, after `test_emit_rust_enum_field_numeric_prefix_sanitized` (around line 1170):

```python
def test_pascalize_titlecases_all_uppercase_tokens():
    from modelable.emitters.rust import _pascalize

    assert _pascalize("INTERNAL") == "Internal"
    assert _pascalize("SERVER_CLIENT") == "ServerClient"
    assert _pascalize("AlreadyPascalCase") == "AlreadyPascalCase"
    assert _pascalize("camelCase") == "CamelCase"


def test_emit_rust_screaming_snake_case_enum_value_becomes_pascal_case(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain tracing {
  owner: "test-team"
  entity Span @ 1 (additive) {
    @key spanId: uuid
    spanKind: enum(INTERNAL, SERVER, CLIENT, PRODUCER, CONSUMER)
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_rust(workspace, tmp_path / "out")
    art = next(a for a in artifacts if a.ref == "tracing.Span@1")
    # Rust variant names are idiomatic PascalCase, not the raw wire casing
    assert "Internal," in art.content
    assert "Server," in art.content
    assert "Client," in art.content
    assert "Producer," in art.content
    assert "Consumer," in art.content
    assert "INTERNAL," not in art.content
    # The wire value is preserved via serde rename so the wire contract doesn't shift
    assert '#[serde(rename = "INTERNAL")]' in art.content
    assert '#[serde(rename = "SERVER")]' in art.content
```

- [x] **Step 2: Run tests to verify they fail**

Run: `cd cli && python -m pytest tests/test_emit_rust.py -k "pascalize_titlecases or screaming_snake_case_enum" -v`
Expected: both FAIL — `test_pascalize_titlecases_all_uppercase_tokens` fails on `_pascalize("INTERNAL") == "Internal"` (actual: `"INTERNAL"`); `test_emit_rust_screaming_snake_case_enum_value_becomes_pascal_case` fails because `"Internal,"` is not in the generated content (it contains `"INTERNAL,"` instead).

- [x] **Step 3: Fix `_pascalize`**

In `cli/src/modelable/emitters/rust.py:168-170`, change:

```python
def _pascalize(value: str) -> str:
    parts = [part for part in re.split(r"[^A-Za-z0-9]+", value) if part]
    return "".join(part[:1].upper() + part[1:] for part in parts) or "Generated"
```

to:

```python
def _pascalize(value: str) -> str:
    parts = [part for part in re.split(r"[^A-Za-z0-9]+", value) if part]

    def _title(part: str) -> str:
        if part.isupper():
            return part[:1] + part[1:].lower()
        return part[:1].upper() + part[1:]

    return "".join(_title(part) for part in parts) or "Generated"
```

**Why not a plain `part[1:].lower()` on every part:** a single-token PascalCase input (no separators, e.g. `LogEntry`) is one split part, `"LogEntry"`. Lowercasing its remainder unconditionally turns it into `"Logentry"`, silently mangling every already-correct entity/model name in the corpus. Only lowering the remainder when the *whole* token is uppercase (`part.isupper()`) fixes the SCREAMING_SNAKE_CASE case (each token there — `INTERNAL`, `SERVER` — is fully uppercase) while leaving PascalCase/camelCase/mixed-case tokens exactly as the old code left them.

- [x] **Step 4: Run tests to verify they pass**

Run: `cd cli && python -m pytest tests/test_emit_rust.py -v`
Expected: PASS — full file, including the two new tests and every pre-existing `test_emit_rust*` test (the fix only changes behavior for tokens that are entirely uppercase, so existing PascalCase/camelCase/snake_case fixtures — including single-token names like `LogEntry` or `OrderRow` — are unaffected).

- [x] **Step 5: Commit**

```bash
git add cli/src/modelable/emitters/rust.py cli/tests/test_emit_rust.py
git commit -m "fix(rust): pascalize all-caps enum values instead of leaving them SCREAMING_CASE"
```

---

### Task 2: Fix `_pascalize` all-caps casing bug in the C# emitter

**Files:**
- Modify: `cli/src/modelable/emitters/csharp.py:31-33`
- Test: `cli/tests/test_emit_csharp.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `_pascalize(value: str) -> str` in `modelable.emitters.csharp`, same fixed behavior as Task 1's Rust version. Note: the C# emitter maps `enum`-kind fields straight to C# `string` (`cli/src/modelable/emitters/csharp.py:188-189`) and never synthesizes an enum member identifier from the wire values, so this fix has no enum-identifier-level effect today — it only changes `_stable_type_name`/`_namespace_name`/`_property_name`/`_nested_type_name` output, and only for all-uppercase domain/model/field names (verify via a direct unit test of `_pascalize`, not a full-pipeline enum test, since there is no C# enum identifier output to assert against).

- [x] **Step 1: Write the failing test**

Add to `cli/tests/test_emit_csharp.py`, near the top of the file (after the imports, before the first test):

```python
def test_pascalize_titlecases_all_uppercase_tokens():
    from modelable.emitters.csharp import _pascalize

    assert _pascalize("INTERNAL") == "Internal"
    assert _pascalize("SERVER_CLIENT") == "ServerClient"
    assert _pascalize("AlreadyPascalCase") == "AlreadyPascalCase"
    assert _pascalize("camelCase") == "CamelCase"
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd cli && python -m pytest tests/test_emit_csharp.py -k pascalize_titlecases -v`
Expected: FAIL on `_pascalize("INTERNAL") == "Internal"` (actual: `"INTERNAL"`).

- [x] **Step 3: Fix `_pascalize`**

In `cli/src/modelable/emitters/csharp.py:31-33`, change:

```python
def _pascalize(value: str) -> str:
    parts = [part for part in re.split(r"[^A-Za-z0-9]+", value) if part]
    return "".join(part[:1].upper() + part[1:] for part in parts) or "Generated"
```

to:

```python
def _pascalize(value: str) -> str:
    parts = [part for part in re.split(r"[^A-Za-z0-9]+", value) if part]

    def _title(part: str) -> str:
        if part.isupper():
            return part[:1] + part[1:].lower()
        return part[:1].upper() + part[1:]

    return "".join(_title(part) for part in parts) or "Generated"
```

**Why not a plain `part[1:].lower()` on every part:** see Task 1's note — a single-token PascalCase input (e.g. a domain or model name with no separators) is one split part, and unconditionally lowering its remainder would mangle every already-correct name in the corpus. Only lowering the remainder when the whole token is uppercase (`part.isupper()`) is the same fix applied in Task 1.

- [x] **Step 4: Run tests to verify they pass**

Run: `cd cli && python -m pytest tests/test_emit_csharp.py -v`
Expected: PASS — full file, including the new test and every pre-existing `test_emit_csharp*`/`test_cli_compile_csharp*` test.

- [x] **Step 5: Commit**

```bash
git add cli/src/modelable/emitters/csharp.py cli/tests/test_emit_csharp.py
git commit -m "fix(csharp): pascalize all-caps tokens instead of leaving them SCREAMING_CASE"
```

---

### Task 3: Add a repeatable `--domain` filter to `compile`

**Files:**
- Modify: `cli/src/modelable/commands/compile.py`
- Test: Create `cli/tests/test_cli_compile.py`

**Interfaces:**
- Consumes: `Workspace` (`modelable.compiler.workspace.Workspace`, a frozen dataclass with `.mdl: MdlFile`), `MdlFile` (`modelable.parser.ir.MdlFile`, a pydantic `BaseModel` with `.domains: list[DomainDef]`), `DomainDef.name: str`.
- Produces: `compile` CLI command gains a `--domain <name>` option (Click, `multiple=True`, repeatable, default `()`). When one or more `--domain` values are given: unknown names raise `click.ClickException` naming the bad value(s) and the available domains; known names restrict the workspace passed to the target emitter (all 16 target branches) to just those domains, while registry id allocation, registry push, and `.modelable/plans` writing keep using the full, unfiltered workspace. Omitting `--domain` is behaviorally identical to today.

- [x] **Step 1: Write the failing tests**

Create `cli/tests/test_cli_compile.py`:

```python
from __future__ import annotations

from click.testing import CliRunner

from modelable.cli import cli

_TWO_DOMAIN_MDL = """
domain logs {
  owner: "test-team"
  entity LogEntry @ 1 (additive) {
    @key logId: uuid
    message: string
  }
}

domain nlq {
  owner: "test-team"
  entity Query @ 1 (additive) {
    @key queryId: uuid
    text: string
  }
}
"""


def test_compile_domain_flag_restricts_output(tmp_path):
    mdl = tmp_path / "workspace.mdl"
    mdl.write_text(_TWO_DOMAIN_MDL, encoding="utf-8")
    out = tmp_path / "dist" / "rust"

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            cli,
            ["compile", str(mdl), "--target", "rust", "--domain", "logs", "--out", str(out)],
        )

    assert result.exit_code == 0, result.output
    assert (out / "logs" / "logs_log_entry_v1.rs").exists()
    assert not (out / "nlq").exists()


def test_compile_domain_flag_is_additive(tmp_path):
    mdl = tmp_path / "workspace.mdl"
    mdl.write_text(_TWO_DOMAIN_MDL, encoding="utf-8")
    out = tmp_path / "dist" / "rust"

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            cli,
            [
                "compile",
                str(mdl),
                "--target",
                "rust",
                "--domain",
                "logs",
                "--domain",
                "nlq",
                "--out",
                str(out),
            ],
        )

    assert result.exit_code == 0, result.output
    assert (out / "logs" / "logs_log_entry_v1.rs").exists()
    assert (out / "nlq" / "nlq_query_v1.rs").exists()


def test_compile_unknown_domain_errors_clearly(tmp_path):
    mdl = tmp_path / "workspace.mdl"
    mdl.write_text(_TWO_DOMAIN_MDL, encoding="utf-8")
    out = tmp_path / "dist" / "rust"

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            cli,
            ["compile", str(mdl), "--target", "rust", "--domain", "bogus", "--out", str(out)],
        )

    assert result.exit_code != 0
    assert "bogus" in result.output
    assert "logs" in result.output
    assert "nlq" in result.output
    assert not out.exists()


def test_compile_without_domain_flag_compiles_whole_workspace(tmp_path):
    mdl = tmp_path / "workspace.mdl"
    mdl.write_text(_TWO_DOMAIN_MDL, encoding="utf-8")
    out = tmp_path / "dist" / "rust"

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            cli,
            ["compile", str(mdl), "--target", "rust", "--out", str(out)],
        )

    assert result.exit_code == 0, result.output
    assert (out / "logs" / "logs_log_entry_v1.rs").exists()
    assert (out / "nlq" / "nlq_query_v1.rs").exists()
```

- [x] **Step 2: Run tests to verify they fail**

Run: `cd cli && python -m pytest tests/test_cli_compile.py -v`
Expected: FAIL — `no such option: --domain` (Click rejects the unrecognized option) for the three tests that pass `--domain`; the fourth (`test_compile_without_domain_flag_compiles_whole_workspace`) currently PASSES already (today's default behavior), which is fine — it's here as a regression guard for the change about to be made.

- [x] **Step 3: Add the `--domain` option and workspace scoping**

In `cli/src/modelable/commands/compile.py`, add the `dataclasses` import at the top of the file (after `from pathlib import Path`):

```python
import dataclasses
```

Add the option decorator right after the existing `--allow-orphaned-registry-ids` option (before the `def compile(` signature):

```python
@click.option(
    "--domain",
    "domains",
    multiple=True,
    default=(),
    help="Restrict compilation to the named domain(s) (repeatable). Omit to compile the whole workspace.",
)
```

Update the `compile` function signature to accept the new parameter:

```python
def compile(
    source: Path,
    target: str,
    out_dir: Path | None,
    registry_path: str,
    registry_ids_path: Path,
    allow_orphaned_registry_ids: bool,
    domains: tuple[str, ...],
) -> None:
```

Right after `workspace = load_workspace_or_exit(source)`, add the domain-scoping block:

```python
    emit_workspace = workspace
    if domains:
        known_domains = {d.name for d in workspace.mdl.domains}
        unknown_domains = sorted(set(domains) - known_domains)
        if unknown_domains:
            raise click.ClickException(
                f"Unknown --domain value(s): {', '.join(unknown_domains)}. "
                f"Available domains: {', '.join(sorted(known_domains))}"
            )
        scoped_domains = [d for d in workspace.mdl.domains if d.name in domains]
        emit_workspace = dataclasses.replace(
            workspace, mdl=workspace.mdl.model_copy(update={"domains": scoped_domains})
        )
```

Then, in every target branch inside the `if target == "json-schema": ... elif target == ...` chain (lines ~121-255), replace the workspace argument passed to each `emit_*` call — `workspace` becomes `emit_workspace` — for all of: `emit_json_schema`, `emit_markdown`, `emit_typescript`, `emit_csharp`, `emit_java`, `emit_python`, `emit_rust`, `emit_go`, `emit_dbt_yaml`, `emit_fhir_profile`, `emit_openmetadata`, `emit_openlineage`, `emit_odcs`, `emit_protobuf`, `emit_grpc`, `emit_sql`. Do not change the `registry.push(built_registry_path)` or `write_plans(workspace, plans_dir)` calls above this block — those must keep using the original, unfiltered `workspace`.

- [x] **Step 4: Run tests to verify they pass**

Run: `cd cli && python -m pytest tests/test_cli_compile.py cli/tests/test_emit_rust.py cli/tests/test_emit_csharp.py -v`

(if running from repo root, drop the `cli/` prefix already implied by `cd cli`; use `cd cli && python -m pytest tests/test_cli_compile.py tests/test_emit_rust.py tests/test_emit_csharp.py -v`)

Expected: PASS — all four new tests in `test_cli_compile.py`, plus every pre-existing `test_emit_rust.py`/`test_emit_csharp.py` test (which never pass `--domain`, exercising the unchanged default path).

- [x] **Step 5: Run the full test suite**

Run: `cd cli && python -m pytest -v`
Expected: PASS — no regressions in registry, plans, or other emitter tests, since `--domain` only touches the target-emission branches and the whole-workspace path is unchanged when the flag is omitted.

- [x] **Step 6: Commit**

```bash
git add cli/src/modelable/commands/compile.py cli/tests/test_cli_compile.py
git commit -m "feat(compile): add repeatable --domain filter to scope target emission"
```

---

## Status: shipped (PR #157, merged)

All three tasks landed as planned. Code review on the PR surfaced two further fixes not in the original plan, both merged into the same branch before merge:

- **mypy baseline ratchet regen** (`cli/mypy-baseline.txt`): the `_pascalize` fix inserted 6 lines per file, shifting every downstream error's line number and tripping the line-number-keyed ratchet check. Regenerated the baseline — 463 errors before and after, pure shift, nothing new or resolved.
- **`--domain` cross-domain dangling-reference guard** (`cli/src/modelable/commands/compile.py`): the shipped Task 3 silently degraded output (lossy fallback types + `EMIT002` warnings, exit 0) when a requested domain's projection or field referenced a model in an excluded domain, instead of the compile-time error this plan's own "Out of scope" section called for. Added `_find_domain_scope_violations` to detect this before scoping the workspace and raise `click.ClickException` instead.
- A `ruff format` fixup for one unwrapped long line in the cross-domain guard.

## Out of scope (per design doc)

- Extending `--domain` filtering to `validate`, `diff`, or `docs`.
- Fixing `_pascalize`'s all-caps handling for Go, Java, Python, or TypeScript.
- Resolving `NamedType` references across an excluded domain when `--domain` is used — a requested domain referencing a type that lives only in an excluded domain should already be a compile-time dangling-reference error from `validate`; this plan does not touch that path.
- The ClickHouse `Row` enum-to-`String` coercion (design Finding 3) — no code change, downstream doc fix only, not part of this plan.
