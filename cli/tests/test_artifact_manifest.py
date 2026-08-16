from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from modelable.cli import cli


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
    assert manifest["inputs"][0]["path"] == "customer.mdl"
    assert manifest["inputs"][0]["signature"]
    assert manifest["snapshot"]["sha256"] is None
    assert manifest["plugins"] == []
    assert {entry["path"] for entry in manifest["artifacts"]} == {"customer.Customer.v1.ts"}
    assert all(entry["sha256"] for entry in manifest["artifacts"])
