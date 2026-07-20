from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from modelable.cli import cli
from modelable.emitters.base import EmittedArtifact, compute_content_hash
from modelable.emitters.descriptors import DescriptorGenerationError, compile_descriptor_set
from modelable.operations.compilation import _write_artifact


def _write_fake_protoc(path: Path, *, body: str) -> Path:
    if sys.platform == "win32":
        script = path / "protoc.cmd"
        script.write_text(body, encoding="utf-8")
        return script
    script = path / "protoc"
    script.write_text(body, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


def _write_python_fake_protoc(path: Path, *, source: str) -> Path:
    script = path / "fake_protoc.py"
    script.write_text(source, encoding="utf-8")
    if sys.platform == "win32":
        wrapper = path / "protoc.cmd"
        wrapper.write_text(f'@"{sys.executable}" "{script}" %*\n', encoding="utf-8")
        return wrapper
    wrapper = path / "protoc"
    wrapper.write_text(f'#!/usr/bin/env sh\n"{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)
    return wrapper


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
    _write_python_fake_protoc(
        bin_dir,
        source=(
            "from pathlib import Path\n"
            "import sys\n"
            f"Path({str(calls_path)!r}).write_text(' '.join(sys.argv[1:]), encoding='utf-8')\n"
            "out = next(arg.split('=', 1)[1] for arg in sys.argv[1:] if arg.startswith('--descriptor_set_out='))\n"
            "Path(out).write_bytes(b'descriptor')\n"
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

    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["compile", str(mdl), "--target", "protobuf", "--out", str(out)])

    assert result.exit_code == 0, result.output
    assert (out / "platform" / "Order.v1" / "Order.v1.proto").exists()
    assert not (out / "platform" / "Order.v1" / "Order.v1.descriptor.pb").exists()


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
    _write_python_fake_protoc(
        bin_dir,
        source=(
            "from pathlib import Path\n"
            "import sys\n"
            "out = next(arg.split('=', 1)[1] for arg in sys.argv[1:] if arg.startswith('--descriptor_set_out='))\n"
            "Path(out).write_bytes(b'protobuf-descriptor')\n"
        ),
    )
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    out = tmp_path / "dist"

    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(
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

    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(
            cli,
            ["compile", str(mdl), "--target", "protobuf", "--out", str(tmp_path / "dist"), "--descriptor-set"],
        )

    assert result.exit_code != 0
    assert "descriptor generation requires protoc on PATH" in result.output


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
    _write_python_fake_protoc(
        bin_dir,
        source=(
            "from pathlib import Path\n"
            "import sys\n"
            "out = next(arg.split('=', 1)[1] for arg in sys.argv[1:] if arg.startswith('--descriptor_set_out='))\n"
            "Path(out).write_bytes(b'grpc-descriptor')\n"
        ),
    )
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    out = tmp_path / "dist"

    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(
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

    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(
            cli,
            ["compile", str(mdl), "--target", "grpc", "--out", str(tmp_path / "dist"), "--descriptor-set"],
        )

    assert result.exit_code != 0
    assert "descriptor generation requires protoc on PATH" in result.output


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

    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["compile", str(mdl), "--target", "grpc", "--out", str(out)])

    assert result.exit_code == 0, result.output
    assert (out / "platform" / "Order.v1" / "Order.v1.grpc.proto").exists()
    assert not (out / "platform" / "Order.v1" / "Order.v1.grpc.descriptor.pb").exists()
    manifest = json.loads((out / "platform" / "Order.v1" / "service-manifest.json").read_text(encoding="utf-8"))
    assert "descriptor" not in manifest
