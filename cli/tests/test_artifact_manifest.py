from __future__ import annotations

import hashlib
import json
from pathlib import Path

from click.testing import CliRunner

from modelable.cli import cli
from modelable.compiler.workspace import load_workspace
from modelable.extensions import PROTOCOL, ExtensionDescriptor, pin_extension_descriptor
from modelable.registry.snapshot import resolve_workspace_snapshot


def test_compile_writes_deterministic_artifact_manifest(tmp_path: Path) -> None:
    source = tmp_path / "customer.mdl"
    source.write_text(
        """
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    @key
    customerId: uuid
    name: string
  }
}
""".strip(),
        encoding="utf-8",
    )
    output = tmp_path / "dist"
    result = CliRunner().invoke(cli, ["compile", str(source), "--target", "typescript", "--out", str(output)])

    assert result.exit_code == 0, result.output
    manifest_path = output / "modelable-artifact-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["format"] == "modelable.artifact-manifest.v1"
    assert manifest["target"] == {"kind": "language", "name": "typescript", "status": "implemented"}
    assert manifest["extensions"] == [
        {
            "accepted_plan_versions": ["modelable.plan/v0", "modelable.plan/v1"],
            "capabilities": ["enums", "maps", "records", "semantic-types"],
            "compatibility_support": False,
            "configuration_schema": None,
            "id": "modelable.target.typescript",
            "output_kinds": ["language"],
            "protocol": "modelable.extension/v1",
            "version": manifest["compiler"]["version"],
        }
    ]
    assert manifest["inputs"][0]["path"] == "customer.mdl"
    assert manifest["inputs"][0]["signature"]
    assert manifest["snapshot"]["sha256"] is None
    assert "overlay" not in manifest
    assert manifest["plugins"] == []
    assert manifest["extension_pins"] == []
    assert {entry["path"] for entry in manifest["artifacts"]} == {"customer.Customer.v1.ts"}
    assert all(entry["sha256"] for entry in manifest["artifacts"])


def test_compile_carries_verified_extension_pins_into_manifest(tmp_path: Path) -> None:
    source = tmp_path / "customer.mdl"
    source.write_text(
        """
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""".strip(),
        encoding="utf-8",
    )
    descriptor = ExtensionDescriptor(
        protocol=PROTOCOL,
        id="example.target",
        version="1.2.3",
        accepted_plan_versions=("modelable.plan/v0",),
        capabilities=("records",),
        configuration_schema=None,
        output_kinds=("artifact",),
        compatibility_support=False,
    )
    pin = pin_extension_descriptor(descriptor, "a" * 64, source="oci://example/target")
    resolve_workspace_snapshot(load_workspace(tmp_path), tmp_path / ".modelable", extension_pins=(pin,))

    result = CliRunner().invoke(
        cli, ["compile", str(source), "--target", "typescript", "--out", str(tmp_path / "dist")]
    )

    assert result.exit_code == 0, result.output
    manifest = json.loads((tmp_path / "dist" / "modelable-artifact-manifest.json").read_text(encoding="utf-8"))
    assert manifest["extension_pins"] == [pin.as_dict()]


def test_compile_records_overlay_provenance_in_manifest(tmp_path: Path) -> None:
    source = tmp_path / "customer.mdl"
    source.write_text(
        """
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    @key
    customerId: uuid
  }
}
""".strip(),
        encoding="utf-8",
    )
    overlay = tmp_path / "postgres.toml"
    overlay.write_text(
        """
target = "sql-postgres"
version = 1

[models."customer.Customer@1"]
table = "customers"
""".strip(),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli,
        [
            "compile",
            str(source),
            "--target",
            "sql-postgres",
            "--overlay",
            str(overlay),
            "--out",
            str(tmp_path / "dist"),
        ],
    )

    assert result.exit_code == 0, result.output
    manifest = json.loads((tmp_path / "dist" / "modelable-artifact-manifest.json").read_text(encoding="utf-8"))
    assert manifest["overlay"] == {
        "path": "postgres.toml",
        "sha256": hashlib.sha256(overlay.read_bytes()).hexdigest(),
    }
