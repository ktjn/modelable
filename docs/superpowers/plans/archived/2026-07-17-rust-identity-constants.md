# Rust Identity Constants Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate stable Rust associated constants for allocated semantic registry IDs and for every model and projection's declared version and canonical Modelable signature.

**Architecture:** Keep identity generation inside the existing Rust emitter. The compile path continues to pass ledger allocations into `emit_rust()`; semantic newtypes render the supplied allocation, while model and projection emitters call the existing canonical `compute_version_signature()` function and render its digest as a dependency-free `[u8; 32]`. Identity `impl` blocks sit immediately after their owning top-level struct, and storage-gated projections apply the same feature gate to the `impl`.

**Tech Stack:** Python 3.14+, Pydantic parser IR, pytest, Ruff, mypy baseline ratchet, MkDocs, generated Rust validated with Cargo in Docker.

## Global Constraints

- Implement the accepted design in `docs/superpowers/specs/archived/2026-07-17-rust-identity-constants-design.md`; do not widen this slice into Protobuf, descriptor-set, inspect, or Scalable changes.
- `REGISTRY_ID` comes only from an explicit allocation supplied for a `registry: true` semantic type. Never invent a sentinel.
- `SCHEMA_CONTENT_SIGNATURE` must come only from `compute_version_signature()`; do not use `EmittedArtifact.content_hash` or a target-specific wire fingerprint.
- Emit constants only on top-level semantic, model, and projection types. Nested structs and enums receive no identity constants.
- Preserve the current `/// registry id: N` comment.
- From `cli/`, run all four repository gates before every commit:

  ```powershell
  uv run ruff format .
  uv run ruff check .
  uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
  uv run pytest --tb=short
  ```

- If the mypy ratchet reports only shifted existing errors, regenerate `cli/mypy-baseline.txt` exactly as described in `AGENTS.md`; fix genuine new errors instead of baselining them.
- Keep this plan and its design spec in the active directories until the implementation PR merges. Archive both in a post-merge follow-up, not in this implementation branch.

---

## Task 1: Emit allocated registry IDs as associated constants

**Files:**

- Modify: `cli/tests/test_emit_rust.py`
- Modify: `cli/tests/test_cli.py`
- Modify: `cli/src/modelable/emitters/rust.py`

- [ ] **Step 1: Strengthen direct-emitter tests for the three allocation cases**

In `cli/tests/test_emit_rust.py`, rename
`test_emit_rust_semantic_type_with_allocated_id_gets_doc_comment` to
`test_emit_rust_registry_semantic_type_with_allocated_id_gets_constant` and
require the exact generated API:

```python
assert "/// registry id: 1" in art.content
assert (
    "impl SchemaId {\n"
    "    pub const REGISTRY_ID: u32 = 1;\n"
    "}"
) in art.content
```

Rename
`test_emit_rust_semantic_type_without_allocated_id_has_no_doc_comment` to
`test_emit_rust_registry_semantic_type_without_allocated_id_has_no_identity`
and assert both surfaces are absent:

```python
assert "registry id" not in art.content
assert "pub const REGISTRY_ID" not in art.content
```

Add a non-registry case that deliberately supplies an entry with the same
qualified name:

```python
def test_emit_rust_non_registry_semantic_type_ignores_allocated_id(tmp_path):
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
    artifacts = emit_rust(workspace, tmp_path / "out", registry_ids={"platform.ModuleId": 7})
    art = next(a for a in artifacts if a.ref == "platform.ModuleId")
    assert "registry id" not in art.content
    assert "pub const REGISTRY_ID" not in art.content
```

- [ ] **Step 2: Add an end-to-end compile assertion**

In `cli/tests/test_cli.py`,
`test_compile_allocates_and_persists_registry_ids`, read the emitted file after
the existing lock assertion:

```python
generated = (tmp_path / "dist" / "platform" / "schema_id.rs").read_text(encoding="utf-8")
assert "pub const REGISTRY_ID: u32 = 1;" in generated
```

This verifies that the CLI's ledger allocation reaches generated Rust, not
only that the direct emitter can render a manually supplied map.

- [ ] **Step 3: Run the focused tests and confirm the expected failures**

From `cli/`:

```powershell
uv run pytest tests/test_emit_rust.py -k "registry_semantic or non_registry_semantic" --tb=short
uv run pytest tests/test_cli.py::test_compile_allocates_and_persists_registry_ids --tb=short
```

Expected: the allocated cases fail because `REGISTRY_ID` is not emitted yet.
The omission cases should already pass.

- [ ] **Step 4: Add a small renderer and integrate it**

In `cli/src/modelable/emitters/rust.py`, add:

```python
def _render_registry_id_impl(type_name: str, allocated_id: int) -> list[str]:
    return [
        "",
        f"impl {type_name} {{",
        f"    pub const REGISTRY_ID: u32 = {allocated_id};",
        "}",
    ]
```

In `_emit_semantic_type()`, immediately after the generated tuple-struct line,
extend the output only when the allocation is present:

```python
lines.append(f"pub struct {struct_name}(pub {rust_type});")
if allocated_id is not None:
    lines.extend(_render_registry_id_impl(struct_name, allocated_id))
lines.append("")
lines.append(f"impl From<{rust_type}> for {struct_name} {{")
```

Do not change `emit_rust()` allocation filtering: its existing
`if decl.registry` check is the boundary that prevents ordinary semantic
types from consuming registry-map entries.

- [ ] **Step 5: Re-run focused tests**

From `cli/`:

```powershell
uv run pytest tests/test_emit_rust.py -k "registry_semantic or non_registry_semantic" --tb=short
uv run pytest tests/test_cli.py::test_compile_allocates_and_persists_registry_ids --tb=short
```

Expected: all selected tests pass.

- [ ] **Step 6: Run the mandatory pre-commit gates**

From `cli/`:

```powershell
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
```

Expected: all four commands pass cleanly.

- [ ] **Step 7: Commit Task 1**

```powershell
git add cli/src/modelable/emitters/rust.py cli/tests/test_emit_rust.py cli/tests/test_cli.py cli/mypy-baseline.txt
git commit -m "feat: emit Rust registry ID constants"
```

`cli/mypy-baseline.txt` should be staged only if line-number shifts required a
mechanical baseline refresh.

---

## Task 2: Emit canonical model and projection identity constants

**Files:**

- Modify: `cli/tests/test_emit_rust.py`
- Modify: `cli/tests/test_codegen_docker_smoke.py`
- Modify: `cli/src/modelable/emitters/rust.py`

- [ ] **Step 1: Add test helpers and canonical identity assertions**

At the top of `cli/tests/test_emit_rust.py`, add:

```python
import re

import pytest

from modelable.registry.signature import compute_version_signature
```

Add this test-only parser near the imports:

```python
def _emitted_schema_signature(content: str) -> str:
    match = re.search(
        r"SCHEMA_CONTENT_SIGNATURE: \[u8; 32\] = \[(.*?)\];",
        content,
        flags=re.DOTALL,
    )
    assert match is not None
    byte_literals = re.findall(r"0x([0-9a-f]{2})", match.group(1))
    assert len(byte_literals) == 32
    return "".join(byte_literals)
```

In `test_emit_rust_model_and_projection`, obtain the parsed domain and versions:

```python
domain = workspace.mdl.domains[0]
model_version = domain.models["Customer"][0]
projection_version = domain.projections["CustomerView"][0]
```

After the model's top-level struct assertion, add:

```python
assert "pub const SCHEMA_VERSION: u32 = 1;" in model_art.content
assert _emitted_schema_signature(model_art.content) == compute_version_signature(
    "customer", "Customer", model_version
)
assert model_art.content.index("pub struct CustomerCustomerV1") < model_art.content.index(
    "impl CustomerCustomerV1"
)
assert model_art.content.index("impl CustomerCustomerV1") < model_art.content.index(
    "pub struct CustomerCustomerV1Address"
)
```

After the projection's top-level struct assertion, add:

```python
assert "pub const SCHEMA_VERSION: u32 = 1;" in proj_art.content
assert _emitted_schema_signature(proj_art.content) == compute_version_signature(
    "customer", "CustomerView", projection_version
)
assert proj_art.content.index("pub struct CustomerCustomerViewV1") < proj_art.content.index(
    "impl CustomerCustomerViewV1"
)
assert proj_art.content.index("impl CustomerCustomerViewV1") < proj_art.content.index(
    "pub struct CustomerCustomerViewV1Address"
)
```

These assertions cover the declared version, exact canonical digest, 32-byte
representation, and placement before nested definitions for both artifact
kinds.

- [ ] **Step 2: Add malformed-digest invariant tests**

Import the private conversion helper that will be introduced:

```python
from modelable.emitters.rust import _signature_bytes, emit_rust
```

Add:

```python
@pytest.mark.parametrize("signature", ["not-hex", "00" * 31, "00" * 33])
def test_rust_signature_bytes_rejects_malformed_digest(signature: str):
    with pytest.raises(ValueError, match="canonical Modelable signature"):
        _signature_bytes(signature)
```

- [ ] **Step 3: Make the existing Rust Docker smoke compile the constants**

In the Rust test body written by
`cli/tests/test_codegen_docker_smoke.py::_write_rust_smoke`, add after the
existing display-name assertion:

```rust
assert_eq!(CustomerCustomerV1::SCHEMA_VERSION, 1);
assert_eq!(CustomerCustomerV1::SCHEMA_CONTENT_SIGNATURE.len(), 32);
assert_eq!(CustomerCustomerViewV1::SCHEMA_VERSION, 1);
assert_eq!(CustomerCustomerViewV1::SCHEMA_CONTENT_SIGNATURE.len(), 32);
```

This is a compilation check for the exact public associated-constant API and
its array type.

- [ ] **Step 4: Run the focused unit test and confirm it fails**

From `cli/`:

```powershell
uv run pytest tests/test_emit_rust.py::test_emit_rust_model_and_projection tests/test_emit_rust.py::test_rust_signature_bytes_rejects_malformed_digest --tb=short
```

Expected: test collection or assertions fail because `_signature_bytes` and
the model/projection constants do not exist yet.

- [ ] **Step 5: Implement strict digest conversion and rendering**

In `cli/src/modelable/emitters/rust.py`, import the canonical function:

```python
from modelable.registry.signature import compute_version_signature
```

Add these helpers near the existing Rust render helpers:

```python
def _signature_bytes(signature: str) -> bytes:
    try:
        raw = bytes.fromhex(signature)
    except ValueError as exc:
        raise ValueError("canonical Modelable signature must be hexadecimal") from exc
    if len(raw) != 32:
        raise ValueError("canonical Modelable signature must contain exactly 32 bytes")
    return raw


def _render_schema_identity_impl(
    type_name: str,
    version: int,
    signature: str,
    *,
    storage_gated: bool = False,
) -> list[str]:
    values = _signature_bytes(signature)
    lines = [""]
    if storage_gated:
        lines.append('#[cfg(feature = "storage")]')
    lines.extend(
        [
            f"impl {type_name} {{",
            f"    pub const SCHEMA_VERSION: u32 = {version};",
            "    pub const SCHEMA_CONTENT_SIGNATURE: [u8; 32] = [",
        ]
    )
    for offset in range(0, len(values), 8):
        row = ", ".join(f"0x{value:02x}" for value in values[offset : offset + 8])
        lines.append(f"        {row},")
    lines.extend(["    ];", "}"])
    return lines
```

The strict helper ensures invalid hex and valid hex of the wrong size fail
before malformed Rust can be emitted. Eight literals per row keeps output
stable and readable.

- [ ] **Step 6: Integrate model identity immediately after the top-level struct**

In `_emit_model()`, after `_render_struct_definition()` and before nested
definitions:

```python
lines.extend(_render_struct_definition(type_name, field_specs))
lines.extend(
    _render_schema_identity_impl(
        type_name,
        version.version,
        compute_version_signature(domain.name, model_name, version),
    )
)
lines.extend(_render_nested_definitions(nested_definitions))
```

- [ ] **Step 7: Integrate projection identity with matching storage gating**

In `_emit_projection()`, after `_render_struct_definition()` and before nested
definitions:

```python
lines.extend(
    _render_struct_definition(type_name, field_specs, extra_derives=extra_derives, storage_gated=storage_gated)
)
lines.extend(
    _render_schema_identity_impl(
        type_name,
        version.version,
        compute_version_signature(domain.name, projection_name, version),
        storage_gated=storage_gated,
    )
)
lines.extend(_render_nested_definitions(nested_definitions))
```

The matching `#[cfg(feature = "storage")]` is required: otherwise the `impl`
would reference a projection struct that is absent when the storage feature is
disabled.

- [ ] **Step 8: Re-run behavior and determinism tests**

From `cli/`:

```powershell
uv run pytest tests/test_emit_rust.py::test_emit_rust_model_and_projection tests/test_emit_rust.py::test_rust_signature_bytes_rejects_malformed_digest --tb=short
uv run pytest tests/test_emit_rust.py::test_emit_rust_named_type_use_statements_are_hash_seed_independent --tb=short
```

Expected: all selected tests pass. The cross-process test proves the newly
included signature output remains byte-identical across different hash seeds.

- [ ] **Step 9: Run the Rust generated-output Docker smoke**

From `cli/`, with Docker available:

```powershell
$env:MODELABLE_DOCKER_SMOKE = "1"
uv run pytest tests/test_codegen_docker_smoke.py -k "rust" --tb=short
Remove-Item Env:MODELABLE_DOCKER_SMOKE
```

Expected: the Rust case builds and tests successfully in the pinned Rust
container. If Docker is unavailable, record that limitation explicitly and do
not describe this smoke as passing.

- [ ] **Step 10: Run the mandatory pre-commit gates**

From `cli/`:

```powershell
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
```

Expected: all four commands pass cleanly.

- [ ] **Step 11: Commit Task 2**

```powershell
git add cli/src/modelable/emitters/rust.py cli/tests/test_emit_rust.py cli/tests/test_codegen_docker_smoke.py cli/mypy-baseline.txt
git commit -m "feat: emit Rust schema identity constants"
```

Again, stage the baseline only if exact line shifts required it.

---

## Task 3: Document the generated API and close the roadmap slice

**Files:**

- Modify: `docs/compiler-reference.md`
- Modify: `CHANGELOG.md`
- Modify: `ROADMAP.md`

- [ ] **Step 1: Update the compiler reference**

In `docs/compiler-reference.md`, extend the Rust semantic-type description to
state that an allocated registry semantic newtype exposes both the preserved
doc comment and:

```rust
RuntimeKernelConfigSchemaId::REGISTRY_ID
```

Add a neighboring paragraph explaining that every generated Rust model and
projection exposes:

```rust
RuntimeKernelConfigV1::SCHEMA_VERSION
RuntimeKernelConfigV1::SCHEMA_CONTENT_SIGNATURE
```

Document the types as `u32` and `[u8; 32]`, identify
`compute_version_signature()` as the canonical signature source, and state
that generated Rust text hashes and Protobuf wire fingerprints are distinct
target-specific values.

- [ ] **Step 2: Add an Unreleased changelog entry**

Under `## [Unreleased]` in `CHANGELOG.md`, add:

```markdown
### Added

- Generated Rust registry-backed semantic newtypes now expose their allocated
  ID as `REGISTRY_ID`. Generated Rust models and projections expose
  `SCHEMA_VERSION` and the canonical Modelable signature as a dependency-free
  `[u8; 32]` `SCHEMA_CONTENT_SIGNATURE`.
```

- [ ] **Step 3: Mark only Priority 1 item 1 shipped**

In `ROADMAP.md`, change item 1's heading to:

```markdown
1. **Shipped: emit stable Rust identity constants.**
```

Rewrite its body in past tense and identify item 2, semantic identity in
Protobuf, as the next dependency-ordered slice. Do not mark any part of items
2–5 complete.

- [ ] **Step 4: Check the documentation diff for scope and stale wording**

From the repository root:

```powershell
git diff --check
rg -n "REGISTRY_ID|SCHEMA_VERSION|SCHEMA_CONTENT_SIGNATURE|Shipped: emit stable Rust identity constants|Carry semantic identity into Protobuf" ROADMAP.md CHANGELOG.md docs/compiler-reference.md
```

Expected: no whitespace errors; all three public constants are documented;
only roadmap item 1 says `Shipped`.

- [ ] **Step 5: Build documentation strictly**

From the repository root:

```powershell
uvx --from mkdocs==1.6.1 --with mkdocs-material==9.7.6 mkdocs build --strict
```

Expected: the strict build succeeds without warnings or broken links.

- [ ] **Step 6: Run the mandatory pre-commit gates**

From `cli/`:

```powershell
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
```

Expected: all four commands pass cleanly.

- [ ] **Step 7: Commit Task 3**

From the repository root:

```powershell
git add docs/compiler-reference.md CHANGELOG.md ROADMAP.md
git commit -m "docs: document Rust identity constants"
```

---

## Task 4: Final branch verification and publication handoff

**Files:**

- Verify only; do not archive the active plan or spec before merge.

- [ ] **Step 1: Inspect the complete branch diff**

From the repository root:

```powershell
git status --short
git diff --check main...HEAD
git diff --stat main...HEAD
git log --oneline main..HEAD
```

Expected: a clean worktree, no whitespace errors, and only the accepted Rust
identity slice plus its design/plan documentation.

- [ ] **Step 2: Re-run the strict docs build and mandatory gates**

From the repository root:

```powershell
uvx --from mkdocs==1.6.1 --with mkdocs-material==9.7.6 mkdocs build --strict
```

Then from `cli/`:

```powershell
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
```

Expected: strict docs and all four repository gates pass from the final branch
state.

- [ ] **Step 3: Re-run the Rust Docker smoke from the final branch state**

From `cli/`, with Docker available:

```powershell
$env:MODELABLE_DOCKER_SMOKE = "1"
uv run pytest tests/test_codegen_docker_smoke.py -k "rust" --tb=short
Remove-Item Env:MODELABLE_DOCKER_SMOKE
```

Expected: the generated Rust model and projection compile and their associated
constants are usable. Record an unavailable Docker daemon as an unverified
gate, not a pass.

- [ ] **Step 4: Prepare the PR contract**

The PR summary should state:

- allocated registry semantic types now expose `REGISTRY_ID`;
- models and projections expose `SCHEMA_VERSION` and canonical
  `SCHEMA_CONTENT_SIGNATURE`;
- storage-gated projections preserve valid feature-gated Rust;
- exact canonical-signature, omission, determinism, CLI ledger, and generated
  Rust compilation coverage were added; and
- roadmap Priority 1 item 1 is shipped, with Protobuf semantic identity next.

Include the exact final verification results. Do not use `Closes #N` unless a
live GitHub issue was explicitly added to this implementation's scope.

- [ ] **Step 5: Archive after merge**

After the implementation PR merges to `main`, move:

```text
docs/superpowers/specs/2026-07-17-rust-identity-constants-design.md
docs/superpowers/plans/2026-07-17-rust-identity-constants.md
```

to:

```text
docs/superpowers/specs/archived/2026-07-17-rust-identity-constants-design.md
docs/superpowers/plans/archived/2026-07-17-rust-identity-constants.md
```

Perform that archive bookkeeping in the merge PR if still possible, or in a
prompt follow-up PR immediately after merge.
