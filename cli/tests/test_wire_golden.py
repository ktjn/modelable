"""
Wire-format contract golden-fixture regression suite.

Pins the byte-exact Rust and Protobuf output documented in
docs/wire-format-contract.md. See that document for the encoding rules
this suite enforces and the update workflow for intentional emitter
changes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from modelable.compiler.workspace import load_workspace
from modelable.emitters.protobuf import emit_protobuf
from modelable.emitters.rust import emit_rust

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "wire_golden"
GOLDEN_DIR = FIXTURE_DIR / "golden"


@pytest.fixture(scope="module")
def wire_golden_workspace():
    return load_workspace(FIXTURE_DIR)


@pytest.fixture(scope="module")
def rust_artifacts(wire_golden_workspace, tmp_path_factory):
    out = tmp_path_factory.mktemp("wire_golden_rust")
    return emit_rust(wire_golden_workspace, out)


@pytest.fixture(scope="module")
def proto_artifacts(wire_golden_workspace, tmp_path_factory):
    out = tmp_path_factory.mktemp("wire_golden_proto")
    return emit_protobuf(wire_golden_workspace, out)


def test_wire_golden_fixture_validates_cleanly(wire_golden_workspace):
    assert wire_golden_workspace.errors == []


def test_rust_widget_output_matches_golden_file(rust_artifacts):
    art = next(a for a in rust_artifacts if a.ref == "platform.Widget@1")
    golden = (GOLDEN_DIR / "rust" / "platform_widget_v1.rs").read_text(encoding="utf-8")
    assert art.content == golden


def test_protobuf_widget_output_matches_golden_file(proto_artifacts):
    art = next(a for a in proto_artifacts if a.ref == "platform.Widget@1" and a.path.suffix == ".proto")
    golden = (GOLDEN_DIR / "protobuf" / "platform_widget_v1.proto").read_text(encoding="utf-8")
    assert art.content == golden


def test_every_golden_file_has_a_generation_source():
    """Guards against the fixture silently losing coverage: every committed
    golden file must correspond to a field/type this test suite actually
    exercises, not a stale leftover from a removed fixture.
    """
    rust_goldens = sorted((GOLDEN_DIR / "rust").glob("*.rs"))
    proto_goldens = sorted((GOLDEN_DIR / "protobuf").glob("*.proto"))
    assert [p.name for p in rust_goldens] == ["platform_widget_v1.rs"]
    assert [p.name for p in proto_goldens] == ["platform_widget_v1.proto"]
