from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from modelable.cli import cli
from modelable.compiler.workspace import load_workspace
from modelable.config import load_config


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


def test_config_exposes_workspace_relative_target_overlay(tmp_path: Path) -> None:
    (tmp_path / "modelable.toml").write_text(
        '[[target]]\nname = "sql-postgres"\noverlay = "modelable.extensions/postgres.toml"\n',
        encoding="utf-8",
    )

    config = load_config(tmp_path)

    assert config.overlay_for_target("sql-postgres") == Path("modelable.extensions/postgres.toml")


def test_config_rejects_absolute_target_overlay(tmp_path: Path) -> None:
    outside = tmp_path / "outside.toml"
    (tmp_path / "modelable.toml").write_text(
        f"[[target]]\nname = 'sql-postgres'\noverlay = '{outside.as_posix()}'\n",
        encoding="utf-8",
    )

    config = load_config(tmp_path)

    with pytest.raises(ValueError, match="workspace-relative"):
        config.overlay_for_target("sql-postgres")


def test_config_loads_registry_blocked_actions(tmp_path: Path) -> None:
    (tmp_path / "modelable.toml").write_text(
        '[registry]\nblocked_actions = ["breaking", "storage_migration"]\n', encoding="utf-8"
    )

    config = load_config(tmp_path)

    assert config.blocked_registry_actions() == ("breaking", "storage_migration")


def test_config_loads_registry_policy_severity(tmp_path: Path) -> None:
    (tmp_path / "modelable.toml").write_text('[registry.policy]\npii_changes = "error"\n', encoding="utf-8")

    config = load_config(tmp_path)

    assert config.registry_policy_severities() == {"lifecycle_references": "off", "pii_changes": "error"}


def test_config_rejects_invalid_registry_policy_severity(tmp_path: Path) -> None:
    (tmp_path / "modelable.toml").write_text('[registry.policy]\npii_changes = "critical"\n', encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported registry policy severity"):
        load_config(tmp_path)


def test_config_rejects_unknown_registry_blocked_action(tmp_path: Path) -> None:
    (tmp_path / "modelable.toml").write_text('[registry]\nblocked_actions = ["unknown"]\n', encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported registry blocked action"):
        load_config(tmp_path)
