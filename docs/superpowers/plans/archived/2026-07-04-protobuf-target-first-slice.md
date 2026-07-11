# Protobuf Target First Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a first usable `modelable compile --target protobuf` path that emits deterministic `.proto` files and a schema manifest for model and projection versions.

**Architecture:** Implement protobuf as a normal local artifact target beside JSON Schema, ODCS, and OpenLineage. Keep this first slice focused on `.proto` text and manifest generation from the existing `Workspace` IR; do not add new `.mdl` syntax, gRPC services, descriptor-set generation, or compatibility validation in this slice.

**Tech Stack:** Python 3.14, Click CLI, existing Modelable compiler IR, `EmittedArtifact`, pytest, ruff.

---

## Scope And Version Boundary

This is appropriate for Modelable 1.1 work. Modelable 1.0 shipped on 2026-06-28 with the then-current stable generated-artifact set, and protobuf/gRPC is listed in `ROADMAP.md` as a deferred candidate with an accepted design. This plan starts that 1.1 line by adding the protobuf artifact target only.

Out of scope for this first slice:

- `compile --target grpc`
- descriptor-set binary output
- primary-key and secondary-index syntax beyond existing `@key`
- `validate-compat --target protobuf`
- stable field-number reservation storage for deleted fields
- SDK wrappers

The first slice still needs deterministic field numbers for current fields. Use declaration order starting at `1` so generated output is reviewable. Reservation support must be added in the compatibility slice before protobuf is called stable for long-lived external contracts.

## File Structure

- Create `cli/src/modelable/emitters/protobuf.py`: all protobuf rendering, schema identity, and schema-manifest construction.
- Create `cli/tests/test_emit_protobuf.py`: focused emitter and CLI tests.
- Modify `cli/src/modelable/emitters/targets.py`: register `protobuf` as an implemented artifact target with default output `./dist/protobuf`.
- Modify `cli/src/modelable/commands/compile.py`: dispatch the new target and write `.proto`/`.json` artifacts.
- Modify `cli/tests/test_codegen_targets.py`: update target inventory and type mapping assertions.
- Modify `docs/cli-reference.md`, `docs/compiler-reference.md`, and `ROADMAP.md`: document the new target as a first 1.1 protobuf slice and record deferred gRPC/compat work.
- Modify `docs/maintainers.md`: add the protobuf focused test gate.

## Task 1: Register The Target With A Failing Inventory Test

**Files:**
- Modify: `cli/tests/test_codegen_targets.py`
- Modify: `cli/src/modelable/emitters/targets.py`

- [ ] **Step 1: Write the failing target-inventory test**

Update `test_codegen_formats_list_supported_and_deferred_targets` so the expected target list includes `"protobuf"` after `"odcs"`:

```python
    assert [target["name"] for target in targets] == [
        "json-schema",
        "markdown",
        "typescript",
        "csharp",
        "java",
        "python",
        "rust",
        "go",
        "sql-postgres",
        "sql-clickhouse",
        "dbt-yaml",
        "fhir-profile",
        "openmetadata",
        "openlineage",
        "odcs",
        "protobuf",
    ]
```

- [ ] **Step 2: Verify the test fails**

Run from `cli/`:

```bash
uv run pytest tests/test_codegen_targets.py::test_codegen_formats_list_supported_and_deferred_targets -q
```

Expected: failure showing the actual target list does not include `protobuf`.

- [ ] **Step 3: Register the minimal target**

Add this entry at the end of `CODEGEN_TARGETS` in `cli/src/modelable/emitters/targets.py`:

```python
    CodegenTarget(
        name="protobuf",
        description="Protocol Buffers schema artifacts and Modelable schema manifest",
        status="implemented",
        kind="artifact",
        default_out_dir=Path("./dist/protobuf"),
    ),
```

- [ ] **Step 4: Verify the target-inventory test passes**

Run from `cli/`:

```bash
uv run pytest tests/test_codegen_targets.py::test_codegen_formats_list_supported_and_deferred_targets -q
```

Expected: pass.

## Task 2: Emit Deterministic Protobuf For Entity Versions

**Files:**
- Create: `cli/src/modelable/emitters/protobuf.py`
- Create: `cli/tests/test_emit_protobuf.py`

- [ ] **Step 1: Write the failing entity emitter test**

Create `cli/tests/test_emit_protobuf.py` with this first test:

```python
from __future__ import annotations

import json

from modelable.compiler.workspace import load_workspace
from modelable.emitters.protobuf import emit_protobuf


def test_emit_protobuf_entity_proto_and_manifest(tmp_path):
    (tmp_path / "customer.mdl").write_text(
        """
domain customer {
  owner: "customer-team"

  entity Customer @ 1 (additive) {
    @key customerId: uuid
    email?: string
    status: enum(active, blocked)
    joinedAt?: timestamp
    score: decimal(12, 2)
    tags: array<string>
    avatar?: binary
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)

    artifacts = emit_protobuf(workspace, tmp_path / "out")

    proto = next(art for art in artifacts if art.path.name == "Customer.v1.proto")
    assert proto.target == "protobuf"
    assert proto.ref == "customer.Customer@1"
    assert proto.artifact_id == "customer.Customer.v1"
    assert proto.path == tmp_path / "out" / "customer" / "Customer.v1" / "Customer.v1.proto"
    assert proto.content == '''syntax = "proto3";

package modelable.customer.v1;

import "google/protobuf/timestamp.proto";

message Customer {
  string customer_id = 1;
  optional string email = 2;
  CustomerStatus status = 3;
  optional google.protobuf.Timestamp joined_at = 4;
  string score = 5;
  repeated string tags = 6;
  optional bytes avatar = 7;
}

enum CustomerStatus {
  CUSTOMER_STATUS_UNSPECIFIED = 0;
  CUSTOMER_STATUS_ACTIVE = 1;
  CUSTOMER_STATUS_BLOCKED = 2;
}
'''

    manifest = next(art for art in artifacts if art.path.name == "schema-manifest.json")
    manifest_doc = json.loads(manifest.content)
    assert manifest_doc["target"] == "protobuf"
    assert manifest_doc["schemas"][0]["ref"] == "customer.Customer@1"
    assert manifest_doc["schemas"][0]["schema_id"] == "modelable://customer/Customer/v1/protobuf"
    assert manifest_doc["schemas"][0]["fields"] == [
        {"name": "customerId", "proto_name": "customer_id", "number": 1, "type": "string", "key": True},
        {"name": "email", "proto_name": "email", "number": 2, "type": "optional string", "key": False},
        {"name": "status", "proto_name": "status", "number": 3, "type": "CustomerStatus", "key": False},
        {
            "name": "joinedAt",
            "proto_name": "joined_at",
            "number": 4,
            "type": "optional google.protobuf.Timestamp",
            "key": False,
        },
        {"name": "score", "proto_name": "score", "number": 5, "type": "string", "key": False},
        {"name": "tags", "proto_name": "tags", "number": 6, "type": "repeated string", "key": False},
        {"name": "avatar", "proto_name": "avatar", "number": 7, "type": "optional bytes", "key": False},
    ]
```

- [ ] **Step 2: Verify the test fails because the emitter is missing**

Run from `cli/`:

```bash
uv run pytest tests/test_emit_protobuf.py::test_emit_protobuf_entity_proto_and_manifest -q
```

Expected: failure with `ModuleNotFoundError: No module named 'modelable.emitters.protobuf'`.

- [ ] **Step 3: Add the minimal entity emitter**

Create `cli/src/modelable/emitters/protobuf.py` with helpers for:

- artifact path: `<out>/<domain>/<Name>.v<version>/<Name>.v<version>.proto`
- package name: `modelable.<domain>.v<version>` with non-alphanumeric characters normalized to `_`
- message name: original model name
- protobuf field name: lower snake case from the Modelable field name
- field numbers: declaration order starting at `1`
- enum names: `<Message><FieldNamePascal>`
- scalar mapping:
  - `string`, `uuid`, `date`, `time`, `duration`, and `decimal(p,s)` -> `string`
  - `int` -> `int64`
  - `float` -> `double`
  - `bool` -> `bool`
  - `timestamp` -> `google.protobuf.Timestamp`
  - `binary` -> `bytes`
  - `array<T>` -> `repeated <T>`
  - `enum(a,b)` -> generated enum
  - unsupported map/object/ref/named shapes -> `bytes` plus an artifact warning
- manifest path: `<out>/<domain>/<Name>.v<version>/schema-manifest.json`

- [ ] **Step 4: Verify the entity emitter test passes**

Run from `cli/`:

```bash
uv run pytest tests/test_emit_protobuf.py::test_emit_protobuf_entity_proto_and_manifest -q
```

Expected: pass.

## Task 3: Support Projection Versions

**Files:**
- Modify: `cli/tests/test_emit_protobuf.py`
- Modify: `cli/src/modelable/emitters/protobuf.py`

- [ ] **Step 1: Write the failing projection test**

Append this test to `cli/tests/test_emit_protobuf.py`:

```python
def test_emit_protobuf_projection_uses_resolved_source_field_types(tmp_path):
    (tmp_path / "customer.mdl").write_text(
        """
domain customer {
  owner: "customer-team"

  entity Customer @ 1 (additive) {
    @key customerId: uuid
    email: string
    joinedAt?: timestamp
  }

  projection CustomerSummary @ 1
    from customer.Customer @ 1 as c
  {
    customerId <- c.customerId
    email <- c.email
    joinedAt <- c.joinedAt
    displayName = c.email
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)

    artifacts = emit_protobuf(workspace, tmp_path / "out")

    proto = next(art for art in artifacts if art.ref == "customer.CustomerSummary@1" and art.path.suffix == ".proto")
    assert proto.path == tmp_path / "out" / "customer" / "CustomerSummary.v1" / "CustomerSummary.v1.proto"
    assert proto.content == '''syntax = "proto3";

package modelable.customer.v1;

import "google/protobuf/timestamp.proto";

message CustomerSummary {
  string customer_id = 1;
  string email = 2;
  google.protobuf.Timestamp joined_at = 3;
  string display_name = 4;
}
'''
```

- [ ] **Step 2: Verify the projection test fails**

Run from `cli/`:

```bash
uv run pytest tests/test_emit_protobuf.py::test_emit_protobuf_projection_uses_resolved_source_field_types -q
```

Expected: failure showing no projection artifact or unresolved field types.

- [ ] **Step 3: Resolve projection direct mappings**

Update the emitter to mirror the JSON Schema pattern:

- for `DirectMapping`, resolve the source model version with `resolve_model_ref`
- use the source field type and source field optionality
- for `ComputedMapping`, emit `string` for now and include manifest mapping metadata with `"mapping": "computed"`
- projection fields stay required unless the resolved direct source field is optional

- [ ] **Step 4: Verify projection support passes**

Run from `cli/`:

```bash
uv run pytest tests/test_emit_protobuf.py::test_emit_protobuf_projection_uses_resolved_source_field_types -q
```

Expected: pass.

## Task 4: Wire The Compile Command

**Files:**
- Modify: `cli/tests/test_emit_protobuf.py`
- Modify: `cli/src/modelable/commands/compile.py`

- [ ] **Step 1: Write the failing CLI test**

Append this test:

```python
from click.testing import CliRunner

from modelable.cli import cli


def test_compile_protobuf_writes_proto_and_manifest(tmp_path):
    mdl = tmp_path / "customer.mdl"
    mdl.write_text(
        """
domain customer {
  owner: "customer-team"

  entity Customer @ 1 (additive) {
    @key customerId: uuid
    email?: string
  }
}
""",
        encoding="utf-8",
    )

    out = tmp_path / "dist"
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli, ["compile", str(mdl), "--target", "protobuf", "--out", str(out)])

    assert result.exit_code == 0, result.output
    assert (out / "customer" / "Customer.v1" / "Customer.v1.proto").exists()
    assert (out / "customer" / "Customer.v1" / "schema-manifest.json").exists()
```

- [ ] **Step 2: Verify the CLI test fails**

Run from `cli/`:

```bash
uv run pytest tests/test_emit_protobuf.py::test_compile_protobuf_writes_proto_and_manifest -q
```

Expected: failure showing `protobuf` is not dispatched or no artifacts are written.

- [ ] **Step 3: Import and dispatch the emitter**

In `cli/src/modelable/commands/compile.py`:

```python
from modelable.emitters.protobuf import emit_protobuf
```

Add an `elif target == "protobuf":` branch that writes string artifacts exactly like `odcs`:

```python
    elif target == "protobuf":
        artifacts = emit_protobuf(workspace, output)
        for art in artifacts:
            assert isinstance(art.content, str)
            _write_artifact_text(art.path, art.content)
            _print_artifact_result(art)
        if not artifacts:
            console.print("[yellow]No artifacts generated.[/yellow]")
```

- [ ] **Step 4: Verify the CLI test passes**

Run from `cli/`:

```bash
uv run pytest tests/test_emit_protobuf.py::test_compile_protobuf_writes_proto_and_manifest -q
```

Expected: pass.

## Task 5: Document The First Slice

**Files:**
- Modify: `docs/cli-reference.md`
- Modify: `docs/compiler-reference.md`
- Modify: `docs/maintainers.md`
- Modify: `ROADMAP.md`

- [ ] **Step 1: Write the documentation edits**

Document these exact contract points:

- `compile --target protobuf` is implemented.
- It emits one `.proto` and one `schema-manifest.json` per model or projection version.
- Output layout is `<out>/<domain>/<Name>.v<version>/`.
- Field numbers are declaration-order deterministic in this first slice.
- Deleted-field reservations, descriptor sets, gRPC profile generation, and protobuf compatibility validation are deferred follow-up work before long-lived protobuf contracts are considered stable.
- Maintainer gate: run `uv run pytest tests/test_emit_protobuf.py tests/test_codegen_targets.py -q` from `cli/` for protobuf target changes.

- [ ] **Step 2: Verify docs mention the new target**

Run from repo root:

```bash
rg -n "compile --target protobuf|protobuf target|test_emit_protobuf" ROADMAP.md docs
```

Expected: matches in the CLI reference, compiler reference, maintainer docs, and roadmap.

## Task 6: Final Verification

**Files:**
- All touched files

- [ ] **Step 1: Run focused tests**

Run from `cli/`:

```bash
uv run pytest tests/test_emit_protobuf.py tests/test_codegen_targets.py --tb=short -q
```

Expected: pass.

- [ ] **Step 2: Run required pre-commit gate**

Run from `cli/`:

```bash
uv run ruff format .
uv run ruff check .
uv run pytest --tb=short
```

Expected: all pass cleanly.

- [ ] **Step 3: Inspect the final diff**

Run from repo root:

```bash
git diff --stat
git diff -- docs/superpowers/plans/2026-07-04-protobuf-target-first-slice.md cli/src/modelable/emitters/protobuf.py cli/src/modelable/commands/compile.py cli/src/modelable/emitters/targets.py cli/tests/test_emit_protobuf.py cli/tests/test_codegen_targets.py docs/cli-reference.md docs/compiler-reference.md docs/maintainers.md ROADMAP.md
```

Expected: diff contains only the protobuf target first slice and documentation.

## Self-Review

Spec coverage:

- Covered: `compile --target protobuf`, deterministic `.proto`, schema manifest, package/message/field/type mappings, optional/repeated fields, timestamps, ids, decimals, projections, and generated artifact tests.
- Deferred by design: descriptor sets, gRPC target, new index metadata syntax, compatibility validation, stable reservations for deleted fields, and Scalable fixture registration.

Placeholder scan:

- No placeholder tasks are left. Deferred work is explicitly out of this first slice.

Type consistency:

- The plan uses the existing `emit_<target>(workspace, out_dir) -> list[EmittedArtifact]` pattern.
- Manifest content is serialized as a string artifact so the existing compile writer can stay simple.
