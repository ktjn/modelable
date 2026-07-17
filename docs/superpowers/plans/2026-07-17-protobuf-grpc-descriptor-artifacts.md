# Protobuf and gRPC Descriptor Artifacts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add opt-in descriptor-set artifacts for `compile --target protobuf` and `compile --target grpc`.

**Architecture:** Keep existing emitters deterministic and text-first. Add binary artifact support to the shared artifact layer, then make `compile` orchestrate descriptor generation after `.proto` files are written because `protoc` operates on files. Descriptor metadata is patched into manifests only when `--descriptor-set` is requested.

**Tech Stack:** Python 3.14, Click, pytest, `subprocess`, external `protoc` executable on `PATH`, existing Modelable emitter and manifest code.

## Global Constraints

- Descriptor generation is opt-in via `--descriptor-set`.
- Default `compile --target protobuf` and `compile --target grpc` must not require `protoc`.
- Descriptor generation must fail clearly when `protoc` is missing.
- Descriptor generation must fail clearly when `protoc` rejects generated `.proto` files.
- Do not add a Python dependency on `protobuf`, `grpcio`, or `grpcio-tools`.
- Do not introduce field-number reservations or `validate-compat --target protobuf|grpc`.
- Do not change existing `.proto` text output.
- Before every commit, run the four AGENTS.md commands from `cli/`.

---

## Task 1: Binary Artifact Support and Descriptor Helper

**Files:**
- Modify: `cli/src/modelable/emitters/base.py`
- Create: `cli/src/modelable/emitters/descriptors.py`
- Create: `cli/tests/test_descriptor_artifacts.py`

**Interfaces:**
- Produces: `EmittedArtifact.content: dict[str, object] | str | bytes`
- Produces: `compute_content_hash(content: dict[str, object] | str | bytes) -> str`
- Produces: `DescriptorGenerationError(ValueError)`
- Produces: `compile_descriptor_set(proto_root: Path, proto_files: list[Path], out_path: Path, include_imports: bool = True, target_ref: str | None = None) -> bytes`
- Consumed by: Tasks 2, 3, and 4.

- [ ] **Step 1: Add failing tests for binary hashes and descriptor helper command shape**

Create `cli/tests/test_descriptor_artifacts.py`:

```python
from __future__ import annotations

import hashlib
import os
import stat
import sys
from pathlib import Path

import pytest

from modelable.emitters.base import EmittedArtifact, compute_content_hash
from modelable.emitters.descriptors import DescriptorGenerationError, compile_descriptor_set


def _write_fake_protoc(path: Path, *, body: str) -> Path:
    if sys.platform == "win32":
        script = path / "protoc.cmd"
        script.write_text(body, encoding="utf-8")
        return script
    script = path / "protoc"
    script.write_text(body, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


def test_compute_content_hash_supports_bytes():
    assert compute_content_hash(b"descriptor-bytes") == hashlib.sha256(b"descriptor-bytes").hexdigest()


def test_emitted_artifact_accepts_bytes_content(tmp_path):
    artifact = EmittedArtifact(
        target="protobuf",
        ref="platform.Order@1",
        artifact_id="platform.Order.v1.descriptor",
        path=tmp_path / "Order.v1.descriptor.pb",
        content=b"descriptor-bytes",
        content_hash=compute_content_hash(b"descriptor-bytes"),
    )

    assert artifact.content == b"descriptor-bytes"
    assert artifact.content_hash == hashlib.sha256(b"descriptor-bytes").hexdigest()


def test_compile_descriptor_set_invokes_protoc_with_relative_inputs(tmp_path, monkeypatch):
    proto_root = tmp_path / "generated"
    proto_root.mkdir()
    (proto_root / "platform").mkdir()
    proto_file = proto_root / "platform" / "Order.v1.proto"
    proto_file.write_text('syntax = "proto3";\npackage modelable.platform.v1;\nmessage Order {}\n', encoding="utf-8")
    out_path = proto_root / "platform" / "Order.v1.descriptor.pb"
    calls_path = tmp_path / "calls.txt"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    if sys.platform == "win32":
        _write_fake_protoc(
            bin_dir,
            body=(
                "@echo off\n"
                "echo %* > \"" + str(calls_path) + "\"\n"
                "for %%a in (%*) do (\n"
                "  echo %%a | findstr /b /c:\"--descriptor_set_out=\" >nul && (\n"
                "    set out=%%a\n"
                "  )\n"
                ")\n"
                "set out=%out:--descriptor_set_out=%\n"
                "echo descriptor> \"%out%\"\n"
            ),
        )
    else:
        _write_fake_protoc(
            bin_dir,
            body=(
                "#!/usr/bin/env sh\n"
                "printf '%s' \"$*\" > '" + str(calls_path) + "'\n"
                "for arg in \"$@\"; do\n"
                "  case \"$arg\" in --descriptor_set_out=*) out=${arg#--descriptor_set_out=};; esac\n"
                "done\n"
                "printf descriptor > \"$out\"\n"
            ),
        )
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))

    content = compile_descriptor_set(
        proto_root=proto_root,
        proto_files=[proto_file],
        out_path=out_path,
        target_ref="platform.Order@1",
    )

    assert content.strip() == b"descriptor"
    call_text = calls_path.read_text(encoding="utf-8")
    assert "-I" in call_text
    assert str(proto_root) in call_text
    assert "platform" + os.sep + "Order.v1.proto" in call_text or "platform/Order.v1.proto" in call_text
    assert "--include_imports" in call_text
    assert "--descriptor_set_out=" in call_text


def test_compile_descriptor_set_reports_missing_protoc(tmp_path, monkeypatch):
    proto_root = tmp_path / "generated"
    proto_root.mkdir()
    proto_file = proto_root / "Order.v1.proto"
    proto_file.write_text('syntax = "proto3";\nmessage Order {}\n', encoding="utf-8")
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))

    with pytest.raises(DescriptorGenerationError, match="descriptor generation requires protoc on PATH"):
        compile_descriptor_set(
            proto_root=proto_root,
            proto_files=[proto_file],
            out_path=proto_root / "Order.v1.descriptor.pb",
            target_ref="platform.Order@1",
        )


def test_compile_descriptor_set_reports_protoc_failure(tmp_path, monkeypatch):
    proto_root = tmp_path / "generated"
    proto_root.mkdir()
    proto_file = proto_root / "Order.v1.proto"
    proto_file.write_text('syntax = "proto3";\nmessage Order {}\n', encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    if sys.platform == "win32":
        _write_fake_protoc(bin_dir, body="@echo off\necho broken proto 1>&2\nexit /b 7\n")
    else:
        _write_fake_protoc(bin_dir, body="#!/usr/bin/env sh\necho broken proto >&2\nexit 7\n")
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))

    with pytest.raises(
        DescriptorGenerationError,
        match=r"platform.Order@1.*protoc failed.*broken proto",
    ):
        compile_descriptor_set(
            proto_root=proto_root,
            proto_files=[proto_file],
            out_path=proto_root / "Order.v1.descriptor.pb",
            target_ref="platform.Order@1",
        )
```

- [ ] **Step 2: Run tests and verify they fail**

Run from `cli/`:

```powershell
uv run pytest tests/test_descriptor_artifacts.py -q
```

Expected: failure because `modelable.emitters.descriptors` does not exist and `compute_content_hash` does not accept bytes.

- [ ] **Step 3: Extend artifact type and binary hashing**

In `cli/src/modelable/emitters/base.py`, change the content type and hash helper:

```python
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path


ArtifactContent = dict[str, object] | str | bytes


@dataclass
class EmittedArtifact:
    target: str
    ref: str  # "domain.Name@version"
    artifact_id: str  # "domain.Name.vVersion"
    path: Path
    content: ArtifactContent
    content_hash: str
    warnings: list[str] = field(default_factory=list)


def compute_content_hash(content: ArtifactContent) -> str:
    if isinstance(content, bytes):
        return hashlib.sha256(content).hexdigest()
    payload = json.dumps(content, indent=2, ensure_ascii=False) + "\n" if isinstance(content, dict) else content
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Add descriptor helper implementation**

Create `cli/src/modelable/emitters/descriptors.py`:

```python
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class DescriptorGenerationError(ValueError):
    """Raised when protoc cannot generate a descriptor artifact."""


def compile_descriptor_set(
    *,
    proto_root: Path,
    proto_files: list[Path],
    out_path: Path,
    include_imports: bool = True,
    target_ref: str | None = None,
) -> bytes:
    protoc = shutil.which("protoc")
    if protoc is None:
        raise DescriptorGenerationError("descriptor generation requires protoc on PATH")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
    relative_inputs = [_relative_proto_path(proto_root, proto_file) for proto_file in proto_files]
    command = [
        protoc,
        "-I",
        str(proto_root),
        f"--descriptor_set_out={tmp_path}",
    ]
    if include_imports:
        command.append("--include_imports")
    command.extend(relative_inputs)

    result = subprocess.run(
        command,
        cwd=proto_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
        prefix = f"{target_ref}: " if target_ref else ""
        raise DescriptorGenerationError(f"{prefix}protoc failed: {message}")
    try:
        content = tmp_path.read_bytes()
    except OSError as exc:
        prefix = f"{target_ref}: " if target_ref else ""
        raise DescriptorGenerationError(f"{prefix}protoc did not write descriptor output: {tmp_path}") from exc
    tmp_path.replace(out_path)
    return content


def _relative_proto_path(proto_root: Path, proto_file: Path) -> str:
    try:
        return proto_file.relative_to(proto_root).as_posix()
    except ValueError as exc:
        raise DescriptorGenerationError(f"proto file {proto_file} is not under proto root {proto_root}") from exc
```

- [ ] **Step 5: Run focused tests**

Run from `cli/`:

```powershell
uv run pytest tests/test_descriptor_artifacts.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Run required gate and commit Task 1**

Run from `cli/`:

```powershell
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
```

Expected: all pass.

Commit from repo root:

```powershell
git add cli/src/modelable/emitters/base.py cli/src/modelable/emitters/descriptors.py cli/tests/test_descriptor_artifacts.py
git commit -m "feat: add descriptor artifact helper"
```

## Task 2: Compile Command Descriptor Flag and Binary Writer

**Files:**
- Modify: `cli/src/modelable/commands/compile.py`
- Modify: `cli/tests/test_descriptor_artifacts.py`

**Interfaces:**
- Consumes: `EmittedArtifact.content` may be `bytes`
- Produces: CLI option `--descriptor-set`, parameter `descriptor_set: bool`
- Produces: `_write_artifact(art: EmittedArtifact) -> None`
- Consumed by: Tasks 3 and 4.

- [ ] **Step 1: Add failing tests for flag parsing and binary writing**

Append to `cli/tests/test_descriptor_artifacts.py`:

```python
from click.testing import CliRunner

from modelable.cli import cli
from modelable.commands.compile import _write_artifact


def test_write_artifact_writes_bytes(tmp_path):
    artifact = EmittedArtifact(
        target="protobuf",
        ref="platform.Order@1",
        artifact_id="platform.Order.v1.descriptor",
        path=tmp_path / "Order.v1.descriptor.pb",
        content=b"\x00descriptor",
        content_hash=compute_content_hash(b"\x00descriptor"),
    )

    _write_artifact(artifact)

    assert artifact.path.read_bytes() == b"\x00descriptor"


def test_compile_accepts_descriptor_set_flag_for_protobuf_without_changing_default_behavior(tmp_path):
    mdl = tmp_path / "platform.mdl"
    mdl.write_text(
        """
domain platform {
  owner: "platform-team"

  entity Order @ 1 (additive) {
    @key orderId: uuid
  }
}
""",
        encoding="utf-8",
    )
    out = tmp_path / "dist"

    result = CliRunner().invoke(cli, ["compile", str(mdl), "--target", "protobuf", "--out", str(out)])

    assert result.exit_code == 0, result.output
    assert (out / "platform" / "Order.v1" / "Order.v1.proto").exists()
    assert not (out / "platform" / "Order.v1" / "Order.v1.descriptor.pb").exists()
```

- [ ] **Step 2: Run tests and verify failure**

Run from `cli/`:

```powershell
uv run pytest tests/test_descriptor_artifacts.py::test_write_artifact_writes_bytes tests/test_descriptor_artifacts.py::test_compile_accepts_descriptor_set_flag_for_protobuf_without_changing_default_behavior -q
```

Expected: failure because `_write_artifact` does not exist.

- [ ] **Step 3: Add CLI option and shared artifact writer**

In `cli/src/modelable/commands/compile.py`, add the Click option immediately after `--domain`:

```python
@click.option(
    "--descriptor-set",
    "descriptor_set",
    is_flag=True,
    help="For protobuf and grpc targets, compile generated .proto files into descriptor .pb artifacts.",
)
```

Add `descriptor_set: bool` to the `compile(...)` signature after `domains`.

Add this helper near `_write_artifact_text`:

```python
def _write_artifact(art: EmittedArtifact) -> None:
    art.path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(art.content, bytes):
        art.path.write_bytes(art.content)
    elif isinstance(art.content, dict):
        art.path.write_text(json.dumps(art.content, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    else:
        art.path.write_text(art.content, encoding="utf-8")
```

Change the protobuf and grpc compile branches to keep existing behavior when `descriptor_set` is false:

```python
    elif target == "protobuf":
        artifacts = emit_protobuf(
            emit_workspace,
            output,
            registry_ids=registry_ids,
        )
        for art in artifacts:
            _write_artifact(art)
            _print_artifact_result(art)
        if not artifacts:
            console.print("[yellow]No artifacts generated.[/yellow]")
```

```python
    elif target == "grpc":
        artifacts = emit_grpc(
            emit_workspace,
            output,
            registry_ids=registry_ids,
        )
        for art in artifacts:
            _write_artifact(art)
            _print_artifact_result(art)
        if not artifacts:
            console.print("[yellow]No artifacts generated.[/yellow]")
```

Leave the descriptor-specific behavior for Tasks 3 and 4.

- [ ] **Step 4: Run focused tests**

Run from `cli/`:

```powershell
uv run pytest tests/test_descriptor_artifacts.py::test_write_artifact_writes_bytes tests/test_descriptor_artifacts.py::test_compile_accepts_descriptor_set_flag_for_protobuf_without_changing_default_behavior -q
```

Expected: pass.

- [ ] **Step 5: Run required gate and commit Task 2**

Run from `cli/`:

```powershell
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
```

Expected: all pass.

Commit from repo root:

```powershell
git add cli/src/modelable/commands/compile.py cli/tests/test_descriptor_artifacts.py
git commit -m "feat: support binary compile artifacts"
```

## Task 3: Protobuf Descriptor Artifacts and Schema Manifest Metadata

**Files:**
- Modify: `cli/src/modelable/commands/compile.py`
- Modify: `cli/tests/test_descriptor_artifacts.py`

**Interfaces:**
- Consumes: `compile_descriptor_set(...) -> bytes`
- Produces: `_with_schema_descriptor_metadata(manifest_content: str, descriptor_path: Path, descriptor_hash: str) -> str`
- Produces: `_emit_protobuf_with_descriptors(artifacts: list[EmittedArtifact], output: Path) -> list[EmittedArtifact]`
- Consumed by: Task 5 docs and final gates.

- [ ] **Step 1: Add failing Protobuf descriptor CLI test with fake protoc**

Append to `cli/tests/test_descriptor_artifacts.py`:

```python
def test_compile_protobuf_descriptor_set_writes_descriptor_and_manifest_metadata(tmp_path, monkeypatch):
    mdl = tmp_path / "platform.mdl"
    mdl.write_text(
        """
domain platform {
  owner: "platform-team"

  entity Order @ 1 (additive) {
    @key orderId: uuid
    customerId: uuid
  }
}
""",
        encoding="utf-8",
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    if sys.platform == "win32":
        _write_fake_protoc(
            bin_dir,
            body=(
                "@echo off\n"
                "for %%a in (%*) do (\n"
                "  echo %%a | findstr /b /c:\"--descriptor_set_out=\" >nul && set out=%%a\n"
                ")\n"
                "set out=%out:--descriptor_set_out=%\n"
                "echo protobuf-descriptor> \"%out%\"\n"
            ),
        )
    else:
        _write_fake_protoc(
            bin_dir,
            body=(
                "#!/usr/bin/env sh\n"
                "for arg in \"$@\"; do\n"
                "  case \"$arg\" in --descriptor_set_out=*) out=${arg#--descriptor_set_out=};; esac\n"
                "done\n"
                "printf protobuf-descriptor > \"$out\"\n"
            ),
        )
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    out = tmp_path / "dist"

    result = CliRunner().invoke(
        cli,
        ["compile", str(mdl), "--target", "protobuf", "--out", str(out), "--descriptor-set"],
    )

    assert result.exit_code == 0, result.output
    descriptor = out / "platform" / "Order.v1" / "Order.v1.descriptor.pb"
    assert descriptor.read_bytes().strip() == b"protobuf-descriptor"
    schema = json.loads((out / "platform" / "Order.v1" / "schema-manifest.json").read_text(encoding="utf-8"))[
        "schemas"
    ][0]
    assert schema["descriptor"] == {
        "path": "Order.v1.descriptor.pb",
        "content_hash": compute_content_hash(descriptor.read_bytes()),
        "include_imports": True,
    }
```

- [ ] **Step 2: Add failing missing-protoc CLI test**

Append:

```python
def test_compile_protobuf_descriptor_set_fails_when_protoc_is_missing(tmp_path, monkeypatch):
    mdl = tmp_path / "platform.mdl"
    mdl.write_text(
        """
domain platform {
  owner: "platform-team"

  entity Order @ 1 (additive) {
    @key orderId: uuid
  }
}
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))

    result = CliRunner().invoke(
        cli,
        ["compile", str(mdl), "--target", "protobuf", "--out", str(tmp_path / "dist"), "--descriptor-set"],
    )

    assert result.exit_code != 0
    assert "descriptor generation requires protoc on PATH" in result.output
```

- [ ] **Step 3: Run tests and verify failure**

Run from `cli/`:

```powershell
uv run pytest tests/test_descriptor_artifacts.py -k "protobuf_descriptor_set" -q
```

Expected: metadata test fails because `--descriptor-set` is accepted but no descriptor generation happens.

- [ ] **Step 4: Add Protobuf descriptor orchestration helpers**

In `cli/src/modelable/commands/compile.py`, import:

```python
from modelable.emitters.base import EmittedArtifact, compute_content_hash
from modelable.emitters.descriptors import DescriptorGenerationError, compile_descriptor_set
```

Replace the existing base import instead of duplicating it.

Add helpers near `_write_artifact`:

```python
def _emit_protobuf_with_descriptors(artifacts: list[EmittedArtifact], output: Path) -> list[EmittedArtifact]:
    for art in artifacts:
        if art.path.name != "schema-manifest.json":
            _write_artifact(art)

    result: list[EmittedArtifact] = []
    for art in artifacts:
        if art.path.name != "schema-manifest.json":
            result.append(art)
            continue
        assert isinstance(art.content, str)
        schema = json.loads(art.content)["schemas"][0]
        ref = str(schema["ref"])
        proto_name = art.path.parent.name + ".proto"
        proto_path = art.path.parent / proto_name
        descriptor_path = art.path.parent / (art.path.parent.name + ".descriptor.pb")
        descriptor_bytes = compile_descriptor_set(
            proto_root=output,
            proto_files=[proto_path],
            out_path=descriptor_path,
            target_ref=ref,
        )
        descriptor_artifact = EmittedArtifact(
            target=art.target,
            ref=art.ref,
            artifact_id=f"{art.artifact_id}.descriptor",
            path=descriptor_path,
            content=descriptor_bytes,
            content_hash=compute_content_hash(descriptor_bytes),
        )
        manifest_content = _with_schema_descriptor_metadata(
            art.content,
            descriptor_path=descriptor_path,
            descriptor_hash=descriptor_artifact.content_hash,
        )
        manifest_artifact = EmittedArtifact(
            target=art.target,
            ref=art.ref,
            artifact_id=art.artifact_id,
            path=art.path,
            content=manifest_content,
            content_hash=compute_content_hash(manifest_content),
            warnings=art.warnings,
        )
        result.extend([descriptor_artifact, manifest_artifact])
    return result
```

Add:

```python
def _with_schema_descriptor_metadata(
    manifest_content: str,
    *,
    descriptor_path: Path,
    descriptor_hash: str,
) -> str:
    manifest = json.loads(manifest_content)
    schema = manifest["schemas"][0]
    schema["descriptor"] = {
        "path": descriptor_path.name,
        "content_hash": descriptor_hash,
        "include_imports": True,
    }
    return json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
```

Wrap descriptor errors in the protobuf branch:

```python
        if descriptor_set:
            try:
                artifacts = _emit_protobuf_with_descriptors(artifacts, output)
            except DescriptorGenerationError as exc:
                raise click.ClickException(str(exc)) from exc
```

Then write returned artifacts with `_write_artifact`.

- [ ] **Step 5: Run focused Protobuf descriptor tests**

Run from `cli/`:

```powershell
uv run pytest tests/test_descriptor_artifacts.py -k "protobuf_descriptor_set" -q
```

Expected: pass.

- [ ] **Step 6: Run Protobuf emitter and compile tests**

Run from `cli/`:

```powershell
uv run pytest tests/test_emit_protobuf.py tests/test_descriptor_artifacts.py --tb=short -q
```

Expected: pass.

- [ ] **Step 7: Run required gate and commit Task 3**

Run from `cli/`:

```powershell
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
```

Expected: all pass.

Commit from repo root:

```powershell
git add cli/src/modelable/commands/compile.py cli/tests/test_descriptor_artifacts.py
git commit -m "feat: emit protobuf descriptor artifacts"
```

## Task 4: gRPC Descriptor Artifacts and Service Manifest Metadata

**Files:**
- Modify: `cli/src/modelable/commands/compile.py`
- Modify: `cli/tests/test_descriptor_artifacts.py`

**Interfaces:**
- Consumes: `compile_descriptor_set(...) -> bytes`
- Produces: `_with_service_descriptor_metadata(manifest_content: str, descriptor_path: Path, descriptor_hash: str) -> str`
- Produces: `_emit_grpc_with_descriptors(artifacts: list[EmittedArtifact], output: Path) -> list[EmittedArtifact]`
- Consumed by: Task 5 docs and final gates.

- [ ] **Step 1: Add failing gRPC descriptor CLI test with fake protoc**

Append to `cli/tests/test_descriptor_artifacts.py`:

```python
def test_compile_grpc_descriptor_set_writes_descriptor_and_service_manifest_metadata(tmp_path, monkeypatch):
    mdl = tmp_path / "platform.mdl"
    mdl.write_text(
        """
domain platform {
  owner: "platform-team"

  entity Order @ 1 (additive) {
    @key orderId: uuid
    customerId: uuid
  }
}
""",
        encoding="utf-8",
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    if sys.platform == "win32":
        _write_fake_protoc(
            bin_dir,
            body=(
                "@echo off\n"
                "for %%a in (%*) do (\n"
                "  echo %%a | findstr /b /c:\"--descriptor_set_out=\" >nul && set out=%%a\n"
                ")\n"
                "set out=%out:--descriptor_set_out=%\n"
                "echo grpc-descriptor> \"%out%\"\n"
            ),
        )
    else:
        _write_fake_protoc(
            bin_dir,
            body=(
                "#!/usr/bin/env sh\n"
                "for arg in \"$@\"; do\n"
                "  case \"$arg\" in --descriptor_set_out=*) out=${arg#--descriptor_set_out=};; esac\n"
                "done\n"
                "printf grpc-descriptor > \"$out\"\n"
            ),
        )
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    out = tmp_path / "dist"

    result = CliRunner().invoke(
        cli,
        ["compile", str(mdl), "--target", "grpc", "--out", str(out), "--descriptor-set"],
    )

    assert result.exit_code == 0, result.output
    descriptor = out / "platform" / "Order.v1" / "Order.v1.grpc.descriptor.pb"
    assert descriptor.read_bytes().strip() == b"grpc-descriptor"
    manifest = json.loads((out / "platform" / "Order.v1" / "service-manifest.json").read_text(encoding="utf-8"))
    assert manifest["descriptor"] == {
        "path": "Order.v1.grpc.descriptor.pb",
        "content_hash": compute_content_hash(descriptor.read_bytes()),
        "include_imports": True,
    }
```

- [ ] **Step 2: Add failing gRPC missing-protoc CLI test**

Append:

```python
def test_compile_grpc_descriptor_set_fails_when_protoc_is_missing(tmp_path, monkeypatch):
    mdl = tmp_path / "platform.mdl"
    mdl.write_text(
        """
domain platform {
  owner: "platform-team"

  entity Order @ 1 (additive) {
    @key orderId: uuid
  }
}
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))

    result = CliRunner().invoke(
        cli,
        ["compile", str(mdl), "--target", "grpc", "--out", str(tmp_path / "dist"), "--descriptor-set"],
    )

    assert result.exit_code != 0
    assert "descriptor generation requires protoc on PATH" in result.output
```

- [ ] **Step 3: Run tests and verify failure**

Run from `cli/`:

```powershell
uv run pytest tests/test_descriptor_artifacts.py -k "grpc_descriptor_set" -q
```

Expected: metadata test fails because grpc descriptor generation is not implemented yet.

- [ ] **Step 4: Add gRPC descriptor orchestration helpers**

In `cli/src/modelable/commands/compile.py`, add:

```python
def _emit_grpc_with_descriptors(artifacts: list[EmittedArtifact], output: Path) -> list[EmittedArtifact]:
    for art in artifacts:
        if art.path.name != "service-manifest.json":
            _write_artifact(art)

    result: list[EmittedArtifact] = []
    for art in artifacts:
        if art.path.name != "service-manifest.json":
            result.append(art)
            continue
        assert isinstance(art.content, str)
        manifest = json.loads(art.content)
        ref = str(manifest["ref"])
        service_proto = art.path.parent / str(manifest["service_proto"])
        payload_proto = art.path.parent / (art.path.parent.name + ".proto")
        descriptor_path = art.path.parent / (art.path.parent.name + ".grpc.descriptor.pb")
        proto_files = [service_proto]
        if payload_proto.exists():
            proto_files.append(payload_proto)
        descriptor_bytes = compile_descriptor_set(
            proto_root=output,
            proto_files=proto_files,
            out_path=descriptor_path,
            target_ref=ref,
        )
        descriptor_artifact = EmittedArtifact(
            target=art.target,
            ref=art.ref,
            artifact_id=f"{art.artifact_id}.descriptor",
            path=descriptor_path,
            content=descriptor_bytes,
            content_hash=compute_content_hash(descriptor_bytes),
        )
        manifest_content = _with_service_descriptor_metadata(
            art.content,
            descriptor_path=descriptor_path,
            descriptor_hash=descriptor_artifact.content_hash,
        )
        manifest_artifact = EmittedArtifact(
            target=art.target,
            ref=art.ref,
            artifact_id=art.artifact_id,
            path=art.path,
            content=manifest_content,
            content_hash=compute_content_hash(manifest_content),
            warnings=art.warnings,
        )
        result.extend([descriptor_artifact, manifest_artifact])
    return result
```

Add:

```python
def _with_service_descriptor_metadata(
    manifest_content: str,
    *,
    descriptor_path: Path,
    descriptor_hash: str,
) -> str:
    manifest = json.loads(manifest_content)
    manifest["descriptor"] = {
        "path": descriptor_path.name,
        "content_hash": descriptor_hash,
        "include_imports": True,
    }
    return json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
```

Wrap descriptor errors in the grpc branch:

```python
        if descriptor_set:
            try:
                artifacts = _emit_grpc_with_descriptors(artifacts, output)
            except DescriptorGenerationError as exc:
                raise click.ClickException(str(exc)) from exc
```

- [ ] **Step 5: Run focused gRPC descriptor tests**

Run from `cli/`:

```powershell
uv run pytest tests/test_descriptor_artifacts.py -k "grpc_descriptor_set" -q
```

Expected: pass.

- [ ] **Step 6: Run gRPC emitter and descriptor tests**

Run from `cli/`:

```powershell
uv run pytest tests/test_emit_grpc.py tests/test_descriptor_artifacts.py --tb=short -q
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

Expected: all pass.

Commit from repo root:

```powershell
git add cli/src/modelable/commands/compile.py cli/tests/test_descriptor_artifacts.py
git commit -m "feat: emit grpc descriptor artifacts"
```

## Task 5: Documentation, Roadmap, and Final Gates

**Files:**
- Modify: `docs/compiler-reference.md`
- Modify: `docs/cli-reference.md`
- Modify: `docs/wire-format-contract.md`
- Modify: `CHANGELOG.md`
- Modify: `ROADMAP.md`
- Modify: `cli/tests/test_descriptor_artifacts.py`

**Interfaces:**
- Consumes: `--descriptor-set` behavior from Tasks 1-4.
- Produces: public docs that descriptor artifacts are shipped while reservations and compatibility validation remain active follow-up work.

- [ ] **Step 1: Add default-no-descriptor regression for gRPC**

Append to `cli/tests/test_descriptor_artifacts.py`:

```python
def test_compile_grpc_without_descriptor_set_does_not_require_protoc_or_write_descriptor(tmp_path, monkeypatch):
    mdl = tmp_path / "platform.mdl"
    mdl.write_text(
        """
domain platform {
  owner: "platform-team"

  entity Order @ 1 (additive) {
    @key orderId: uuid
  }
}
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    out = tmp_path / "dist"

    result = CliRunner().invoke(cli, ["compile", str(mdl), "--target", "grpc", "--out", str(out)])

    assert result.exit_code == 0, result.output
    assert (out / "platform" / "Order.v1" / "Order.v1.grpc.proto").exists()
    assert not (out / "platform" / "Order.v1" / "Order.v1.grpc.descriptor.pb").exists()
    manifest = json.loads((out / "platform" / "Order.v1" / "service-manifest.json").read_text(encoding="utf-8"))
    assert "descriptor" not in manifest
```

- [ ] **Step 2: Run descriptor test suite**

Run from `cli/`:

```powershell
uv run pytest tests/test_descriptor_artifacts.py -q
```

Expected: pass.

- [ ] **Step 3: Update docs**

Update `docs/compiler-reference.md`:

- Target inventory rows:
  - Protobuf: `Implemented local artifact with opt-in descriptor artifacts and native supported maps; compatibility validation deferred`
  - Scalable gRPC profile: `Implemented local artifact with opt-in service descriptors and declared read-index metadata; compatibility validation deferred`
- Deferred target notes:
  - For Protobuf, state `--descriptor-set` emits `<Name>.v<version>.descriptor.pb`.
  - For gRPC, state `--descriptor-set` emits `<Name>.v<version>.grpc.descriptor.pb`.
  - Keep field reservations and Protobuf/gRPC compatibility validation deferred.

Update `docs/cli-reference.md`:

- Add `--descriptor-set` to the Protobuf options table:
  - Required: `No`
  - Default: disabled
  - Description: `Compile generated .proto files into per-schema descriptor .pb artifacts; requires protoc on PATH`
- Add the descriptor path to the Protobuf output layout.
- Add `--descriptor-set` to the gRPC options table:
  - Required: `No`
  - Default: disabled
  - Description: `Compile generated service profile into per-service descriptor .pb artifacts; requires protoc on PATH`
- Add the descriptor path to the gRPC output layout.

Update `docs/wire-format-contract.md`:

- Add a sentence after the golden-fixture section:
  `When --descriptor-set is used, Modelable also emits compiled descriptor artifacts. These descriptors are the compiled target-specific contract surface that later compatibility validation will compare.`

Update `CHANGELOG.md` under `[Unreleased] / Added`:

```markdown
- Added opt-in Protobuf and gRPC descriptor artifact generation via
  `compile --target protobuf|grpc --descriptor-set`.
```

Update `ROADMAP.md` Priority 1 item 4:

- Mark descriptor artifacts shipped inside item 4.
- Keep deleted-field reservations and Protobuf/gRPC compatibility validation as the next active part of item 4.

- [ ] **Step 4: Verify docs mention shipped behavior**

Run from repo root:

```powershell
rg -n -- "--descriptor-set|descriptor.pb|descriptor artifacts|descriptor-set generation|compatibility validation|reserved" ROADMAP.md CHANGELOG.md docs\compiler-reference.md docs\cli-reference.md docs\wire-format-contract.md
```

Expected: matches in all five files; roadmap still keeps reservations and compatibility validation active.

- [ ] **Step 5: Run focused behavior tests**

Run from `cli/`:

```powershell
uv run pytest tests/test_descriptor_artifacts.py tests/test_emit_protobuf.py tests/test_emit_grpc.py --tb=short -q
```

Expected: pass.

- [ ] **Step 6: Run docs build**

Run from repo root:

```powershell
uvx --from mkdocs==1.6.1 --with mkdocs-material==9.7.6 mkdocs build --strict
```

Expected: exit 0. Existing informational messages about unnaved `wire-format-contract.md` and excluded archived spec links are acceptable if unchanged.

- [ ] **Step 7: Run mandatory repository gates**

Run from `cli/`:

```powershell
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
```

Expected: all pass.

- [ ] **Step 8: Run doc-review**

Run the doc-review phases for changed docs:

```powershell
git diff --name-only main
git diff --check
rg -n "T[O]DO|T[B]D|implement lat[e]r|fill in detail[s]|appropriate error handl[i]ng" docs ROADMAP.md CHANGELOG.md
uvx --from mkdocs==1.6.1 --with mkdocs-material==9.7.6 mkdocs build --strict
```

Expected: no placeholders, no whitespace issues, docs build passes.

- [ ] **Step 9: Commit Task 5**

Commit from repo root:

```powershell
git add cli/tests/test_descriptor_artifacts.py docs/compiler-reference.md docs/cli-reference.md docs/wire-format-contract.md CHANGELOG.md ROADMAP.md
git commit -m "docs: document descriptor artifacts"
```

## Final Publish Checklist

After all tasks are committed:

- [ ] Run `git status --short --branch` from repo root; expected branch is `design/protobuf-grpc-descriptor-artifacts` with no unstaged changes.
- [ ] Run `git log --oneline main..HEAD`; expected commits are the design commit, this plan commit, and task commits.
- [ ] Push and open or update the draft PR:

```powershell
git push -u origin design/protobuf-grpc-descriptor-artifacts
```

The PR body must mention:

- opt-in `--descriptor-set`;
- Protobuf and gRPC descriptor artifacts;
- manifest descriptor metadata;
- `protoc` as the strict requested-generation boundary;
- default compile behavior not requiring `protoc`;
- docs updates and roadmap status;
- all verification commands and results;
- `Doc/spec review: all phases passed`.

## Self-Review

Spec coverage:

- Descriptor artifacts: Tasks 1, 3, and 4 cover binary artifacts, helper execution, Protobuf descriptors, and gRPC descriptors.
- Opt-in CLI behavior: Tasks 2, 3, 4, and 5 cover `--descriptor-set`, default no-descriptor behavior, and missing-`protoc` failures.
- Manifest metadata: Tasks 3 and 4 cover schema and service descriptor metadata.
- No new Python dependency: Task 1 uses `subprocess` and `shutil`, not Protobuf Python packages.
- Documentation and roadmap: Task 5 covers compiler, CLI, wire-format, changelog, roadmap, docs build, and doc-review.
- Deferred work remains explicit: Task 5 keeps reservations and compatibility validation active follow-up work.
