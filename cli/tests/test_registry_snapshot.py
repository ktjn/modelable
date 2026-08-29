from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from modelable.cli import cli
from modelable.compiler.workspace import load_workspace
from modelable.registry.index import build_registry_from_snapshot
from modelable.registry.snapshot import (
    diff_workspace_snapshot,
    load_snapshot_workspace,
    prune_snapshot,
    resolve_workspace_snapshot,
    update_workspace_snapshot,
    verify_snapshot,
)
from modelable.registry.sources import LocalSourceAdapter

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


def test_resolve_records_exact_dependency_requirement(tmp_path: Path) -> None:
    source = tmp_path / "workspace.mdl"
    source.write_text(
        """
domain customer {
  owner: "customer-platform"
  entity Customer @ 1 (additive) {
    @key id: uuid
  }
  entity Customer @ 2 (additive) {
    @key id: uuid
    name?: string
  }
}
domain billing {
  owner: "billing-platform"
  projection Billing @ 1
    from customer.Customer @ >=1 <3 as c
  {
    id <- c.id
  }
}
""",
        encoding="utf-8",
    )

    result = resolve_workspace_snapshot(load_workspace(source), tmp_path / ".modelable")
    lock = json.loads(result.lock_path.read_text(encoding="utf-8"))

    requirements = [item for item in lock["requirements"] if item["from"] == "billing.Billing@1"]
    assert len(requirements) == 1
    requirement = requirements[0]
    assert requirement["requested"] == "customer.Customer@>=1<3"
    assert requirement["resolved"] == "customer.Customer@2"
    target = next(item for item in lock["objects"] if item["identity"] == requirement["resolved"])
    assert requirement["signature"] == target["signature"]
    assert requirement["object"] == target["content_hash"]


def test_resolve_records_enum_source_provenance(tmp_path: Path) -> None:
    source = tmp_path / "workspace.mdl"
    source.write_text(
        """
domain orders {
  owner: "orders-platform"
  semantic OrderStatus @ 1 (additive): enum(active, blocked)
  enum projection PublicStatus @ 1 (additive)
    from OrderStatus @ 1
    pick(active)
}
""",
        encoding="utf-8",
    )

    result = resolve_workspace_snapshot(load_workspace(source), tmp_path / ".modelable")
    lock = json.loads(result.lock_path.read_text(encoding="utf-8"))
    entries = {entry["identity"]: entry for entry in lock["objects"]}

    for identity in ("orders.OrderStatus@1", "orders.PublicStatus@1"):
        provenance = json.loads(
            (result.lock_path.parent / "registry" / "objects" / f"{entries[identity]['content_hash']}.json").read_text(
                encoding="utf-8"
            )
        )["provenance"]
        assert provenance["source"] == str(source)
        assert len(provenance["source_hash"]) == 64


def test_transitive_dependency_closure_rebuilds_offline_index(tmp_path: Path) -> None:
    source = tmp_path / "workspace.mdl"
    source.write_text(
        """
domain customer {
  owner: "customer-platform"
  entity Customer @ 1 (additive) {
    @key id: uuid
  }
}
domain billing {
  owner: "billing-platform"
  projection Billing @ 1
    from customer.Customer @ 1 as c
  {
    id <- c.id
  }
}
domain reporting {
  owner: "reporting-platform"
  projection CustomerReport @ 1
    from billing.Billing @ 1 as b
  {
    id <- b.id
  }
}
""",
        encoding="utf-8",
    )
    output_dir = tmp_path / ".modelable"
    result = resolve_workspace_snapshot(load_workspace(source), output_dir)
    lock = json.loads(result.lock_path.read_text(encoding="utf-8"))

    requirements = {(item["from"], item["resolved"]) for item in lock["requirements"]}
    assert ("billing.Billing@1", "customer.Customer@1") in requirements
    assert ("reporting.CustomerReport@1", "billing.Billing@1") in requirements

    loaded = load_snapshot_workspace(output_dir)
    assert {domain.name for domain in loaded.mdl.domains} == {"billing", "customer", "reporting"}
    index_path = build_registry_from_snapshot(output_dir)
    assert index_path == output_dir / "registry.db"


def test_verify_detects_non_deterministic_dependency_resolution(tmp_path: Path) -> None:
    source = tmp_path / "workspace.mdl"
    source.write_text(
        """
domain customer {
  owner: "customer-platform"
  entity Customer @ 1 (additive) {
    @key id: uuid
  }
  entity Customer @ 2 (additive) {
    @key id: uuid
    name?: string
  }
}
domain billing {
  owner: "billing-platform"
  projection Billing @ 1
    from customer.Customer @ >=1 <3 as c
  {
    id <- c.id
  }
}
""",
        encoding="utf-8",
    )
    output_dir = tmp_path / ".modelable"
    result = resolve_workspace_snapshot(load_workspace(source), output_dir)
    lock = json.loads(result.lock_path.read_text(encoding="utf-8"))
    requirement = next(item for item in lock["requirements"] if item["from"] == "billing.Billing@1")
    target = next(item for item in lock["objects"] if item["identity"] == "customer.Customer@1")
    requirement["resolved"] = target["identity"]
    requirement["signature"] = target["signature"]
    requirement["object"] = target["content_hash"]
    result.lock_path.write_text(json.dumps(lock), encoding="utf-8")

    errors = verify_snapshot(output_dir)

    assert any("but 'customer.Customer@>=1<3' selects customer.Customer@2" in error for error in errors)


def test_verify_detects_missing_dependency_requirement(tmp_path: Path) -> None:
    source = tmp_path / "workspace.mdl"
    source.write_text(
        """
domain customer {
  owner: "customer-platform"
  entity Customer @ 1 (additive) {
    @key id: uuid
  }
}
domain billing {
  owner: "billing-platform"
  projection Billing @ 1
    from customer.Customer @ 1 as c
  {
    id <- c.id
  }
}
""",
        encoding="utf-8",
    )
    output_dir = tmp_path / ".modelable"
    result = resolve_workspace_snapshot(load_workspace(source), output_dir)
    lock = json.loads(result.lock_path.read_text(encoding="utf-8"))
    lock["requirements"] = []
    result.lock_path.write_text(json.dumps(lock), encoding="utf-8")

    errors = verify_snapshot(output_dir)

    assert any("requirements do not match object dependency edges" in error for error in errors)


def test_verify_detects_conflicting_content_for_one_identity(tmp_path: Path) -> None:
    result = resolve_workspace_snapshot(load_workspace(FIXTURE), tmp_path / ".modelable")
    lock = json.loads(result.lock_path.read_text(encoding="utf-8"))
    first, second = lock["objects"]
    conflicting = dict(first)
    conflicting["content_hash"] = second["content_hash"]
    lock["objects"].append(conflicting)
    result.lock_path.write_text(json.dumps(lock), encoding="utf-8")

    errors = verify_snapshot(tmp_path / ".modelable")

    assert any("identity customer.Customer@1 has conflicting content hashes" in error for error in errors)


def test_verify_detects_tampered_object(tmp_path: Path) -> None:
    result = resolve_workspace_snapshot(load_workspace(FIXTURE), tmp_path / ".modelable")
    object_path = next((result.lock_path.parent / "registry" / "objects").glob("*.json"))
    payload = json.loads(object_path.read_text(encoding="utf-8"))
    payload["contract"]["version"] = 99
    object_path.write_text(json.dumps(payload), encoding="utf-8")

    errors = verify_snapshot(tmp_path / ".modelable")

    assert any("hash mismatch" in error for error in errors)


def test_verify_detects_missing_object(tmp_path: Path) -> None:
    result = resolve_workspace_snapshot(load_workspace(FIXTURE), tmp_path / ".modelable")
    object_path = next((result.lock_path.parent / "registry" / "objects").glob("*.json"))
    object_path.unlink()

    errors = verify_snapshot(tmp_path / ".modelable")

    assert any("missing registry object" in error for error in errors)


def test_verify_detects_source_drift(tmp_path: Path) -> None:
    source = tmp_path / "customer.mdl"
    source.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    output_dir = tmp_path / ".modelable"
    resolve_workspace_snapshot(load_workspace(source), output_dir)

    source.write_text(source.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    errors = verify_snapshot(output_dir)

    assert any("source drift" in error for error in errors)


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


def test_registry_resolve_uses_explicit_local_source_adapter(tmp_path: Path, monkeypatch) -> None:
    calls: list[Path] = []
    original_load = LocalSourceAdapter.load

    def recording_load(adapter: LocalSourceAdapter, source: Path):
        calls.append(source)
        return original_load(adapter, source)

    monkeypatch.setattr(LocalSourceAdapter, "load", recording_load)
    result = CliRunner().invoke(cli, ["registry", "resolve", str(FIXTURE), "--out", str(tmp_path / ".modelable")])

    assert result.exit_code == 0, result.output
    assert calls == [FIXTURE]


def test_registry_cli_status_reports_missing_object(tmp_path: Path) -> None:
    runner = CliRunner()
    output_dir = tmp_path / ".modelable"
    result = resolve_workspace_snapshot(load_workspace(FIXTURE), output_dir)
    next((result.lock_path.parent / "registry" / "objects").glob("*.json")).unlink()

    status = runner.invoke(cli, ["registry", "status", "--out", str(output_dir), "--format", "json"])

    assert status.exit_code == 1
    payload = json.loads(status.output)
    assert payload["valid"] is False
    assert any("missing registry object" in error for error in payload["errors"])


def test_update_stages_candidate_and_preserves_old_lock_on_diff(tmp_path: Path) -> None:
    workspace = load_workspace(FIXTURE)
    output_dir = tmp_path / ".modelable"
    resolve_workspace_snapshot(workspace, output_dir)
    source = tmp_path / "customer.mdl"
    source.write_text(
        FIXTURE.read_text(encoding="utf-8").replace("legalName: string", "legalName: string\n    region: string"),
        encoding="utf-8",
    )
    changed_workspace = load_workspace(source)

    snapshot_diff = diff_workspace_snapshot(changed_workspace, output_dir)
    original_lock = (output_dir / "registry.lock").read_bytes()

    assert snapshot_diff.changed
    assert (output_dir / "registry.lock").read_bytes() == original_lock

    _, applied_diff = update_workspace_snapshot(changed_workspace, output_dir)

    assert applied_diff.changed == snapshot_diff.changed
    assert verify_snapshot(output_dir) == []
