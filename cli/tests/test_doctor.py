from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from modelable.cli import cli


def test_doctor_reports_healthy_workspace_and_missing_snapshot(tmp_path: Path) -> None:
    (tmp_path / "customer.mdl").write_text(
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

    result = CliRunner().invoke(cli, ["doctor", str(tmp_path), "--format", "json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["kind"] == "doctor_report"
    assert payload["workspace"]["errors"] == 0
    assert payload["snapshot"]["valid"] is False


def test_doctor_accepts_resolved_snapshot(tmp_path: Path) -> None:
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
    runner = CliRunner()
    assert (
        runner.invoke(cli, ["registry", "resolve", str(source), "--out", str(tmp_path / ".modelable")]).exit_code == 0
    )

    result = runner.invoke(cli, ["doctor", str(tmp_path), "--format", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["healthy"] is True
    assert payload["registry_index"]["valid"] is True


def test_doctor_detects_tampered_generated_artifact(tmp_path: Path) -> None:
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
    runner = CliRunner()
    assert (
        runner.invoke(cli, ["registry", "resolve", str(source), "--out", str(tmp_path / ".modelable")]).exit_code == 0
    )
    output = tmp_path / "dist"
    assert runner.invoke(cli, ["compile", str(source), "--target", "typescript", "--out", str(output)]).exit_code == 0
    artifact = next(output.glob("*.ts"))
    artifact.write_text(artifact.read_text(encoding="utf-8") + "// tampered\n", encoding="utf-8")

    result = runner.invoke(cli, ["doctor", str(tmp_path), "--format", "json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["healthy"] is False
    assert any("hash mismatch" in error for error in payload["artifact_manifests"]["errors"])
