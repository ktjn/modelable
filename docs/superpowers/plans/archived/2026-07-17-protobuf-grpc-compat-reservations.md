# Protobuf and gRPC Compatibility Reservations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add source-level Protobuf reservations and dependency-free `validate-compat --target protobuf|grpc` validation.

**Architecture:** Extend the parser/IR with version-local Protobuf reservations, then teach the Protobuf emitter to render and manifest those reservations. Add a target-compatibility module that compares generated manifests in memory, and expose it through a new top-level CLI command. Documentation closes the loop by marking the remaining wire-contract enforcement slice as shipped while leaving field pinning, enum reservations, and rebuild declarations as follow-ups.

**Tech Stack:** Python 3.14, Click, Lark grammar, Pydantic IR models, existing Protobuf/gRPC emitters, pytest.

## Global Constraints

- Do not require `protoc` for compatibility validation.
- Keep descriptor generation opt-in and compile-only via existing `--descriptor-set`.
- Do not add field-number pinning syntax in this slice.
- Do not add enum reservation syntax in this slice.
- Do not add rebuild or migration declaration syntax in this slice.
- Preserve existing default Protobuf/gRPC compile output unless reservations are declared.
- Before every commit, run these commands from `cli/`:
  - `uv run ruff format .`
  - `uv run ruff check .`
  - `uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes`
  - `uv run pytest --tb=short`

---

## Task 1: Parser and IR Support for Protobuf Reservations

**Files:**
- Modify: `cli/src/modelable/grammar/modelable.lark`
- Modify: `cli/src/modelable/parser/ir.py`
- Modify: `cli/src/modelable/parser/__init__.py`
- Modify: `cli/src/modelable/parser/transformer.py`
- Create: `cli/tests/test_protobuf_reservations.py`

**Interfaces:**
- Produces: `ProtobufReservations(numbers: list[int], names: list[str])`
- Produces: `ModelVersion.protobuf_reservations: ProtobufReservations | None`
- Produces: `ProjectionVersion.protobuf_reservations: ProtobufReservations | None`
- Consumed by: Task 2 Protobuf emitter and Task 3 compatibility validator.

- [ ] **Step 1: Add failing parser tests for model and projection reservations**

Create `cli/tests/test_protobuf_reservations.py`:

```python
from __future__ import annotations

import pytest

from modelable.parser import parse_mdl


def test_parse_model_protobuf_reservations():
    mdl = parse_mdl(
        """
domain billing {
  owner: "billing"

  entity Customer @ 2 (additive) {
    reserved protobuf {
      numbers: [3, 7]
      names: ["legacy_status", "old_status"]
    }

    @key customerId: uuid
    displayName?: string
  }
}
"""
    )

    customer = mdl.domains[0].models["Customer"][0]
    assert customer.protobuf_reservations is not None
    assert customer.protobuf_reservations.numbers == [3, 7]
    assert customer.protobuf_reservations.names == ["legacy_status", "old_status"]


def test_parse_projection_protobuf_reservations():
    mdl = parse_mdl(
        """
domain billing {
  owner: "billing"

  entity Customer @ 1 (additive) {
    @key customerId: uuid
    status: string
  }

  projection CustomerView @ 2 from billing.Customer@1 as c {
    reserved protobuf {
      numbers: [2]
      names: ["status"]
    }

    customerId <- c.customerId
  }
}
"""
    )

    projection = mdl.domains[0].projections["CustomerView"][0]
    assert projection.protobuf_reservations is not None
    assert projection.protobuf_reservations.numbers == [2]
    assert projection.protobuf_reservations.names == ["status"]
```

- [ ] **Step 2: Add failing validation tests for duplicate and empty reservations**

Append:

```python
def test_reject_duplicate_protobuf_reservation_numbers():
    with pytest.raises(ValueError, match="duplicate protobuf reservation number"):
        parse_mdl(
            """
domain billing {
  owner: "billing"
  entity Customer @ 2 (additive) {
    reserved protobuf {
      numbers: [3, 3]
    }
    @key customerId: uuid
  }
}
"""
        )


def test_reject_empty_protobuf_reservation_block():
    with pytest.raises(ValueError, match="must reserve at least one number or name"):
        parse_mdl(
            """
domain billing {
  owner: "billing"
  entity Customer @ 2 (additive) {
    reserved protobuf {
    }
    @key customerId: uuid
  }
}
"""
        )
```

- [ ] **Step 3: Run tests and verify failure**

Run from `cli/`:

```powershell
uv run pytest tests/test_protobuf_reservations.py -q
```

Expected: parser failure because `reserved protobuf` is not in the grammar.

- [ ] **Step 4: Add grammar productions**

In `cli/src/modelable/grammar/modelable.lark`, change:

```lark
model_body_item: field_decl
               | access_block
```

to:

```lark
model_body_item: field_decl
               | access_block
               | reservation_block
```

Change:

```lark
projection_body_item: proj_field
                    | access_block
                    | subscription_block
                    | generate_block
                    | materialisation_block
```

to:

```lark
projection_body_item: proj_field
                    | access_block
                    | subscription_block
                    | generate_block
                    | materialisation_block
                    | reservation_block
```

Add near the model/projection shared grammar:

```lark
reservation_block: "reserved" "protobuf" "{" reservation_item* "}"
reservation_item: reserved_numbers | reserved_names
reserved_numbers: "numbers" ":" "[" INT ("," INT)* "]"
reserved_names: "names" ":" "[" ESCAPED_STRING ("," ESCAPED_STRING)* "]"
```

- [ ] **Step 5: Add IR model and version fields**

In `cli/src/modelable/parser/ir.py`, add before `ModelVersion`:

```python
class ProtobufReservations(BaseModel):
    numbers: list[int] = Field(default_factory=list)
    names: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate(self) -> ProtobufReservations:
        if not self.numbers and not self.names:
            raise ValueError("protobuf reservations must reserve at least one number or name")
        seen_numbers: set[int] = set()
        for number in self.numbers:
            if number <= 0:
                raise ValueError("protobuf reservation numbers must be positive")
            if number in seen_numbers:
                raise ValueError(f"duplicate protobuf reservation number {number}")
            seen_numbers.add(number)
        seen_names: set[str] = set()
        for name in self.names:
            if name in seen_names:
                raise ValueError(f"duplicate protobuf reservation name {name}")
            seen_names.add(name)
        return self
```

Add to `ModelVersion`:

```python
protobuf_reservations: ProtobufReservations | None = None
```

Add the same field to `ProjectionVersion`.

Export `ProtobufReservations` from `cli/src/modelable/parser/__init__.py`.

- [ ] **Step 6: Add transformer support**

In `cli/src/modelable/parser/transformer.py`, import `ProtobufReservations`.

Add transformer methods:

```python
def reserved_numbers(self, items: list[object]) -> tuple[str, list[int]]:
    return ("numbers", [int(item) for item in items])


def reserved_names(self, items: list[object]) -> tuple[str, list[str]]:
    return ("names", [_unquote(str(item)) for item in items])


def reservation_item(self, items: list[object]) -> object:
    return items[0]


def reservation_block(self, items: list[object]) -> ProtobufReservations:
    parts: dict[str, list[int] | list[str]] = {}
    for item in items:
        if isinstance(item, tuple):
            parts[item[0]] = item[1]
    return ProtobufReservations(
        numbers=parts.get("numbers", []),  # type: ignore[arg-type]
        names=parts.get("names", []),  # type: ignore[arg-type]
    )
```

In `model_decl`, collect the reservation:

```python
reservation = next((item for item in items[body_start:] if isinstance(item, ProtobufReservations)), None)
```

Pass it to `ModelVersion(protobuf_reservations=reservation, ...)`.

In `projection_decl`, collect the reservation from projection body items and pass it to `ProjectionVersion`.

- [ ] **Step 7: Run focused parser tests**

Run from `cli/`:

```powershell
uv run pytest tests/test_protobuf_reservations.py -q
```

Expected: all Task 1 tests pass.

- [ ] **Step 8: Run required gate and commit Task 1**

Run from `cli/`:

```powershell
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
```

Commit from repo root:

```powershell
git add cli/src/modelable/grammar/modelable.lark cli/src/modelable/parser/ir.py cli/src/modelable/parser/__init__.py cli/src/modelable/parser/transformer.py cli/tests/test_protobuf_reservations.py
git commit -m "feat: parse protobuf reservations"
```

## Task 2: Protobuf Emitter Reservations and Manifest Metadata

**Files:**
- Modify: `cli/src/modelable/emitters/protobuf.py`
- Modify: `cli/tests/test_protobuf_reservations.py`
- Modify: `cli/tests/test_emit_protobuf.py`

**Interfaces:**
- Consumes: `ModelVersion.protobuf_reservations`
- Consumes: `ProjectionVersion.protobuf_reservations`
- Produces: `reserved ...;` declarations in `.proto`
- Produces: manifest key `reservations: {"numbers": list[int], "names": list[str]}`
- Produces: `schema_fingerprint` includes reservations.
- Consumed by: Task 3 compatibility validator.

- [ ] **Step 1: Add failing emitter tests**

Append to `cli/tests/test_protobuf_reservations.py`:

```python
import json
from pathlib import Path

from modelable.compiler.workspace import load_workspace
from modelable.emitters.protobuf import emit_protobuf


def test_emit_protobuf_renders_reserved_numbers_and_names(tmp_path):
    source = tmp_path / "model.mdl"
    source.write_text(
        """
domain billing {
  owner: "billing"
  entity Customer @ 2 (additive) {
    reserved protobuf {
      numbers: [3, 7]
      names: ["legacy_status"]
    }
    @key customerId: uuid
  }
}
""",
        encoding="utf-8",
    )
    artifacts = emit_protobuf(load_workspace(source), tmp_path / "out")
    proto = next(artifact for artifact in artifacts if artifact.path.name == "Customer.v2.proto")

    assert '  reserved 3, 7;' in proto.content
    assert '  reserved "legacy_status";' in proto.content


def test_emit_protobuf_manifest_records_reservations_and_fingerprint_changes(tmp_path):
    source = tmp_path / "model.mdl"
    source.write_text(
        """
domain billing {
  owner: "billing"
  entity Customer @ 2 (additive) {
    reserved protobuf {
      numbers: [3]
      names: ["legacy_status"]
    }
    @key customerId: uuid
  }
}
""",
        encoding="utf-8",
    )
    artifacts = emit_protobuf(load_workspace(source), tmp_path / "out")
    manifest = next(artifact for artifact in artifacts if artifact.path.name == "schema-manifest.json")
    schema = json.loads(manifest.content)["schemas"][0]

    assert schema["reservations"] == {"numbers": [3], "names": ["legacy_status"]}
    assert "reservations" in schema["schema_fingerprint"] or isinstance(schema["schema_fingerprint"], str)
```

Append a collision test:

```python
def test_emit_protobuf_rejects_field_colliding_with_reserved_number(tmp_path):
    source = tmp_path / "model.mdl"
    source.write_text(
        """
domain billing {
  owner: "billing"
  entity Customer @ 2 (additive) {
    reserved protobuf {
      numbers: [2]
    }
    @key customerId: uuid
    displayName: string
  }
}
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="reserved protobuf field number 2"):
        emit_protobuf(load_workspace(source), tmp_path / "out")
```

- [ ] **Step 2: Run tests and verify failure**

Run from `cli/`:

```powershell
uv run pytest tests/test_protobuf_reservations.py -k "emit_protobuf" -q
```

Expected: failures because emitter ignores reservations.

- [ ] **Step 3: Extend internal emitter data**

In `cli/src/modelable/emitters/protobuf.py`, import `ProtobufReservations`.

Add `reservations: ProtobufReservations | None` to `_render_proto(...)` and `_manifest_json(...)` signatures.

Pass `version.protobuf_reservations` from `_emit_model_version` and `_emit_projection_version`.

- [ ] **Step 4: Validate same-version reservation collisions**

Add helper:

```python
def _validate_reservations(fields: list[_ProtoField], reservations: ProtobufReservations | None, *, ref: str) -> None:
    if reservations is None:
        return
    reserved_numbers = set(reservations.numbers)
    reserved_names = set(reservations.names)
    for field in fields:
        if field.number in reserved_numbers:
            raise ValueError(f"{ref}: field {field.source_name} uses reserved protobuf field number {field.number}")
        if field.source_name in reserved_names or field.proto_name in reserved_names:
            raise ValueError(f"{ref}: field {field.source_name} uses reserved protobuf field name {field.proto_name}")
```

Call this before rendering/manifest creation for models and projections.

- [ ] **Step 5: Render reservation lines**

Add helper:

```python
def _reservation_lines(reservations: ProtobufReservations | None) -> list[str]:
    if reservations is None:
        return []
    lines: list[str] = []
    if reservations.numbers:
        lines.append(f"  reserved {', '.join(str(number) for number in reservations.numbers)};")
    if reservations.names:
        names = ", ".join(json.dumps(name) for name in reservations.names)
        lines.append(f"  reserved {names};")
    if lines:
        lines.append("")
    return lines
```

In `_render_proto`, after `message ... {`, extend with `_reservation_lines(reservations)` before field lines.

- [ ] **Step 6: Add manifest metadata and fingerprint input**

In `_manifest_json`, after `fields`, add:

```python
if version.protobuf_reservations is not None:
    schema_entry["reservations"] = _manifest_reservations(version.protobuf_reservations)
```

Add:

```python
def _manifest_reservations(reservations: ProtobufReservations) -> dict[str, object]:
    return {
        "numbers": list(reservations.numbers),
        "names": list(reservations.names),
    }
```

In `_schema_fingerprint(...)`, accept `reservations` and include:

```python
if reservations is not None:
    normalized["reservations"] = _manifest_reservations(reservations)
```

- [ ] **Step 7: Strengthen fingerprint test**

Replace the weak fingerprint assertion with:

```python
without_reservations = source.with_name("without.mdl")
without_reservations.write_text(
    """
domain billing {
  owner: "billing"
  entity Customer @ 2 (additive) {
    @key customerId: uuid
  }
}
""",
    encoding="utf-8",
)
without_manifest = next(
    artifact for artifact in emit_protobuf(load_workspace(without_reservations), tmp_path / "without")
    if artifact.path.name == "schema-manifest.json"
)
assert json.loads(without_manifest.content)["schemas"][0]["schema_fingerprint"] != schema["schema_fingerprint"]
```

- [ ] **Step 8: Run focused emitter tests**

Run from `cli/`:

```powershell
uv run pytest tests/test_protobuf_reservations.py tests/test_emit_protobuf.py --tb=short -q
```

Expected: all pass.

- [ ] **Step 9: Run required gate and commit Task 2**

Run from `cli/`:

```powershell
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
```

Commit:

```powershell
git add cli/src/modelable/emitters/protobuf.py cli/tests/test_protobuf_reservations.py cli/tests/test_emit_protobuf.py
git commit -m "feat: emit protobuf reservations"
```

## Task 3: Target Compatibility Core

**Files:**
- Create: `cli/src/modelable/compat/targets.py`
- Create: `cli/tests/test_target_compatibility.py`

**Interfaces:**
- Produces: `TargetCompatibilityFinding`
- Produces: `TargetCompatibilityReport`
- Produces: `compare_protobuf_manifests(old_artifacts: list[EmittedArtifact], new_artifacts: list[EmittedArtifact]) -> TargetCompatibilityReport`
- Produces: `compare_grpc_artifacts(old_artifacts: list[EmittedArtifact], new_artifacts: list[EmittedArtifact]) -> TargetCompatibilityReport`
- Consumed by: Task 4 CLI command.

- [ ] **Step 1: Add failing protobuf compatibility tests**

Create `cli/tests/test_target_compatibility.py`:

```python
from __future__ import annotations

from pathlib import Path

from modelable.compiler.workspace import load_workspace
from modelable.compat.targets import compare_protobuf_manifests
from modelable.emitters.protobuf import emit_protobuf


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _protobuf_artifacts(path: Path):
    return emit_protobuf(load_workspace(path), path.parent / "out")


def test_protobuf_compat_allows_added_optional_field(tmp_path):
    old = _write(
        tmp_path / "old.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""",
    )
    new = _write(
        tmp_path / "new.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    displayName?: string
  }
}
""",
    )

    report = compare_protobuf_manifests(_protobuf_artifacts(old), _protobuf_artifacts(new))

    assert report.status == "wire_compatible"
    assert report.findings == []


def test_protobuf_compat_rejects_removed_field_without_reservation(tmp_path):
    old = _write(
        tmp_path / "old.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    legacyStatus: string
  }
}
""",
    )
    new = _write(
        tmp_path / "new.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""",
    )

    report = compare_protobuf_manifests(_protobuf_artifacts(old), _protobuf_artifacts(new))

    assert report.status == "breaking"
    assert any(finding.code == "removed_field_not_reserved" for finding in report.findings)


def test_protobuf_compat_allows_removed_field_with_number_and_name_reservation(tmp_path):
    old = _write(
        tmp_path / "old.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    legacyStatus: string
  }
}
""",
    )
    new = _write(
        tmp_path / "new.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    reserved protobuf {
      numbers: [2]
      names: ["legacy_status"]
    }
    @key customerId: uuid
  }
}
""",
    )

    report = compare_protobuf_manifests(_protobuf_artifacts(old), _protobuf_artifacts(new))

    assert report.status == "wire_compatible"
    assert report.findings == []
```

- [ ] **Step 2: Add failing number reuse, type change, and enum tests**

Append:

```python
def test_protobuf_compat_rejects_field_number_reuse_by_reorder(tmp_path):
    old = _write(
        tmp_path / "old.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    displayName: string
  }
}
""",
    )
    new = _write(
        tmp_path / "new.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    displayName: string
    @key customerId: uuid
  }
}
""",
    )

    report = compare_protobuf_manifests(_protobuf_artifacts(old), _protobuf_artifacts(new))

    assert report.status == "breaking"
    assert any(finding.code == "field_number_reused" for finding in report.findings)


def test_protobuf_compat_rejects_target_type_change(tmp_path):
    old = _write(
        tmp_path / "old.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    score: int
  }
}
""",
    )
    new = _write(
        tmp_path / "new.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    score: string
  }
}
""",
    )

    report = compare_protobuf_manifests(_protobuf_artifacts(old), _protobuf_artifacts(new))

    assert report.status == "breaking"
    assert any(finding.code == "field_type_changed" for finding in report.findings)


def test_protobuf_compat_rejects_inline_enum_reorder(tmp_path):
    old = _write(
        tmp_path / "old.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    status: enum(active, blocked)
  }
}
""",
    )
    new = _write(
        tmp_path / "new.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    status: enum(blocked, active)
  }
}
""",
    )

    report = compare_protobuf_manifests(_protobuf_artifacts(old), _protobuf_artifacts(new))

    assert report.status == "breaking"
    assert any(finding.code == "enum_value_reused" for finding in report.findings)
```

- [ ] **Step 3: Add failing gRPC index compatibility test**

Append:

```python
from modelable.compat.targets import compare_grpc_artifacts
from modelable.emitters.grpc import emit_grpc


def _grpc_artifacts(path: Path):
    return emit_grpc(load_workspace(path), path.parent / "grpc-out")


def test_grpc_compat_reports_changed_secondary_index_as_read_rebuild(tmp_path):
    old = _write(
        tmp_path / "old.mdl",
        """
domain billing {
  owner: "billing"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    customerId: uuid
    createdAt: timestamp
  }
  index Order @ 1 {
    primary orderId
    secondary by_customer {
      key: [customerId]
    }
  }
}
""",
    )
    new = _write(
        tmp_path / "new.mdl",
        """
domain billing {
  owner: "billing"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    customerId: uuid
    createdAt: timestamp
  }
  index Order @ 1 {
    primary orderId
    secondary by_customer {
      key: [customerId]
      sort: [createdAt desc]
    }
  }
}
""",
    )

    report = compare_grpc_artifacts(_grpc_artifacts(old), _grpc_artifacts(new))

    assert report.status == "requires_read_rebuild"
    assert any(finding.code == "read_index_changed" for finding in report.findings)
```

- [ ] **Step 4: Run tests and verify failure**

Run from `cli/`:

```powershell
uv run pytest tests/test_target_compatibility.py -q
```

Expected: import failure because `modelable.compat.targets` does not exist.

- [ ] **Step 5: Implement report dataclasses and manifest extraction**

Create `cli/src/modelable/compat/targets.py`:

```python
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from modelable.emitters.base import EmittedArtifact

PASSING_STATUSES = {"wire_compatible", "read_compatible"}
STATUS_RANK = {
    "wire_compatible": 0,
    "read_compatible": 1,
    "requires_read_rebuild": 2,
    "requires_state_migration": 3,
    "breaking": 4,
}


@dataclass(frozen=True)
class TargetCompatibilityFinding:
    ref: str
    status: str
    code: str
    message: str
    old_path: str | None = None
    new_path: str | None = None


@dataclass(frozen=True)
class TargetCompatibilityReport:
    target: str
    status: str
    findings: list[TargetCompatibilityFinding] = field(default_factory=list)


def _worst_status(statuses: list[str]) -> str:
    if not statuses:
        return "wire_compatible"
    return max(statuses, key=lambda status: STATUS_RANK[status])
```

Add helpers:

```python
def _schema_entries(artifacts: list[EmittedArtifact]) -> dict[str, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {}
    for artifact in artifacts:
        if artifact.path.name != "schema-manifest.json":
            continue
        if not isinstance(artifact.content, str):
            continue
        document = json.loads(artifact.content)
        for schema in document.get("schemas", []):
            if isinstance(schema, dict) and isinstance(schema.get("ref"), str):
                entries[str(schema["ref"])] = schema
    return entries


def _service_entries(artifacts: list[EmittedArtifact]) -> dict[str, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {}
    for artifact in artifacts:
        if artifact.path.name != "service-manifest.json":
            continue
        if not isinstance(artifact.content, str):
            continue
        document = json.loads(artifact.content)
        ref = document.get("ref")
        if isinstance(ref, str):
            entries[ref] = document
    return entries
```

- [ ] **Step 6: Implement Protobuf comparison**

Add:

```python
def compare_protobuf_manifests(
    old_artifacts: list[EmittedArtifact],
    new_artifacts: list[EmittedArtifact],
) -> TargetCompatibilityReport:
    old_schemas = _schema_entries(old_artifacts)
    new_schemas = _schema_entries(new_artifacts)
    findings: list[TargetCompatibilityFinding] = []

    for ref in sorted(set(old_schemas) - set(new_schemas)):
        findings.append(_finding(ref, "breaking", "schema_removed", f"{ref}: schema was removed"))
    for ref in sorted(set(new_schemas) - set(old_schemas)):
        pass
    for ref in sorted(set(old_schemas) & set(new_schemas)):
        findings.extend(_compare_schema(ref, old_schemas[ref], new_schemas[ref]))

    return TargetCompatibilityReport(
        target="protobuf",
        status=_worst_status([finding.status for finding in findings]),
        findings=findings,
    )
```

Implement `_compare_schema`:

```python
def _compare_schema(ref: str, old: dict[str, Any], new: dict[str, Any]) -> list[TargetCompatibilityFinding]:
    findings: list[TargetCompatibilityFinding] = []
    old_fields = _fields_by_number(old)
    new_fields = _fields_by_number(new)
    old_by_name = _fields_by_name(old)
    new_by_name = _fields_by_name(new)
    reservations = _reservations(new)

    for number, old_field in old_fields.items():
        new_field = new_fields.get(number)
        if new_field is None:
            if number not in reservations["numbers"] or str(old_field["proto_name"]) not in reservations["names"]:
                findings.append(
                    _finding(
                        ref,
                        "breaking",
                        "removed_field_not_reserved",
                        f"{ref}: removed field {old_field['name']} number {number} is not reserved",
                    )
                )
            continue
        if old_field["name"] != new_field["name"]:
            findings.append(
                _finding(
                    ref,
                    "breaking",
                    "field_number_reused",
                    f"{ref}: field number {number} changed from {old_field['name']} to {new_field['name']}",
                )
            )
        findings.extend(_compare_field(ref, old_field, new_field))

    for name, old_field in old_by_name.items():
        new_field = new_by_name.get(name)
        if new_field is not None and old_field["number"] != new_field["number"]:
            findings.append(
                _finding(
                    ref,
                    "breaking",
                    "field_number_reused",
                    f"{ref}: field {name} moved from number {old_field['number']} to {new_field['number']}",
                )
            )
    return findings
```

Add helpers:

```python
def _compare_field(ref: str, old_field: dict[str, Any], new_field: dict[str, Any]) -> list[TargetCompatibilityFinding]:
    findings: list[TargetCompatibilityFinding] = []
    for key in ("type", "fixed_length", "semantic_type", "map"):
        if old_field.get(key) != new_field.get(key):
            findings.append(
                _finding(ref, "breaking", "field_type_changed", f"{ref}: field {old_field['name']} changed {key}")
            )
            break
    old_optional = str(old_field.get("type", "")).startswith("optional ")
    new_optional = str(new_field.get("type", "")).startswith("optional ")
    if old_optional and not new_optional:
        findings.append(
            _finding(
                ref,
                "breaking",
                "field_requiredness_changed",
                f"{ref}: field {old_field['name']} changed from optional to required",
            )
        )
    return findings


def _fields_by_number(schema: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {
        int(field["number"]): field
        for field in schema.get("fields", [])
        if isinstance(field, dict) and isinstance(field.get("number"), int)
    }


def _fields_by_name(schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(field["name"]): field
        for field in schema.get("fields", [])
        if isinstance(field, dict) and isinstance(field.get("name"), str)
    }


def _reservations(schema: dict[str, Any]) -> dict[str, set[Any]]:
    raw = schema.get("reservations", {})
    if not isinstance(raw, dict):
        return {"numbers": set(), "names": set()}
    numbers = raw.get("numbers", [])
    names = raw.get("names", [])
    return {
        "numbers": {int(number) for number in numbers if isinstance(number, int)},
        "names": {str(name) for name in names if isinstance(name, str)},
    }


def _finding(ref: str, status: str, code: str, message: str) -> TargetCompatibilityFinding:
    return TargetCompatibilityFinding(ref=ref, status=status, code=code, message=message)
```

- [ ] **Step 7: Implement enum compatibility using manifest metadata**

If manifest fields do not yet include enum values, add in Task 2 or here:

In `cli/src/modelable/emitters/protobuf.py`, add to `_manifest_field`:

```python
if field.enum is not None:
    entry["enum_values"] = list(field.enum.values)
```

Then in `_compare_field`, compare:

```python
old_enum = old_field.get("enum_values")
new_enum = new_field.get("enum_values")
if isinstance(old_enum, list) and isinstance(new_enum, list):
    for index, value in enumerate(old_enum):
        if index >= len(new_enum):
            findings.append(_finding(ref, "breaking", "enum_value_removed", f"{ref}: enum value {value} was removed"))
        elif new_enum[index] != value:
            findings.append(
                _finding(
                    ref,
                    "breaking",
                    "enum_value_reused",
                    f"{ref}: enum value number {index + 1} changed from {value} to {new_enum[index]}",
                )
            )
```

- [ ] **Step 8: Implement gRPC service comparison**

Add:

```python
def compare_grpc_artifacts(
    old_artifacts: list[EmittedArtifact],
    new_artifacts: list[EmittedArtifact],
) -> TargetCompatibilityReport:
    protobuf_report = compare_protobuf_manifests(old_artifacts, new_artifacts)
    old_services = _service_entries(old_artifacts)
    new_services = _service_entries(new_artifacts)
    findings = list(protobuf_report.findings)

    for ref in sorted(set(old_services) & set(new_services)):
        findings.extend(_compare_service(ref, old_services[ref], new_services[ref]))
    for ref in sorted(set(old_services) - set(new_services)):
        findings.append(_finding(ref, "breaking", "service_removed", f"{ref}: gRPC service manifest was removed"))

    return TargetCompatibilityReport(
        target="grpc",
        status=_worst_status([finding.status for finding in findings]) if findings else "read_compatible",
        findings=findings,
    )
```

Add:

```python
def _compare_service(ref: str, old: dict[str, Any], new: dict[str, Any]) -> list[TargetCompatibilityFinding]:
    findings: list[TargetCompatibilityFinding] = []
    if old.get("service_proto") != new.get("service_proto"):
        findings.append(_finding(ref, "breaking", "service_proto_changed", f"{ref}: service proto changed"))
    old_indexes = _indexes_by_name(old.get("read_indexes", []))
    new_indexes = _indexes_by_name(new.get("read_indexes", []))
    for name, old_index in old_indexes.items():
        new_index = new_indexes.get(name)
        if new_index is None:
            findings.append(_finding(ref, "requires_read_rebuild", "read_index_removed", f"{ref}: read index {name} was removed"))
            continue
        if old_index != new_index:
            status = "requires_state_migration" if name == "primary" and old_index.get("key_fields") != new_index.get("key_fields") else "requires_read_rebuild"
            findings.append(_finding(ref, status, "read_index_changed", f"{ref}: read index {name} changed"))
    return findings


def _indexes_by_name(value: object) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for item in value:
        if isinstance(item, dict) and isinstance(item.get("index_name"), str):
            result[str(item["index_name"])] = item
    return result
```

- [ ] **Step 9: Run focused compatibility tests**

Run from `cli/`:

```powershell
uv run pytest tests/test_target_compatibility.py tests/test_protobuf_reservations.py --tb=short -q
```

Expected: all pass.

- [ ] **Step 10: Run required gate and commit Task 3**

Run from `cli/`:

```powershell
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
```

Commit:

```powershell
git add cli/src/modelable/compat/targets.py cli/src/modelable/emitters/protobuf.py cli/tests/test_target_compatibility.py cli/tests/test_protobuf_reservations.py
git commit -m "feat: compare protobuf grpc compatibility"
```

## Task 4: `validate-compat` CLI Command

**Files:**
- Create: `cli/src/modelable/commands/validate_compat.py`
- Modify: `cli/src/modelable/cli.py`
- Modify: `cli/tests/test_target_compatibility.py`

**Interfaces:**
- Consumes: `compare_protobuf_manifests(...)`
- Consumes: `compare_grpc_artifacts(...)`
- Produces: Click command `validate-compat --from OLD --to NEW --target protobuf|grpc`

- [ ] **Step 1: Add failing CLI tests**

Append to `cli/tests/test_target_compatibility.py`:

```python
from click.testing import CliRunner

from modelable.cli import cli


def test_validate_compat_cli_passes_wire_compatible_change(tmp_path):
    old = _write(
        tmp_path / "old.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""",
    )
    new = _write(
        tmp_path / "new.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    displayName?: string
  }
}
""",
    )

    result = CliRunner().invoke(
        cli,
        ["validate-compat", "--from", str(old), "--to", str(new), "--target", "protobuf"],
    )

    assert result.exit_code == 0, result.output
    assert "target: protobuf" in result.output
    assert "status: wire_compatible" in result.output


def test_validate_compat_cli_fails_breaking_change(tmp_path):
    old = _write(
        tmp_path / "old.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    legacyStatus: string
  }
}
""",
    )
    new = _write(
        tmp_path / "new.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""",
    )

    result = CliRunner().invoke(
        cli,
        ["validate-compat", "--from", str(old), "--to", str(new), "--target", "protobuf"],
    )

    assert result.exit_code == 1
    assert "status: breaking" in result.output
    assert "removed field legacyStatus" in result.output
```

- [ ] **Step 2: Run tests and verify failure**

Run from `cli/`:

```powershell
uv run pytest tests/test_target_compatibility.py -k "validate_compat_cli" -q
```

Expected: Click reports no such command.

- [ ] **Step 3: Implement command module**

Create `cli/src/modelable/commands/validate_compat.py`:

```python
from __future__ import annotations

from pathlib import Path

import click

from modelable.commands.common import console
from modelable.compat.targets import PASSING_STATUSES, TargetCompatibilityReport, compare_grpc_artifacts, compare_protobuf_manifests
from modelable.compiler.workspace import load_workspace
from modelable.emitters.grpc import emit_grpc
from modelable.emitters.protobuf import emit_protobuf


def register_validate_compat_commands(cli_group: click.Group) -> None:
    cli_group.add_command(validate_compat)


@click.command("validate-compat")
@click.option("--from", "from_path", required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--to", "to_path", required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--target", required=True, type=click.Choice(["protobuf", "grpc"]))
def validate_compat(from_path: Path, to_path: Path, target: str) -> None:
    """Validate target-specific compatibility between two Modelable workspaces."""
    old_workspace = load_workspace(from_path)
    new_workspace = load_workspace(to_path)
    try:
        if target == "protobuf":
            report = compare_protobuf_manifests(
                emit_protobuf(old_workspace, Path(".modelable/compat/old/protobuf")),
                emit_protobuf(new_workspace, Path(".modelable/compat/new/protobuf")),
            )
        else:
            report = compare_grpc_artifacts(
                emit_grpc(old_workspace, Path(".modelable/compat/old/grpc")),
                emit_grpc(new_workspace, Path(".modelable/compat/new/grpc")),
            )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    _print_report(report)
    if report.status not in PASSING_STATUSES:
        raise click.exceptions.Exit(1)


def _print_report(report: TargetCompatibilityReport) -> None:
    console.print(f"target: {report.target}")
    console.print(f"status: {report.status}")
    if report.findings:
        console.print("")
        for finding in report.findings:
            console.print(f"- {finding.message}")
    else:
        console.print("")
        console.print("- no target compatibility findings")
```

- [ ] **Step 4: Register command**

In `cli/src/modelable/cli.py`, import and register:

```python
from modelable.commands.validate_compat import register_validate_compat_commands
```

Then add:

```python
register_validate_compat_commands(cli)
```

- [ ] **Step 5: Run CLI tests**

Run from `cli/`:

```powershell
uv run pytest tests/test_target_compatibility.py -k "validate_compat_cli" -q
```

Expected: pass.

- [ ] **Step 6: Run target compatibility suites**

Run from `cli/`:

```powershell
uv run pytest tests/test_target_compatibility.py tests/test_protobuf_reservations.py tests/test_emit_protobuf.py tests/test_emit_grpc.py --tb=short -q
```

Expected: pass.

- [ ] **Step 7: Run required gate and commit Task 4**

Run from `cli/`:

```powershell
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
```

Commit:

```powershell
git add cli/src/modelable/commands/validate_compat.py cli/src/modelable/cli.py cli/tests/test_target_compatibility.py
git commit -m "feat: add target compatibility command"
```

## Task 5: Documentation, Roadmap, and Final Gates

**Files:**
- Modify: `docs/language-reference.md`
- Modify: `docs/cli-reference.md`
- Modify: `docs/compiler-reference.md`
- Modify: `docs/wire-format-contract.md`
- Modify: `CHANGELOG.md`
- Modify: `ROADMAP.md`

**Interfaces:**
- Consumes: completed reservations and `validate-compat` behavior from Tasks 1-4.
- Produces: public docs for reservation syntax, target compatibility validation, known remaining limits, and roadmap status.

- [ ] **Step 1: Update language reference**

Add a section near model/projection field syntax:

```markdown
### Protobuf reservations

Model and projection versions may reserve deleted Protobuf field numbers and
field names:

```mdl
reserved protobuf {
  numbers: [3, 7]
  names: ["legacy_status"]
}
```

Reservations are version-local. A field in the same version may not reuse a
reserved number, source field name, or generated Protobuf field name. The
Protobuf and gRPC targets use these reservations to render `reserved`
declarations and to validate target compatibility.
```

- [ ] **Step 2: Update CLI reference**

Add:

```markdown
### `validate-compat` — Validate target compatibility

```text
modelable validate-compat --from OLD --to NEW --target protobuf|grpc
```

`validate-compat` compares generated target manifests from two Modelable
workspaces without requiring `protoc`. `wire_compatible` and `read_compatible`
exit `0`; `requires_read_rebuild`, `requires_state_migration`, and `breaking`
exit non-zero.
```

- [ ] **Step 3: Update compiler and wire-format docs**

In `docs/compiler-reference.md`, mark Protobuf/gRPC compatibility validation implemented for the first manifest-based slice and note remaining follow-ups:

```markdown
Protobuf/gRPC compatibility validation compares generated manifests and service
metadata. Descriptor-binary diffing, field-number pinning, enum reservations,
and explicit rebuild/migration declarations remain follow-up work.
```

In `docs/wire-format-contract.md`, replace the current no-compiler-guard caveat with:

```markdown
`modelable validate-compat --target protobuf|grpc` guards field-number reuse,
deleted-field reservations, target type changes, requiredness changes, inline
enum value reuse, and gRPC read-index changes. The first slice is
manifest-based and does not compare descriptor binaries.
```

- [ ] **Step 4: Update changelog and roadmap**

Add under `[Unreleased] / Added`:

```markdown
- Added source-level Protobuf field reservations and
  `validate-compat --target protobuf|grpc` compatibility validation.
```

Update `ROADMAP.md` Priority 1 item 4 to mark reservations and manifest-based compatibility validation shipped. Leave field-number pinning, enum reservations, explicit rebuild/migration declarations, and Scalable registration fixtures as follow-ups where appropriate.

- [ ] **Step 5: Run docs mention check**

Run from repo root:

```powershell
rg -n -- "reserved protobuf|validate-compat|wire_compatible|requires_read_rebuild|field-number pinning|enum reservations|descriptor-binary" docs CHANGELOG.md ROADMAP.md
```

Expected: matches in docs, changelog, and roadmap; remaining limits are explicit.

- [ ] **Step 6: Run focused behavior tests**

Run from `cli/`:

```powershell
uv run pytest tests/test_protobuf_reservations.py tests/test_target_compatibility.py tests/test_emit_protobuf.py tests/test_emit_grpc.py --tb=short -q
```

Expected: pass.

- [ ] **Step 7: Run docs build**

Run from repo root:

```powershell
uvx --from mkdocs==1.6.1 --with mkdocs-material==9.7.6 mkdocs build --strict
```

Expected: exit `0`. Existing informational messages about unnaved `wire-format-contract.md` and excluded archived spec links are acceptable if unchanged.

- [ ] **Step 8: Run mandatory repository gates**

Run from `cli/`:

```powershell
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
```

Expected: all pass.

- [ ] **Step 9: Run doc-review**

Run from repo root:

```powershell
git diff --name-only main
git diff --check
rg -n "T[O]DO|T[B]D|implement lat[e]r|fill in detail[s]|appropriate error handl[i]ng" docs ROADMAP.md CHANGELOG.md
uvx --from mkdocs==1.6.1 --with mkdocs-material==9.7.6 mkdocs build --strict
```

Expected: no placeholders, no whitespace errors, docs build exits `0`.

- [ ] **Step 10: Commit Task 5**

Commit:

```powershell
git add docs/language-reference.md docs/cli-reference.md docs/compiler-reference.md docs/wire-format-contract.md CHANGELOG.md ROADMAP.md
git commit -m "docs: document target compatibility validation"
```

## Final Publish Checklist

After all implementation tasks are committed:

- [ ] Run from repo root:

```powershell
git status --short --branch
git log --oneline main..HEAD
```

Expected: branch is `design/protobuf-grpc-compat-reservations`, working tree is clean, and commits include the design commit, plan commit, and task commits.

- [ ] Push:

```powershell
git push -u origin design/protobuf-grpc-compat-reservations
```

- [ ] Open or update a draft PR with:

  - source-level `reserved protobuf` syntax;
  - Protobuf `.proto` reservation rendering;
  - schema manifest reservation metadata;
  - `validate-compat --target protobuf|grpc`;
  - manifest-based, dependency-free validation;
  - gRPC read-index compatibility classification;
  - explicit follow-ups for field-number pinning, enum reservations, rebuild declarations, JSON output, and descriptor-binary diffing;
  - all verification commands and results;
  - `Doc/spec review: all phases passed`.

## Self-Review

Spec coverage:

- Reservation syntax: Task 1 parses and validates `reserved protobuf`; Task 2 emits and manifests it.
- Emitter behavior: Task 2 renders `reserved` declarations and includes reservations in fingerprints.
- Protobuf compatibility: Task 3 compares field numbers, names, types, requiredness, removed fields, reservations, and inline enum values.
- gRPC compatibility: Task 3 adds service/read-index comparison.
- CLI command: Task 4 registers `validate-compat`.
- Docs and roadmap: Task 5 updates public docs and remaining limits.

Known scoped follow-ups remain outside this plan by design: field-number pinning, enum reservation syntax, rebuild/migration declarations, JSON output, and descriptor-binary comparison.
