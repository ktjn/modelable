from __future__ import annotations

import json

from click.testing import CliRunner

from modelable.cli import cli
from modelable.compiler.workspace import load_workspace
from modelable.emitters.grpc import emit_grpc


def test_emit_grpc_service_profile_and_manifests(tmp_path):
    (tmp_path / "customer.mdl").write_text(
        """
domain customer {
  owner: "customer-team"

  entity Customer @ 1 (additive) {
    @key customerId: uuid
    email?: string
    joinedAt?: timestamp
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)

    artifacts = emit_grpc(workspace, tmp_path / "out")

    payload_proto = next(art for art in artifacts if art.path.name == "Customer.v1.proto")
    assert payload_proto.path == tmp_path / "out" / "customer" / "Customer.v1" / "Customer.v1.proto"

    service_proto = next(art for art in artifacts if art.path.name == "Customer.v1.grpc.proto")
    assert service_proto.target == "grpc"
    assert service_proto.ref == "customer.Customer@1"
    assert service_proto.artifact_id == "customer.Customer.v1.grpc"
    assert service_proto.path == tmp_path / "out" / "customer" / "Customer.v1" / "Customer.v1.grpc.proto"
    assert (
        service_proto.content
        == """syntax = "proto3";

package modelable.customer.v1.scalable;

import "google/protobuf/timestamp.proto";

message SchemaIdentity {
  string model_id = 1;
  string model_name = 2;
  int64 model_version = 3;
  string schema_id = 4;
  string schema_fingerprint = 5;
  string source_ref = 6;
  string generated_at = 7;
  string target = 8;
}

message CommandEnvelope {
  string protocol_version = 1;
  string envelope_version = 2;
  string command_type = 3;
  string command_id = 4;
  string idempotency_key = 5;
  string causation_id = 6;
  string correlation_id = 7;
  optional google.protobuf.Timestamp deadline = 8;
  string target_hint = 9;
  string payload_codec = 10;
  string payload_schema_id = 11;
  bytes payload = 12;
  SchemaIdentity schema_identity = 13;
}

message CommandResultEnvelope {
  string protocol_version = 1;
  string envelope_version = 2;
  string command_id = 3;
  string status = 4;
  string retry_hint = 5;
  int64 committed_log_position = 6;
  int64 applied_log_position = 7;
  bytes payload = 8;
  string payload_codec = 9;
  string payload_schema_id = 10;
}

message GetEntityRequest {
  string entity_type = 1;
  string entity_id = 2;
  ReadConsistency consistency = 3;
}

message ListEntitiesRequest {
  string entity_type = 1;
  int32 limit = 2;
  string page_token = 3;
  ReadConsistency consistency = 4;
}

message ListByIndexRequest {
  string entity_type = 1;
  string index_name = 2;
  repeated string key_values = 3;
  int32 limit = 4;
  string page_token = 5;
  ReadConsistency consistency = 6;
}

message ReadResultEnvelope {
  string entity_type = 1;
  bytes payload = 2;
  string payload_codec = 3;
  string payload_schema_id = 4;
  int64 source_commit_position = 5;
  string freshness_status = 6;
}

message ListResultEnvelope {
  repeated ReadResultEnvelope items = 1;
  string next_page_token = 2;
  int64 source_commit_position = 3;
  string freshness_status = 4;
}

message IndexMetadata {
  string index_name = 1;
  int64 index_version = 2;
  repeated string key_fields = 3;
  repeated string sort_fields = 4;
  bool unique = 5;
}

enum ReadConsistency {
  READ_CONSISTENCY_UNSPECIFIED = 0;
  READ_CONSISTENCY_EVENTUAL = 1;
  READ_CONSISTENCY_STRONG = 2;
}

service CommandService {
  rpc SubmitCommand(CommandEnvelope) returns (CommandResultEnvelope);
  rpc CommandStream(stream CommandEnvelope) returns (stream CommandResultEnvelope);
}

service EntityReadService {
  rpc GetEntity(GetEntityRequest) returns (ReadResultEnvelope);
  rpc ListEntities(ListEntitiesRequest) returns (ListResultEnvelope);
  rpc ListByIndex(ListByIndexRequest) returns (ListResultEnvelope);
}
"""
    )

    service_manifest = next(art for art in artifacts if art.path.name == "service-manifest.json")
    manifest_doc = json.loads(service_manifest.content)
    assert manifest_doc["target"] == "grpc"
    assert manifest_doc["ref"] == "customer.Customer@1"
    assert manifest_doc["schema_manifest"] == "schema-manifest.json"
    assert manifest_doc["service_proto"] == "Customer.v1.grpc.proto"
    assert manifest_doc["services"] == ["CommandService", "EntityReadService"]
    assert manifest_doc["entity_types"] == ["customer.Customer@1"]
    assert manifest_doc["read_indexes"] == [
        {
            "index_name": "primary",
            "index_version": 1,
            "key_fields": ["customerId"],
            "sort_fields": [],
            "unique": True,
        }
    ]


def test_compile_grpc_writes_payload_service_and_manifests(tmp_path):
    mdl = tmp_path / "customer.mdl"
    mdl.write_text(
        """
domain customer {
  owner: "customer-team"

  entity Customer @ 1 (additive) {
    @key customerId: uuid
    email?: string
  }
}
""",
        encoding="utf-8",
    )

    out = tmp_path / "dist"
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli, ["compile", str(mdl), "--target", "grpc", "--out", str(out)])

    assert result.exit_code == 0, result.output
    base = out / "customer" / "Customer.v1"
    assert (base / "Customer.v1.proto").exists()
    assert (base / "Customer.v1.grpc.proto").exists()
    assert (base / "schema-manifest.json").exists()
    assert (base / "service-manifest.json").exists()


def test_compile_grpc_passes_registry_allocations_to_payload_manifest(tmp_path):
    mdl = tmp_path / "platform.mdl"
    mdl.write_text(
        """
domain platform {
  owner: "platform-team"
  semantic SchemaId : u32 { registry: true }
  entity Schema @ 1 (additive) {
    @key schemaId: SchemaId
  }
}
""",
        encoding="utf-8",
    )
    out = tmp_path / "dist"
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            cli,
            ["compile", str(mdl), "--target", "grpc", "--out", str(out)],
        )

    assert result.exit_code == 0, result.output
    schema = json.loads((out / "platform" / "Schema.v1" / "schema-manifest.json").read_text(encoding="utf-8"))[
        "schemas"
    ][0]
    assert schema["semantic_types"][0]["registry_id"] == 1
    assert (out / "platform" / "semantic-types.proto").exists()


def test_emit_grpc_retargets_semantic_payload_artifacts_unchanged(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain platform {
  owner: "platform-team"
  semantic SchemaId : u32 { registry: true }
  entity Schema @ 1 (additive) {
    @key schemaId: SchemaId
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_grpc(
        workspace,
        tmp_path / "out",
        registry_ids={"platform.SchemaId": 5},
    )

    bundle = next(art for art in artifacts if art.path.name == "semantic-types.proto")
    assert bundle.target == "grpc"
    assert "message SchemaId" in bundle.content
    schema_manifest = next(art for art in artifacts if art.path.name == "schema-manifest.json")
    schema = json.loads(schema_manifest.content)["schemas"][0]
    assert schema["semantic_types"][0]["registry_id"] == 5
    assert schema["fields"][0]["semantic_type"] == "platform.SchemaId"


def test_compile_grpc_domain_scope_preserves_semantic_ambiguity(tmp_path):
    mdl = tmp_path / "ambiguous.mdl"
    mdl.write_text(
        """
domain alpha {
  owner: "alpha-team"
  semantic SharedId : u32
}

domain beta {
  owner: "beta-team"
  semantic SharedId : u64
}

domain consumer {
  owner: "consumer-team"
  entity UsesShared @ 1 (additive) {
    @key id: SharedId
  }
}
""",
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli,
        [
            "compile",
            str(mdl),
            "--target",
            "grpc",
            "--out",
            str(tmp_path / "dist"),
            "--registry",
            str(tmp_path / ".modelable" / "registry.db"),
            "--registry-ids",
            str(tmp_path / "registry-ids.lock"),
            "--domain",
            "alpha",
            "--domain",
            "consumer",
        ],
    )

    assert result.exit_code == 1
    assert "ambiguous type 'SharedId'; candidates: alpha.SharedId, beta.SharedId" in result.output
