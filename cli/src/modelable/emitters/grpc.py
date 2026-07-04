from __future__ import annotations

import json
import re
from pathlib import Path

from modelable.compiler.workspace import Workspace
from modelable.emitters.base import EmittedArtifact, compute_content_hash
from modelable.emitters.protobuf import emit_protobuf


def emit_grpc(workspace: Workspace, out_dir: Path) -> list[EmittedArtifact]:
    """Emit the Scalable gRPC profile beside generated protobuf payload schemas."""
    artifacts: list[EmittedArtifact] = []
    protobuf_artifacts = emit_protobuf(workspace, out_dir)
    artifacts.extend(_retarget_payload_artifacts(protobuf_artifacts))

    for manifest_artifact in protobuf_artifacts:
        if manifest_artifact.path.name != "schema-manifest.json":
            continue
        assert isinstance(manifest_artifact.content, str)
        schema_manifest = json.loads(manifest_artifact.content)
        schema = schema_manifest["schemas"][0]
        ref = str(schema["ref"])
        domain, name, version = _split_ref(ref)
        artifact_id = f"{domain}.{name}.v{version}.grpc"
        base_path = out_dir / domain / f"{name}.v{version}"
        service_proto = _render_service_proto(package=f"{_package_name(domain, version)}.scalable")
        service_manifest = _service_manifest_json(
            ref=ref,
            service_proto=f"{name}.v{version}.grpc.proto",
            fields=schema.get("fields", []),
        )
        artifacts.append(
            EmittedArtifact(
                target="grpc",
                ref=ref,
                artifact_id=artifact_id,
                path=base_path / f"{name}.v{version}.grpc.proto",
                content=service_proto,
                content_hash=compute_content_hash(service_proto),
            )
        )
        artifacts.append(
            EmittedArtifact(
                target="grpc",
                ref=ref,
                artifact_id=artifact_id,
                path=base_path / "service-manifest.json",
                content=service_manifest,
                content_hash=compute_content_hash(service_manifest),
            )
        )

    return artifacts


def _retarget_payload_artifacts(artifacts: list[EmittedArtifact]) -> list[EmittedArtifact]:
    return [
        EmittedArtifact(
            target="grpc",
            ref=artifact.ref,
            artifact_id=artifact.artifact_id,
            path=artifact.path,
            content=artifact.content,
            content_hash=artifact.content_hash,
            warnings=artifact.warnings,
        )
        for artifact in artifacts
    ]


def _render_service_proto(*, package: str) -> str:
    return f"""syntax = "proto3";

package {package};

import "google/protobuf/timestamp.proto";

message SchemaIdentity {{
  string model_id = 1;
  string model_name = 2;
  int64 model_version = 3;
  string schema_id = 4;
  string schema_fingerprint = 5;
  string source_ref = 6;
  string generated_at = 7;
  string target = 8;
}}

message CommandEnvelope {{
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
}}

message CommandResultEnvelope {{
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
}}

message GetEntityRequest {{
  string entity_type = 1;
  string entity_id = 2;
  ReadConsistency consistency = 3;
}}

message ListEntitiesRequest {{
  string entity_type = 1;
  int32 limit = 2;
  string page_token = 3;
  ReadConsistency consistency = 4;
}}

message ListByIndexRequest {{
  string entity_type = 1;
  string index_name = 2;
  repeated string key_values = 3;
  int32 limit = 4;
  string page_token = 5;
  ReadConsistency consistency = 6;
}}

message ReadResultEnvelope {{
  string entity_type = 1;
  bytes payload = 2;
  string payload_codec = 3;
  string payload_schema_id = 4;
  int64 source_commit_position = 5;
  string freshness_status = 6;
}}

message ListResultEnvelope {{
  repeated ReadResultEnvelope items = 1;
  string next_page_token = 2;
  int64 source_commit_position = 3;
  string freshness_status = 4;
}}

message IndexMetadata {{
  string index_name = 1;
  int64 index_version = 2;
  repeated string key_fields = 3;
  repeated string sort_fields = 4;
  bool unique = 5;
}}

enum ReadConsistency {{
  READ_CONSISTENCY_UNSPECIFIED = 0;
  READ_CONSISTENCY_EVENTUAL = 1;
  READ_CONSISTENCY_STRONG = 2;
}}

service CommandService {{
  rpc SubmitCommand(CommandEnvelope) returns (CommandResultEnvelope);
  rpc CommandStream(stream CommandEnvelope) returns (stream CommandResultEnvelope);
}}

service EntityReadService {{
  rpc GetEntity(GetEntityRequest) returns (ReadResultEnvelope);
  rpc ListEntities(ListEntitiesRequest) returns (ListResultEnvelope);
  rpc ListByIndex(ListByIndexRequest) returns (ListResultEnvelope);
}}
"""


def _service_manifest_json(*, ref: str, service_proto: str, fields: object) -> str:
    key_fields = _key_fields(fields)
    manifest: dict[str, object] = {
        "target": "grpc",
        "ref": ref,
        "schema_manifest": "schema-manifest.json",
        "service_proto": service_proto,
        "services": ["CommandService", "EntityReadService"],
        "entity_types": [ref],
        "read_indexes": [],
    }
    if key_fields:
        manifest["read_indexes"] = [
            {
                "index_name": "primary",
                "index_version": 1,
                "key_fields": key_fields,
                "sort_fields": [],
                "unique": True,
            }
        ]
    return json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"


def _key_fields(fields: object) -> list[str]:
    if not isinstance(fields, list):
        return []
    keys: list[str] = []
    for field in fields:
        if isinstance(field, dict) and field.get("key") is True:
            name = field.get("name")
            if isinstance(name, str):
                keys.append(name)
    return keys


def _split_ref(ref: str) -> tuple[str, str, int]:
    domain_name, version_text = ref.split("@", 1)
    domain, name = domain_name.rsplit(".", 1)
    return domain, name, int(version_text)


def _package_name(domain: str, version: int) -> str:
    normalized = re.sub(r"[^0-9A-Za-z_]+", "_", domain).strip("_").lower()
    return f"modelable.{normalized}.v{version}"
