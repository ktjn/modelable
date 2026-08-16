from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from modelable.cli import cli
from modelable.compiler.workspace import load_workspace


def test_config_explain_reports_file_provenance(tmp_path: Path) -> None:
    (tmp_path / "modelable.toml").write_text(
        '[defaults]\nauto_projections = ["db", "reply"]\ngenerate_conversions = false\n', encoding="utf-8"
    )

    result = CliRunner().invoke(
        cli, ["config", "explain", "customer.Customer@1", "--path", str(tmp_path), "--format", "json"]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["auto_projections"]["value"] == ["db", "reply"]
    assert "modelable.toml" in payload["auto_projections"]["provenance"]


def test_config_defaults_lower_to_auto_projections(tmp_path: Path) -> None:
    (tmp_path / "modelable.toml").write_text('[defaults]\nauto_projections = ["db", "reply"]\n', encoding="utf-8")
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

    workspace = load_workspace(tmp_path)

    assert not workspace.errors
    projection_names = set(workspace.mdl.domains[0].projections)
    assert projection_names == {"CustomerDb", "CustomerReply"}
