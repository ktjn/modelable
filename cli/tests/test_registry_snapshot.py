from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

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
    load_snapshot_workspace,
    load_workspace_with_snapshot,
    prune_snapshot,
    resolve_workspace_snapshot,
    update_workspace_snapshot,
    verify_snapshot,
)
from modelable.registry.sources import LocalSourceAdapter
from modelable.registry.usage import build_usage_manifest

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
