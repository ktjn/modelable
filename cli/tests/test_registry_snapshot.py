from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

import modelable.registry.snapshot as snapshot_module
from modelable.cli import cli
from modelable.compat.checker import analyze_impact, check_model_version_compatibility
from modelable.compiler.workspace import load_workspace
from modelable.extensions import PROTOCOL, ExtensionDescriptor, pin_extension_descriptor
from modelable.registry.enum_numbers import allocate_enum_numbers
from modelable.registry.enum_numbers import write_lock_file as write_enum_numbers_lock_file
from modelable.registry.ids import allocate_registry_ids
from modelable.registry.ids import write_lock_file as write_registry_ids_lock_file
from modelable.registry.index import build_registry_from_snapshot
from modelable.registry.resolver import find_dependents
from modelable.registry.snapshot import (
    diff_workspace_snapshot,
    evaluate_registry_policy,
    load_snapshot_workspace,
    load_workspace_with_snapshot,
    prune_snapshot,
    resolve_workspace_snapshot,
    update_workspace_snapshot,
    verify_snapshot,
)
from modelable.registry.sources import GitSourceAdapter, LocalSourceAdapter
from modelable.registry.usage import build_usage_manifest

FIXTURE = Path(__file__).parent / "fixtures" / "customer.mdl"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True)


def test_git_source_adapter_loads_tracked_mdl_from_local_ref(tmp_path: Path) -> None:
    repository = tmp_path / "contracts"
    repository.mkdir()
    _git(repository, "init", "--quiet")
    _git(repository, "config", "user.email", "modelable-tests@example.invalid")
    _git(repository, "config", "user.name", "Modelable Tests")
    (repository / "customer.mdl").write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    _git(repository, "add", "customer.mdl")
    _git(repository, "commit", "--quiet", "-m", "initial contracts")

    workspace = GitSourceAdapter(repository, "HEAD").load(repository)

    assert workspace.errors == []
    assert [domain.name for domain in workspace.mdl.domains] == ["customer"]
    assert workspace.sources[0].path is None
    assert workspace.sources[0].uri.startswith("git+file://")
    assert "@HEAD/customer.mdl" in workspace.sources[0].uri


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


def test_resolve_persists_deterministic_usage_evidence(tmp_path: Path) -> None:
    workspace = load_workspace(FIXTURE)
    output_dir = tmp_path / ".modelable"

    result = resolve_workspace_snapshot(workspace, output_dir)
    lock = json.loads(result.lock_path.read_text(encoding="utf-8"))

    assert lock["usage"] == build_usage_manifest(workspace)
    assert verify_snapshot(output_dir) == []

    first_lock = result.lock_path.read_bytes()
    resolve_workspace_snapshot(workspace, output_dir)
    assert result.lock_path.read_bytes() == first_lock


def test_verify_rejects_usage_evidence_with_a_mismatched_signature(tmp_path: Path) -> None:
    output_dir = tmp_path / ".modelable"
    result = resolve_workspace_snapshot(load_workspace(FIXTURE), output_dir)
    lock = json.loads(result.lock_path.read_text(encoding="utf-8"))
    lock["usage"]["references"][0]["signature"] = "0" * 64
    result.lock_path.write_text(json.dumps(lock), encoding="utf-8")

    errors = verify_snapshot(output_dir)

    assert any("usage reference customer.Customer@1 signature" in error for error in errors)


def test_resolve_persists_deterministic_extension_pins(tmp_path: Path) -> None:
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

    result = resolve_workspace_snapshot(load_workspace(FIXTURE), tmp_path / ".modelable", extension_pins=(pin,))
    lock = json.loads(result.lock_path.read_text(encoding="utf-8"))

    assert lock["extensions"] == [pin.as_dict()]
    assert verify_snapshot(tmp_path / ".modelable") == []


def test_resolve_captures_protobuf_enum_allocations_in_lock(tmp_path: Path) -> None:
    source = tmp_path / "workspace.mdl"
    source.write_text(
        """
domain orders {
  owner: "orders-platform"
  semantic OrderStatus @ 1 (additive): enum(pending, active)
}
""".strip(),
        encoding="utf-8",
    )
    workspace = load_workspace(source)
    enum_numbers_path = tmp_path / "enum-numbers.lock"
    allocations = allocate_enum_numbers(workspace.mdl, {})
    write_enum_numbers_lock_file(enum_numbers_path, allocations)

    result = resolve_workspace_snapshot(
        workspace,
        tmp_path / ".modelable",
    )
    lock = json.loads(result.lock_path.read_text(encoding="utf-8"))

    allocation = lock["allocations"]["protobuf_enums"][0]
    assert allocation == {
        "name": "orders.OrderStatus",
        "unspecified": 0,
        "members": [{"name": "pending", "number": 1}, {"name": "active", "number": 2}],
        "reservations": [],
        "content_hash": allocation["content_hash"],
    }
    assert len(allocation["content_hash"]) == 64
    assert verify_snapshot(result.lock_path.parent) == []


def test_verify_rejects_tampered_protobuf_allocation_metadata(tmp_path: Path) -> None:
    source = tmp_path / "workspace.mdl"
    source.write_text(
        """
domain orders {
  owner: "orders-platform"
  semantic OrderStatus @ 1 (additive): enum(pending, active)
}
""".strip(),
        encoding="utf-8",
    )
    workspace = load_workspace(source)
    enum_numbers_path = tmp_path / "enum-numbers.lock"
    write_enum_numbers_lock_file(enum_numbers_path, allocate_enum_numbers(workspace.mdl, {}))
    result = resolve_workspace_snapshot(
        workspace,
        tmp_path / ".modelable",
        enum_numbers_path=enum_numbers_path,
    )
    lock = json.loads(result.lock_path.read_text(encoding="utf-8"))
    lock["allocations"]["protobuf_enums"][0]["members"][0]["number"] = 99
    result.lock_path.write_text(json.dumps(lock), encoding="utf-8")

    errors = verify_snapshot(result.lock_path.parent)

    assert any("protobuf enum allocation orders.OrderStatus content hash" in error for error in errors)


def test_resolve_captures_registry_ids_in_lock(tmp_path: Path) -> None:
    source = tmp_path / "workspace.mdl"
    source.write_text(
        """
domain platform {
  owner: "platform-team"
  semantic CommandId : u32 { registry: true }
}
""".strip(),
        encoding="utf-8",
    )
    workspace = load_workspace(source)
    registry_ids_path = tmp_path / "registry-ids.lock"
    write_registry_ids_lock_file(registry_ids_path, allocate_registry_ids(workspace.mdl, {}))

    result = resolve_workspace_snapshot(workspace, tmp_path / ".modelable")
    lock = json.loads(result.lock_path.read_text(encoding="utf-8"))

    allocation = lock["allocations"]["registry_ids"][0]
    assert allocation["name"] == "platform.CommandId"
    assert allocation["id"] == 1
    assert len(allocation["content_hash"]) == 64
    assert verify_snapshot(result.lock_path.parent) == []


def test_verify_rejects_tampered_registry_id_allocation(tmp_path: Path) -> None:
    source = tmp_path / "workspace.mdl"
    source.write_text(
        """
domain platform {
  owner: "platform-team"
  semantic CommandId : u32 { registry: true }
}
""".strip(),
        encoding="utf-8",
    )
    workspace = load_workspace(source)
    registry_ids_path = tmp_path / "registry-ids.lock"
    write_registry_ids_lock_file(registry_ids_path, allocate_registry_ids(workspace.mdl, {}))
    result = resolve_workspace_snapshot(workspace, tmp_path / ".modelable")
    lock = json.loads(result.lock_path.read_text(encoding="utf-8"))
    lock["allocations"]["registry_ids"][0]["id"] = 99
    result.lock_path.write_text(json.dumps(lock), encoding="utf-8")

    errors = verify_snapshot(result.lock_path.parent)

    assert any("registry ID allocation platform.CommandId content hash" in error for error in errors)


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


def test_consumer_composes_with_provider_snapshot_offline(tmp_path: Path) -> None:
    provider = tmp_path / "provider.mdl"
    provider.write_text(
        """
domain customer {
  owner: "customer-platform"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    legalName: string
  }
}
""",
        encoding="utf-8",
    )
    consumer = tmp_path / "consumer.mdl"
    consumer.write_text(
        """
domain analytics {
  owner: "analytics-platform"
  projection CustomerSummary @ 1
    from customer.Customer @ 1 as c
  {
    customerId <- c.customerId
    name <- c.legalName
  }
}
""",
        encoding="utf-8",
    )

    provider_workspace = load_workspace(provider)
    snapshot_dir = tmp_path / ".modelable"
    resolve_workspace_snapshot(provider_workspace, snapshot_dir)

    consumer_workspace = load_workspace(consumer)
    assert consumer_workspace.errors
    composed = load_workspace_with_snapshot(consumer_workspace, snapshot_dir)

    assert composed.errors == []
    assert {domain.name for domain in composed.mdl.domains} == {"analytics", "customer"}
    assert composed.mdl.domains[0].projections["CustomerSummary"][0].fields[0].name == "customerId"


def test_historical_snapshot_rebuilds_without_original_source(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "provider.mdl"
    source.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    snapshot_dir = tmp_path / ".modelable"

    resolve_workspace_snapshot(load_workspace(source), snapshot_dir)
    source.unlink()

    def forbidden_operation(*_args, **_kwargs):
        raise AssertionError("historical snapshot attempted a source refresh")

    monkeypatch.setattr(LocalSourceAdapter, "load", forbidden_operation)
    monkeypatch.setattr("urllib.request.urlopen", forbidden_operation)

    assert verify_snapshot(snapshot_dir) == []
    loaded = load_snapshot_workspace(snapshot_dir)
    assert {domain.name for domain in loaded.mdl.domains} == {"customer"}
    assert build_registry_from_snapshot(snapshot_dir) == snapshot_dir / "registry.db"


def test_snapshot_transition_classifies_compatible_and_breaking_candidate(tmp_path: Path) -> None:
    provider_v1 = tmp_path / "provider-v1.mdl"
    provider_v1.write_text(
        """
domain customer {
  owner: "customer-platform"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    legalName: string
  }
}
""",
        encoding="utf-8",
    )
    provider_compatible = tmp_path / "provider-compatible.mdl"
    provider_compatible.write_text(
        """
domain customer {
  owner: "customer-platform"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    legalName: string
  }
  entity Customer @ 2 (additive) {
    @key customerId: uuid
    legalName: string
    segment?: string
  }
}
""",
        encoding="utf-8",
    )
    provider_breaking = tmp_path / "provider-breaking.mdl"
    provider_breaking.write_text(
        """
domain customer {
  owner: "customer-platform"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    legalName: string
  }
  entity Customer @ 2 (breaking) {
    @key customerId: uuid
  }
}
""",
        encoding="utf-8",
    )
    consumer = tmp_path / "consumer.mdl"
    consumer.write_text(
        """
domain analytics {
  owner: "analytics-platform"
  projection CustomerSummary @ 1
    from customer.Customer @ 1 as c
  {
    customerId <- c.customerId
    name <- c.legalName
  }
}
""",
        encoding="utf-8",
    )

    current_dir = tmp_path / "current"
    resolve_workspace_snapshot(load_workspace(provider_v1), current_dir)
    consumer_workspace = load_workspace(consumer)
    current_composed = load_workspace_with_snapshot(consumer_workspace, current_dir)
    assert current_composed.errors == []

    compatible_workspace = load_workspace(provider_compatible)
    compatible_report = check_model_version_compatibility(compatible_workspace.mdl, "customer", "Customer", 1, 2)
    assert compatible_report.status == "compatible"
    runner = CliRunner()
    compatible_cli = runner.invoke(
        cli,
        ["diff", "customer.Customer@1", "customer.Customer@2", "--path", str(provider_compatible)],
    )
    assert compatible_cli.exit_code == 0, compatible_cli.output
    assert "status: compatible" in compatible_cli.output
    compatible_dependents = find_dependents(current_composed.mdl, "customer", "Customer", 1)
    assert compatible_dependents == [("analytics", "CustomerSummary", 1)]
    assert analyze_impact(current_composed.mdl, compatible_report, compatible_dependents[0]).status == "compatible"

    compatible_dir = tmp_path / "compatible"
    resolve_workspace_snapshot(compatible_workspace, compatible_dir)
    compatible_composed = load_workspace_with_snapshot(consumer_workspace, compatible_dir)
    assert compatible_composed.errors == []
    assert {domain.name for domain in compatible_composed.mdl.domains} == {"analytics", "customer"}

    breaking_workspace = load_workspace(provider_breaking)
    breaking_report = check_model_version_compatibility(breaking_workspace.mdl, "customer", "Customer", 1, 2)
    assert breaking_report.status == "breaking"
    breaking_cli = runner.invoke(
        cli,
        ["diff", "customer.Customer@1", "customer.Customer@2", "--path", str(provider_breaking)],
    )
    assert breaking_cli.exit_code != 0
    assert "status: breaking" in breaking_cli.output
    assert analyze_impact(current_composed.mdl, breaking_report, compatible_dependents[0]).status == "broken"
    assert json.loads((current_dir / "registry.lock").read_text(encoding="utf-8"))["objects"][-1]["identity"] == (
        "customer.Customer@1"
    )


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


def test_verify_rejects_duplicate_lock_keys(tmp_path: Path) -> None:
    result = resolve_workspace_snapshot(load_workspace(FIXTURE), tmp_path / ".modelable")
    lock_path = result.lock_path
    text = lock_path.read_text(encoding="utf-8").rstrip()
    lock_path.write_text(text[:-1] + ', "format": "modelable.registry.lock.v1"}\n', encoding="utf-8")

    errors = verify_snapshot(lock_path.parent)

    assert any("Duplicate JSON key 'format'" in error for error in errors)


def test_verify_rejects_non_finite_lock_values(tmp_path: Path) -> None:
    output_dir = tmp_path / ".modelable"
    (output_dir / "registry" / "objects").mkdir(parents=True)
    (output_dir / "registry.lock").write_text(
        '{"format":"modelable.registry.lock.v1","objects":[],"requirements":[NaN]}\n', encoding="utf-8"
    )

    errors = verify_snapshot(output_dir)

    assert any("Non-finite JSON number 'NaN'" in error for error in errors)


def test_verify_rejects_non_object_registry_object_without_crashing(tmp_path: Path) -> None:
    result = resolve_workspace_snapshot(load_workspace(FIXTURE), tmp_path / ".modelable")
    object_path = next((result.lock_path.parent / "registry" / "objects").glob("*.json"))
    object_path.write_text("[]\n", encoding="utf-8")

    errors = verify_snapshot(result.lock_path.parent)

    assert any("registry object payload must be a JSON object" in error for error in errors)


def test_verify_rejects_non_canonical_lock_serialization(tmp_path: Path) -> None:
    result = resolve_workspace_snapshot(load_workspace(FIXTURE), tmp_path / ".modelable")
    lock = json.loads(result.lock_path.read_text(encoding="utf-8"))
    result.lock_path.write_text(json.dumps(lock, separators=(",", ":")) + "\n", encoding="utf-8")

    errors = verify_snapshot(result.lock_path.parent)

    assert any("registry lock is not deterministically serialized" in error for error in errors)


def test_verify_detects_source_drift(tmp_path: Path) -> None:
    source = tmp_path / "customer.mdl"
    source.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    output_dir = tmp_path / ".modelable"
    resolve_workspace_snapshot(load_workspace(source), output_dir)

    source.write_text(source.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    errors = verify_snapshot(output_dir)

    assert any("source drift" in error for error in errors)


def test_update_rejects_changed_content_for_existing_identity(tmp_path: Path) -> None:
    source = tmp_path / "customer.mdl"
    source.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    output_dir = tmp_path / ".modelable"
    first = resolve_workspace_snapshot(load_workspace(source), output_dir)
    original_lock = first.lock_path.read_bytes()

    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "status?: enum(active, blocked, deleted)", "status?: enum(active, blocked, deleted, pending)", 1
        ),
        encoding="utf-8",
    )
    changed_workspace = load_workspace(source)

    with pytest.raises(ValueError, match=r"cannot replace existing registry identity .*different canonical content"):
        resolve_workspace_snapshot(changed_workspace, output_dir)

    with pytest.raises(ValueError, match=r"cannot replace existing registry identity .*different canonical content"):
        update_workspace_snapshot(changed_workspace, output_dir)

    assert first.lock_path.read_bytes() == original_lock


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


def test_registry_cli_resolve_git_preserves_git_provenance(tmp_path: Path) -> None:
    repository = tmp_path / "contracts"
    repository.mkdir()
    _git(repository, "init", "--quiet")
    _git(repository, "config", "user.email", "modelable-tests@example.invalid")
    _git(repository, "config", "user.name", "Modelable Tests")
    (repository / "customer.mdl").write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    _git(repository, "add", "customer.mdl")
    _git(repository, "commit", "--quiet", "-m", "initial contracts")
    output_dir = tmp_path / ".modelable"

    result = CliRunner().invoke(
        cli, ["registry", "resolve-git", str(repository), "--ref", "HEAD", "--out", str(output_dir)]
    )

    assert result.exit_code == 0, result.output
    object_path = next((output_dir / "registry" / "objects").glob("*.json"))
    provenance = json.loads(object_path.read_text(encoding="utf-8"))["provenance"]
    assert provenance["source"].startswith("git+file://")
    assert provenance["source_hash"] is None


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


def test_registry_diff_uses_explicit_local_source_adapter(tmp_path: Path, monkeypatch) -> None:
    calls: list[Path] = []
    original_load = LocalSourceAdapter.load

    def recording_load(adapter: LocalSourceAdapter, source: Path):
        calls.append(source)
        return original_load(adapter, source)

    monkeypatch.setattr(LocalSourceAdapter, "load", recording_load)
    output_dir = tmp_path / ".modelable"
    resolve_workspace_snapshot(load_workspace(FIXTURE), output_dir)

    result = CliRunner().invoke(cli, ["registry", "diff", str(FIXTURE), "--out", str(output_dir)])

    assert result.exit_code == 0, result.output
    assert calls == [FIXTURE]


def test_registry_update_uses_explicit_local_source_adapter(tmp_path: Path, monkeypatch) -> None:
    calls: list[Path] = []
    original_load = LocalSourceAdapter.load

    def recording_load(adapter: LocalSourceAdapter, source: Path):
        calls.append(source)
        return original_load(adapter, source)

    monkeypatch.setattr(LocalSourceAdapter, "load", recording_load)
    output_dir = tmp_path / ".modelable"
    resolve_workspace_snapshot(load_workspace(FIXTURE), output_dir)

    result = CliRunner().invoke(cli, ["registry", "update", str(FIXTURE), "--out", str(output_dir)])

    assert result.exit_code == 0, result.output
    assert calls == [FIXTURE]


def test_registry_update_dry_run_reports_candidate_without_replacing_lock(tmp_path: Path) -> None:
    output_dir = tmp_path / ".modelable"
    resolve_workspace_snapshot(load_workspace(FIXTURE), output_dir)
    source = tmp_path / "customer.mdl"
    source.write_text(
        FIXTURE.read_text(encoding="utf-8").rsplit("}", 1)[0]
        + """
  entity Customer @ 3 (additive) {
    @key
    customerId: uuid
    legalName: string
    @pii
    email?: string
    status?: enum(active, blocked, deleted)
    createdAt: timestamp
    region?: string
  }
}
""",
        encoding="utf-8",
    )
    original_lock = (output_dir / "registry.lock").read_bytes()
    objects_dir = output_dir / "registry" / "objects"
    original_objects = {path.name: path.read_bytes() for path in objects_dir.glob("*.json")}

    result = CliRunner().invoke(
        cli,
        ["registry", "update", str(source), "--out", str(output_dir), "--format", "json", "--dry-run"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output[result.output.index("{") :])
    assert payload["added"] == ["customer.Customer@3 (model)"]
    assert payload["changed"] == ["customer.Customer@1 (model)", "customer.Customer@2 (model)"]
    assert payload["dry_run"] is True
    assert payload["empty"] is False
    assert payload["lock"] == str(output_dir / "registry.lock")
    assert payload["objects"] == 3
    assert payload["removed"] == []
    assert payload["dependencies"] == {"added": [], "changed": [], "removed": []}
    assert payload["policy"] == {"blocked_actions": [], "violations": []}
    assert [item["ref"] for item in payload["usage"]["references"]["added"]] == ["customer.Customer@3"]
    assert payload["usage"]["references"]["removed"] == []
    assert payload["usage"]["references"]["changed"] == []
    assert payload["usage"]["artifacts"] == {"added": [], "changed": [], "removed": []}
    assert (output_dir / "registry.lock").read_bytes() == original_lock
    assert {path.name: path.read_bytes() for path in objects_dir.glob("*.json")} == original_objects


def test_registry_update_dry_run_reports_dependency_and_usage_changes(tmp_path: Path) -> None:
    output_dir = tmp_path / ".modelable"
    source = tmp_path / "models.mdl"
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
  projection BillingCustomer @ 1 from customer.Customer @ >=1 <2 as c {
    id <- c.id
  }
}
""".strip(),
        encoding="utf-8",
    )
    resolve_workspace_snapshot(load_workspace(source), output_dir)
    source.write_text(
        source.read_text(encoding="utf-8")
        .replace("customer.Customer @ >=1 <2", "customer.Customer @ >=1 <3")
        .replace(
            "  }\n}\n",
            "  }\n  entity Customer @ 2 (additive) {\n    @key id: uuid\n    name?: string\n  }\n}\n",
            1,
        ),
        encoding="utf-8",
    )

    snapshot_diff = diff_workspace_snapshot(load_workspace(source), output_dir)

    dependency_changes = snapshot_diff.dependencies["changed"]
    assert len(dependency_changes) == 1
    assert dependency_changes[0]["from"] == "billing.BillingCustomer@1"
    assert dependency_changes[0]["current"]["requested"] == "customer.Customer@>=1<2"
    assert dependency_changes[0]["current"]["resolved"] == "customer.Customer@1"
    assert dependency_changes[0]["candidate"]["requested"] == "customer.Customer@>=1<3"
    assert dependency_changes[0]["candidate"]["resolved"] == "customer.Customer@2"
    assert snapshot_diff.usage["references"]["added"][0]["ref"] == "customer.Customer@2"
    assert snapshot_diff.usage["references"]["added"][0]["fields"] == [
        "customer.Customer@2#id",
        "customer.Customer@2#name",
    ]


def test_registry_resolve_includes_artifact_manifest_evidence(tmp_path: Path) -> None:
    manifest = tmp_path / "artifact-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "target": {"name": "python"},
                "artifacts": [{"path": "customer.py", "ref": "customer.Customer@1", "sha256": "a" * 64}],
            }
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / ".modelable"

    result = CliRunner().invoke(
        cli,
        [
            "registry",
            "resolve",
            str(FIXTURE),
            "--out",
            str(output_dir),
            "--artifact-manifest",
            str(manifest),
        ],
    )

    assert result.exit_code == 0, result.output
    lock = json.loads((output_dir / "registry.lock").read_text(encoding="utf-8"))
    assert lock["usage"]["artifacts"] == [
        {"path": "customer.py", "ref": "customer.Customer@1", "sha256": "a" * 64, "target": "python"}
    ]


def test_registry_diff_reports_changed_usage_surfaces(tmp_path: Path) -> None:
    source = tmp_path / "models.mdl"
    source.write_text(
        """
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    @key id: uuid
  }
  projection CustomerReply @ 1 from customer.Customer @ 1 as c {
    id <- c.id
  }
  auto projections Customer @ 1 {
    event on [created]
  }
  api Customer @ 1 {
    operation "getCustomer" {
      method: GET
      path: "/customers"
      responses {
        200: CustomerReply @ 1
      }
    }
  }
}
binding customerStore {
  adapter: postgres
  model: customer.Customer @ 1
  table: "customers"
}
""".strip(),
        encoding="utf-8",
    )
    output_dir = tmp_path / ".modelable"
    resolve_workspace_snapshot(load_workspace(source), output_dir)
    source.write_text(
        source.read_text(encoding="utf-8")
        .replace('path: "/customers"', 'path: "/v2/customers"')
        .replace('table: "customers"', 'table: "customer_records"'),
        encoding="utf-8",
    )

    snapshot_diff = diff_workspace_snapshot(load_workspace(source), output_dir)

    changed = snapshot_diff.usage["surfaces"]["changed"]
    assert [item["key"] for item in changed] == [["api_operation:customer.Customer@1:getCustomer"]]
    assert changed[0]["current"]["path"] == "/customers"
    assert changed[0]["candidate"]["path"] == "/v2/customers"
    assert snapshot_diff.usage["surfaces"]["removed"] == [
        {
            "adapter": "postgres",
            "id": "storage:postgres:customers",
            "kind": "storage",
            "ref": "customer.Customer@1",
            "table": "customers",
        }
    ]
    assert snapshot_diff.usage["surfaces"]["added"] == [
        {
            "adapter": "postgres",
            "id": "storage:postgres:customer_records",
            "kind": "storage",
            "ref": "customer.Customer@1",
            "table": "customer_records",
        }
    ]
    assert snapshot_diff.usage["required_actions"] == [
        {
            "action": "consumer_update",
            "reason": "API operation surface changed",
            "status": "required",
            "subject": "api_operation:customer.Customer@1:getCustomer",
        },
        {
            "action": "storage_migration",
            "reason": "persistence surface changed",
            "status": "required",
            "subject": "customer.Customer@1",
        },
    ]
    assert snapshot_diff.usage["consequences"] == [
        {
            "action": "consumer_update",
            "causal_path": [
                "customer.Customer@1",
                "api_operation:customer.Customer@1:getCustomer",
            ],
            "reason": "API operation surface changed",
            "status": "required",
            "subject": "api_operation:customer.Customer@1:getCustomer",
        },
        {
            "action": "storage_migration",
            "causal_path": [
                "customer.Customer@1",
                "storage:postgres:customer_records",
            ],
            "reason": "persistence surface changed",
            "status": "required",
            "subject": "customer.Customer@1",
        },
    ]


def test_registry_diff_reports_recompile_for_changed_contract(tmp_path: Path) -> None:
    source = tmp_path / "models.mdl"
    source.write_text(
        """
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    @key
    id: uuid
    name: string
  }
}
""".strip(),
        encoding="utf-8",
    )
    output_dir = tmp_path / ".modelable"
    resolve_workspace_snapshot(load_workspace(source), output_dir)
    source.write_text(
        source.read_text(encoding="utf-8").replace("name: string", "name: uuid", 1),
        encoding="utf-8",
    )

    snapshot_diff = diff_workspace_snapshot(load_workspace(source), output_dir)

    assert {
        "action": "recompile",
        "causal_path": ["customer.Customer@1"],
        "reason": "contract content changed",
        "status": "required",
        "subject": "customer.Customer@1",
    } in snapshot_diff.usage["consequences"]
    assert evaluate_registry_policy(snapshot_diff, ("recompile",)) == ["recompile"]


def test_registry_diff_reports_breaking_consequence_for_added_incompatible_model(tmp_path: Path) -> None:
    source = tmp_path / "models.mdl"
    source.write_text(
        """
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    @key
    id: uuid
    name: string
  }
}
""".strip(),
        encoding="utf-8",
    )
    output_dir = tmp_path / ".modelable"
    resolve_workspace_snapshot(load_workspace(source), output_dir)
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "  entity Customer @ 1 (additive) {\n    @key\n    id: uuid\n    name: string\n  }",
            "  entity Customer @ 1 (additive) {\n    @key\n    id: uuid\n    name: string\n  }\n  entity Customer @ 2 (breaking) {\n    @key\n    id: uuid\n  }",
        ),
        encoding="utf-8",
    )

    snapshot_diff = diff_workspace_snapshot(load_workspace(source), output_dir)

    assert {
        "action": "breaking",
        "causal_path": ["customer.Customer@1", "customer.Customer@2"],
        "reason": "direct contract change",
        "status": "breaking",
        "subject": "customer.Customer@2",
    } in snapshot_diff.usage["consequences"]


def test_registry_diff_reports_breaking_consequence_for_added_incompatible_projection(tmp_path: Path) -> None:
    source = tmp_path / "models.mdl"
    source.write_text(
        """
domain orders {
  owner: "orders-team"
  entity Order @ 1 (additive) {
    @key
    orderId: uuid
    status: string
  }
  projection OrderView @ 1 from orders.Order @ 1 as o {
    orderId <- o.orderId
    status <- o.status
  }
}
""".strip(),
        encoding="utf-8",
    )
    output_dir = tmp_path / ".modelable"
    resolve_workspace_snapshot(load_workspace(source), output_dir)
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "  projection OrderView @ 1 from orders.Order @ 1 as o {\n    orderId <- o.orderId\n    status <- o.status\n  }",
            "  projection OrderView @ 1 from orders.Order @ 1 as o {\n    orderId <- o.orderId\n    status <- o.status\n  }\n  projection OrderView @ 2 from orders.Order @ 1 as o {\n    orderId <- o.orderId\n  }",
        ),
        encoding="utf-8",
    )

    snapshot_diff = diff_workspace_snapshot(load_workspace(source), output_dir)

    assert {
        "action": "breaking",
        "causal_path": ["orders.OrderView@1", "orders.OrderView@2"],
        "reason": "direct projection change",
        "status": "breaking",
        "subject": "orders.OrderView@2",
    } in snapshot_diff.usage["consequences"]


def test_registry_diff_reports_storage_migration_for_added_model_index(tmp_path: Path) -> None:
    source = tmp_path / "models.mdl"
    source.write_text(
        """
domain billing {
  owner: "billing-team"
  entity Order @ 1 (additive) {
    @key
    orderId: uuid
    customerId: uuid
  }
}
""".strip(),
        encoding="utf-8",
    )
    output_dir = tmp_path / ".modelable"
    resolve_workspace_snapshot(load_workspace(source), output_dir)
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "  entity Order @ 1 (additive) {\n    @key\n    orderId: uuid\n    customerId: uuid\n  }",
            "  entity Order @ 1 (additive) {\n    @key\n    orderId: uuid\n    customerId: uuid\n  }\n  entity Order @ 2 (additive) {\n    @key\n    orderId: uuid\n    customerId: uuid\n  }\n  index Order @ 2 {\n    primary orderId\n    secondary by_customer {\n      key: [customerId]\n    }\n  }",
        ),
        encoding="utf-8",
    )

    snapshot_diff = diff_workspace_snapshot(load_workspace(source), output_dir)

    assert {
        "action": "storage_migration",
        "causal_path": [
            "billing.Order@1",
            "billing.Order@2",
            "sql:billing.Order:index_changed",
        ],
        "reason": "index 'by_customer' changed and requires a storage migration",
        "status": "migration_required",
        "subject": "sql:billing.Order:index_changed",
    } in snapshot_diff.usage["consequences"]


def test_registry_diff_reports_projection_rebuild_for_added_projection_expression(tmp_path: Path) -> None:
    source = tmp_path / "models.mdl"
    source.write_text(
        """
domain orders {
  owner: "orders-team"
  entity Order @ 1 (additive) {
    @key
    orderId: uuid
    status: string
  }
  projection OrderView @ 1 from orders.Order @ 1 as o {
    orderId <- o.orderId
    isShipped = o.status == "shipped"
  }
}
""".strip(),
        encoding="utf-8",
    )
    output_dir = tmp_path / ".modelable"
    resolve_workspace_snapshot(load_workspace(source), output_dir)
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            '  projection OrderView @ 1 from orders.Order @ 1 as o {\n    orderId <- o.orderId\n    isShipped = o.status == "shipped"\n  }',
            '  projection OrderView @ 1 from orders.Order @ 1 as o {\n    orderId <- o.orderId\n    isShipped = o.status == "shipped"\n  }\n  projection OrderView @ 2 from orders.Order @ 1 as o {\n    orderId <- o.orderId\n    isShipped = o.status == "delivered"\n  }',
        ),
        encoding="utf-8",
    )

    snapshot_diff = diff_workspace_snapshot(load_workspace(source), output_dir)

    rebuild_consequences = [
        consequence
        for consequence in snapshot_diff.usage["consequences"]
        if consequence["action"] == "projection_rebuild"
    ]
    assert rebuild_consequences == [
        {
            "action": "projection_rebuild",
            "causal_path": [
                "orders.OrderView@1",
                "orders.OrderView@2",
                "projection-rebuild:orders.OrderView:expression_changed",
            ],
            "reason": "field 'isShipped' computed expression changed",
            "status": "migration_required",
            "subject": "projection-rebuild:orders.OrderView:expression_changed",
        }
    ]


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


def test_update_stages_new_version_and_preserves_old_lock_on_diff(tmp_path: Path) -> None:
    workspace = load_workspace(FIXTURE)
    output_dir = tmp_path / ".modelable"
    resolve_workspace_snapshot(workspace, output_dir)
    source = tmp_path / "customer.mdl"
    source.write_text(
        FIXTURE.read_text(encoding="utf-8").rsplit("}", 1)[0]
        + """
  entity Customer @ 3 (additive) {
    @key
    customerId: uuid
    legalName: string
    @pii
    email?: string
    status?: enum(active, blocked, deleted)
    createdAt: timestamp
    region?: string
  }
}
""",
        encoding="utf-8",
    )
    changed_workspace = load_workspace(source)
    assert not changed_workspace.errors, changed_workspace.errors

    snapshot_diff = diff_workspace_snapshot(changed_workspace, output_dir)
    original_lock = (output_dir / "registry.lock").read_bytes()

    assert snapshot_diff.added == ("customer.Customer@3 (model)",)
    assert (output_dir / "registry.lock").read_bytes() == original_lock

    _, applied_diff = update_workspace_snapshot(changed_workspace, output_dir)

    assert applied_diff.added == snapshot_diff.added
    assert verify_snapshot(output_dir) == []


def test_update_rolls_back_new_objects_when_lock_replacement_fails(tmp_path: Path, monkeypatch) -> None:
    output_dir = tmp_path / ".modelable"
    source = tmp_path / "customer.mdl"
    source.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    resolve_workspace_snapshot(load_workspace(source), output_dir)
    source.write_text(
        FIXTURE.read_text(encoding="utf-8").rsplit("}", 1)[0]
        + """
  entity Customer @ 3 (additive) {
    @key
    customerId: uuid
    legalName: string
    @pii
    email?: string
    status?: enum(active, blocked, deleted)
    createdAt: timestamp
    region?: string
  }
}
""",
        encoding="utf-8",
    )
    lock_path = output_dir / "registry.lock"
    objects_dir = output_dir / "registry" / "objects"
    original_lock = lock_path.read_bytes()
    original_objects = {path.name: path.read_bytes() for path in objects_dir.glob("*.json")}
    original_replace = snapshot_module.os.replace

    def fail_replace(source_path: Path, destination: Path) -> None:
        if destination == lock_path:
            raise OSError(f"injected replacement failure for {destination}")
        original_replace(source_path, destination)

    monkeypatch.setattr(snapshot_module.os, "replace", fail_replace)

    with pytest.raises(OSError, match="injected replacement failure"):
        update_workspace_snapshot(load_workspace(source), output_dir)

    assert lock_path.read_bytes() == original_lock
    assert {path.name: path.read_bytes() for path in objects_dir.glob("*.json")} == original_objects
    assert not list(output_dir.glob(".registry.lock.tmp-*"))


def test_update_policy_retains_blocked_candidate(tmp_path: Path) -> None:
    source = tmp_path / "models.mdl"
    source.write_text(
        FIXTURE.read_text(encoding="utf-8")
        + """
binding customerStore {
  adapter: postgres
  model: customer.Customer @ 1
  table: "customers"
}
""",
        encoding="utf-8",
    )
    (tmp_path / "modelable.toml").write_text('[registry]\nblocked_actions = ["storage_migration"]\n', encoding="utf-8")
    output_dir = tmp_path / ".modelable"
    resolve_workspace_snapshot(load_workspace(source), output_dir)
    original_lock = (output_dir / "registry.lock").read_bytes()
    source.write_text(
        source.read_text(encoding="utf-8").replace('table: "customers"', 'table: "customer_records"'), encoding="utf-8"
    )

    result = CliRunner().invoke(cli, ["registry", "update", str(source), "--out", str(output_dir)])

    assert result.exit_code == 1
    assert "blocked by registry policy" in result.output

    assert (output_dir / "registry.lock").read_bytes() == original_lock
    candidates = list((output_dir / "registry" / "candidates").iterdir())
    assert len(candidates) == 1
    assert (candidates[0] / "registry.lock").exists()
    assert verify_snapshot(candidates[0]) == []


def test_update_policy_blocks_changed_generated_artifact(tmp_path: Path) -> None:
    source = tmp_path / "models.mdl"
    source.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    output_dir = tmp_path / ".modelable"
    old_manifest = {
        "target": {"name": "python"},
        "artifacts": [{"path": "customer.py", "ref": "customer.Customer@1", "sha256": "a" * 64}],
    }
    new_manifest = {
        "target": {"name": "python"},
        "artifacts": [{"path": "customer.py", "ref": "customer.Customer@1", "sha256": "b" * 64}],
    }
    resolve_workspace_snapshot(load_workspace(source), output_dir, artifact_manifests=(old_manifest,))
    original_lock = (output_dir / "registry.lock").read_bytes()
    diff = diff_workspace_snapshot(load_workspace(source), output_dir, artifact_manifests=(new_manifest,))

    assert diff.usage["consequences"] == [
        {
            "action": "regenerate",
            "causal_path": ["customer.Customer@1", "generated_artifact:python/customer.py"],
            "reason": "generated artifact changed",
            "status": "required",
            "subject": "generated_artifact:python/customer.py",
        }
    ]

    with pytest.raises(ValueError, match="regenerate"):
        update_workspace_snapshot(
            load_workspace(source),
            output_dir,
            artifact_manifests=(new_manifest,),
            blocked_actions=("regenerate",),
        )

    assert (output_dir / "registry.lock").read_bytes() == original_lock
    candidates = list((output_dir / "registry" / "candidates").iterdir())
    assert len(candidates) == 1
    assert json.loads((candidates[0] / "registry.lock").read_text(encoding="utf-8"))["usage"]["artifacts"] == [
        {"path": "customer.py", "ref": "customer.Customer@1", "sha256": "b" * 64, "target": "python"}
    ]
    assert verify_snapshot(candidates[0]) == []


def test_update_preserves_extension_pins(tmp_path: Path) -> None:
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
    output_dir = tmp_path / ".modelable"
    resolve_workspace_snapshot(load_workspace(FIXTURE), output_dir, extension_pins=(pin,))

    update_workspace_snapshot(load_workspace(FIXTURE), output_dir)

    lock = json.loads((output_dir / "registry.lock").read_text(encoding="utf-8"))
    assert lock["extensions"] == [pin.as_dict()]
