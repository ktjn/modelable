from __future__ import annotations

import json
import os
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from click.testing import CliRunner
from test_descriptor_artifacts import _write_python_fake_protoc

from modelable.cli import cli
from modelable.compat.targets import compare_grpc_artifacts, compare_protobuf_manifests
from modelable.compiler.workspace import load_workspace
from modelable.emitters.grpc import emit_grpc
from modelable.emitters.protobuf import emit_protobuf


@dataclass(frozen=True)
class ScalableRegistration:
    """The generated contract information a Scalable consumer registers."""

    ref: str
    schema_id: str
    modelable_signature: str
    schema_fingerprint: str
    services: tuple[str, ...]
    entity_types: tuple[str, ...]
    read_indexes: tuple[dict[str, object], ...]
    descriptor_path: str


def _register_scalable_contract(output: Path, ref: str) -> ScalableRegistration:
    domain, name_version = ref.split(".", 1)
    name, version = name_version.rsplit("@", 1)
    base = output / domain / f"{name}.v{version}"
    schema_manifest = json.loads((base / "schema-manifest.json").read_text(encoding="utf-8"))["schemas"][0]
    service_manifest = json.loads((base / "service-manifest.json").read_text(encoding="utf-8"))

    assert schema_manifest["ref"] == ref
    assert service_manifest["ref"] == ref
    assert service_manifest["schema_manifest"] == "schema-manifest.json"
    assert service_manifest["service_proto"] == f"{name}.v{version}.grpc.proto"
    assert service_manifest["entity_types"] == [ref]
    assert service_manifest["services"] == ["CommandService", "EntityReadService"]
    assert schema_manifest["indexes"]["primary"]["index_name"] == "primary"
    assert service_manifest["read_indexes"]

    descriptor = service_manifest["descriptor"]
    descriptor_file = base / str(descriptor["path"])
    assert descriptor_file.exists()
    assert descriptor["content_hash"] == sha256(descriptor_file.read_bytes()).hexdigest()

    return ScalableRegistration(
        ref=ref,
        schema_id=str(schema_manifest["schema_id"]),
        modelable_signature=str(schema_manifest["modelable_signature"]),
        schema_fingerprint=str(schema_manifest["schema_fingerprint"]),
        services=tuple(str(service) for service in service_manifest["services"]),
        entity_types=tuple(str(entity) for entity in service_manifest["entity_types"]),
        read_indexes=tuple(service_manifest["read_indexes"]),
        descriptor_path=str(descriptor["path"]),
    )


def _fake_protoc_source() -> str:
    return (
        "from pathlib import Path\n"
        "import sys\n"
        "out = next(arg.split('=', 1)[1] for arg in sys.argv[1:] if arg.startswith('--descriptor_set_out='))\n"
        "Path(out).write_bytes(b'scalable-registration-descriptor')\n"
    )


def test_scalable_consumer_registers_generated_contract_bundle(tmp_path: Path, monkeypatch) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_python_fake_protoc(bin_dir, source=_fake_protoc_source())
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))

    source = Path(__file__).parent / "fixtures" / "scalable_registration" / "workspace.mdl"
    output = tmp_path / "dist"
    result = CliRunner().invoke(
        cli, ["compile", str(source), "--target", "grpc", "--out", str(output), "--descriptor-set"]
    )

    assert result.exit_code == 0, result.output
    registration = _register_scalable_contract(output, "marketplace.Order@1")

    assert registration.schema_id == "modelable://marketplace/Order/v1/protobuf"
    assert len(registration.modelable_signature) == 64
    assert len(registration.schema_fingerprint) == 64
    assert registration.services == ("CommandService", "EntityReadService")
    assert registration.entity_types == ("marketplace.Order@1",)
    assert [index["index_name"] for index in registration.read_indexes] == ["primary", "by_customer"]
    assert registration.descriptor_path == "Order.v1.grpc.descriptor.pb"


def test_scalable_registration_compatibility_accepts_additive_field_and_rejects_index_change(tmp_path: Path) -> None:
    old_source = tmp_path / "old"
    old_source.mkdir()
    (old_source / "workspace.mdl").write_text(
        """
domain marketplace {
  owner: "marketplace-team"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    customerId: uuid
    createdAt: timestamp
  }
  index Order @ 1 {
    primary orderId
    secondary by_customer { key: [customerId] }
  }
}
""",
        encoding="utf-8",
    )
    new_source = tmp_path / "new"
    new_source.mkdir()
    (new_source / "workspace.mdl").write_text(
        """
domain marketplace {
  owner: "marketplace-team"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    customerId: uuid
    createdAt: timestamp
    displayName?: string
  }
  index Order @ 1 {
    primary orderId
    secondary by_customer {
      key: [customerId]
      sort: [createdAt desc]
    }
  }
}
""",
        encoding="utf-8",
    )

    old_workspace = load_workspace(old_source)
    new_workspace = load_workspace(new_source)
    old_protobuf = emit_protobuf(old_workspace, tmp_path / "old-protobuf")
    new_protobuf = emit_protobuf(new_workspace, tmp_path / "new-protobuf")
    old_grpc = emit_grpc(old_workspace, tmp_path / "old-grpc")
    new_grpc = emit_grpc(new_workspace, tmp_path / "new-grpc")

    assert compare_protobuf_manifests(old_protobuf, new_protobuf).status == "wire_compatible"
    grpc_report = compare_grpc_artifacts(old_grpc, new_grpc)
    assert grpc_report.status == "requires_read_rebuild"
    assert [finding.code for finding in grpc_report.findings] == ["read_index_changed"]


def test_scalable_registration_rejects_wire_incompatible_field_change(tmp_path: Path) -> None:
    old_source = tmp_path / "old.mdl"
    old_source.write_text(
        """
domain marketplace {
  owner: "marketplace-team"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    customerId: int
  }
}
""",
        encoding="utf-8",
    )
    new_source = tmp_path / "new.mdl"
    new_source.write_text(
        """
domain marketplace {
  owner: "marketplace-team"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    customerId: string
  }
}
""",
        encoding="utf-8",
    )

    report = compare_protobuf_manifests(
        emit_protobuf(load_workspace(old_source), tmp_path / "old-output"),
        emit_protobuf(load_workspace(new_source), tmp_path / "new-output"),
    )

    assert report.status == "breaking"
    assert any(finding.code == "field_type_changed" for finding in report.findings)
