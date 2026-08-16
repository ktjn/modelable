from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from modelable.cli import cli
from modelable.compiler.workspace import load_workspace
from modelable.registry.snapshot import (
    prune_snapshot,
    resolve_workspace_snapshot,
    verify_snapshot,
)

FIXTURE = Path(__file__).parent / "fixtures" / "customer.mdl"


def test_resolve_writes_deterministic_lock_and_objects(tmp_path: Path) -> None:
    workspace = load_workspace(FIXTURE)
    first = resolve_workspace_snapshot(workspace, tmp_path / ".modelable")
    first_lock = first.lock_path.read_bytes()
    first_objects = sorted((tmp_path / ".modelable" / "registry" / "objects").glob("*.json"))

    second = resolve_workspace_snapshot(workspace, tmp_path / ".modelable")

    assert second.object_count == 2
    assert first_lock == second.lock_path.read_bytes()
    assert first_objects == sorted((tmp_path / ".modelable" / "registry" / "objects").glob("*.json"))
    assert verify_snapshot(tmp_path / ".modelable") == []
    lock = json.loads(first.lock_path.read_text(encoding="utf-8"))
    assert [entry["identity"] for entry in lock["objects"]] == ["customer.Customer@1", "customer.Customer@2"]


def test_verify_detects_tampered_object(tmp_path: Path) -> None:
    result = resolve_workspace_snapshot(load_workspace(FIXTURE), tmp_path / ".modelable")
    object_path = next((result.lock_path.parent / "registry" / "objects").glob("*.json"))
    payload = json.loads(object_path.read_text(encoding="utf-8"))
    payload["contract"]["version"] = 99
    object_path.write_text(json.dumps(payload), encoding="utf-8")

    errors = verify_snapshot(tmp_path / ".modelable")

    assert any("hash mismatch" in error for error in errors)


def test_prune_removes_unreachable_objects(tmp_path: Path) -> None:
    result = resolve_workspace_snapshot(load_workspace(FIXTURE), tmp_path / ".modelable")
    objects = result.lock_path.parent / "registry" / "objects"
    orphan = objects / ("f" * 64 + ".json")
    orphan.write_text("{}", encoding="utf-8")

    assert prune_snapshot(tmp_path / ".modelable") == 1
    assert not orphan.exists()


def test_registry_cli_resolve_and_verify_json(tmp_path: Path) -> None:
    runner = CliRunner()
    output_dir = tmp_path / ".modelable"

    resolved = runner.invoke(cli, ["registry", "resolve", str(FIXTURE), "--out", str(output_dir)])
    verified = runner.invoke(cli, ["registry", "verify", "--out", str(output_dir), "--format", "json"])

    assert resolved.exit_code == 0, resolved.output
    assert verified.exit_code == 0, verified.output
    assert json.loads(verified.output) == {"valid": True, "errors": []}
