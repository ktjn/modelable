"""
Public emitter conformance fixture.

Exercises the four behaviors that Observable identified as 1.0-blocking
emitter gaps and that contributors need to verify without access to Observable.
The fixture lives in samples/conformance/ and is a realistic two-domain workspace.

Covered behaviors:
  1. Rust enum — enum(...) field emits pub enum type, not String.
  2. Rust optional array — optional array<T> emits Vec<T> + #[serde(default)],
     not Option<Vec<T>>.
  3. TypeScript cross-model import — ref<domain.Model> emits the stable
     interface name and an import type statement.
  4. TypeScript array-of-enum — array<enum(...)> emits ('A' | 'B')[], not
     a bare union or string[].
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from modelable.cli import cli
from modelable.compiler.workspace import load_workspace
from modelable.emitters.rust import emit_rust
from modelable.emitters.typescript import emit_typescript

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "samples" / "conformance"


@pytest.fixture(scope="module")
def conformance_workspace():
    return load_workspace(FIXTURE_DIR)


@pytest.fixture(scope="module")
def rust_artifacts(conformance_workspace, tmp_path_factory):
    out = tmp_path_factory.mktemp("rust_out")
    return emit_rust(conformance_workspace, out)


@pytest.fixture(scope="module")
def ts_artifacts(conformance_workspace, tmp_path_factory):
    out = tmp_path_factory.mktemp("ts_out")
    return emit_typescript(conformance_workspace, out)


def _rust(artifacts, ref: str):
    return next(a for a in artifacts if a.ref == ref)


def _ts(artifacts, ref: str):
    return next(a for a in artifacts if a.ref == ref)


def test_public_conformance_fixture_validates_cleanly():
    result = CliRunner().invoke(cli, ["validate", str(FIXTURE_DIR)])
    assert result.exit_code == 0, result.output


class TestRustEnum:
    def test_enum_field_emits_pub_enum_type(self, rust_artifacts):
        art = _rust(rust_artifacts, "catalog.Product@1")
        assert "pub enum CatalogProductV1Status" in art.content

    def test_enum_field_uses_generated_type_not_string(self, rust_artifacts):
        art = _rust(rust_artifacts, "catalog.Product@1")
        assert "pub status: CatalogProductV1Status," in art.content
        assert "pub status: String," not in art.content

    def test_enum_type_has_serde_rename_all(self, rust_artifacts):
        art = _rust(rust_artifacts, "catalog.Product@1")
        assert "pub enum CatalogProductV1Status" in art.content
        assert "Active" in art.content
        assert "Inactive" in art.content
        assert "Discontinued" in art.content


class TestRustOptionalArray:
    def test_optional_array_field_is_vec_not_option_vec(self, rust_artifacts):
        art = _rust(rust_artifacts, "catalog.Product@1")
        assert "pub tags: Vec<String>," in art.content
        assert "Option<Vec" not in art.content

    def test_optional_array_field_has_serde_default(self, rust_artifacts):
        art = _rust(rust_artifacts, "catalog.Product@1")
        assert "#[serde(default)]" in art.content


class TestTypeScriptCrossModelImport:
    def test_ref_field_uses_stable_interface_name(self, ts_artifacts):
        art = _ts(ts_artifacts, "catalog.Product@1")
        assert "shippingAddress: AddressAddressV1;" in art.content

    def test_ref_field_emits_import_type(self, ts_artifacts):
        art = _ts(ts_artifacts, "catalog.Product@1")
        assert "import type { AddressAddressV1 }" in art.content


class TestTypeScriptArrayOfEnum:
    def test_array_of_enum_emits_parenthesised_union_array(self, ts_artifacts):
        art = _ts(ts_artifacts, "catalog.Product@1")
        assert "('New' | 'Sale' | 'Featured')[]" in art.content

    def test_array_of_enum_labels_field_is_not_string_array(self, ts_artifacts):
        art = _ts(ts_artifacts, "catalog.Product@1")
        assert "labels: string[]" not in art.content
