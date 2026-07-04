from __future__ import annotations

import json

from click.testing import CliRunner

from modelable.cli import cli
from modelable.compiler.workspace import load_workspace
from modelable.emitters.protobuf import emit_protobuf


def test_emit_protobuf_entity_proto_and_manifest(tmp_path):
    (tmp_path / "customer.mdl").write_text(
        """
domain customer {
  owner: "customer-team"

  entity Customer @ 1 (additive) {
    @key customerId: uuid
    email?: string
    status: enum(active, blocked)
    joinedAt?: timestamp
    score: decimal(12, 2)
    tags: array<string>
    avatar?: binary
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)

    artifacts = emit_protobuf(workspace, tmp_path / "out")

    proto = next(art for art in artifacts if art.path.name == "Customer.v1.proto")
    assert proto.target == "protobuf"
    assert proto.ref == "customer.Customer@1"
    assert proto.artifact_id == "customer.Customer.v1"
    assert proto.path == tmp_path / "out" / "customer" / "Customer.v1" / "Customer.v1.proto"
    assert (
        proto.content
        == """syntax = "proto3";

package modelable.customer.v1;

import "google/protobuf/timestamp.proto";

message Customer {
  string customer_id = 1;
  optional string email = 2;
  CustomerStatus status = 3;
  optional google.protobuf.Timestamp joined_at = 4;
  string score = 5;
  repeated string tags = 6;
  optional bytes avatar = 7;
}

enum CustomerStatus {
  CUSTOMER_STATUS_UNSPECIFIED = 0;
  CUSTOMER_STATUS_ACTIVE = 1;
  CUSTOMER_STATUS_BLOCKED = 2;
}
"""
    )

    manifest = next(art for art in artifacts if art.path.name == "schema-manifest.json")
    manifest_doc = json.loads(manifest.content)
    assert manifest_doc["target"] == "protobuf"
    assert manifest_doc["schemas"][0]["ref"] == "customer.Customer@1"
    assert manifest_doc["schemas"][0]["schema_id"] == "modelable://customer/Customer/v1/protobuf"
    assert manifest_doc["schemas"][0]["fields"] == [
        {"name": "customerId", "proto_name": "customer_id", "number": 1, "type": "string", "key": True},
        {"name": "email", "proto_name": "email", "number": 2, "type": "optional string", "key": False},
        {"name": "status", "proto_name": "status", "number": 3, "type": "CustomerStatus", "key": False},
        {
            "name": "joinedAt",
            "proto_name": "joined_at",
            "number": 4,
            "type": "optional google.protobuf.Timestamp",
            "key": False,
        },
        {"name": "score", "proto_name": "score", "number": 5, "type": "string", "key": False},
        {"name": "tags", "proto_name": "tags", "number": 6, "type": "repeated string", "key": False},
        {"name": "avatar", "proto_name": "avatar", "number": 7, "type": "optional bytes", "key": False},
    ]


def test_compile_protobuf_writes_proto_and_manifest(tmp_path):
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
        result = runner.invoke(cli, ["compile", str(mdl), "--target", "protobuf", "--out", str(out)])

    assert result.exit_code == 0, result.output
    assert (out / "customer" / "Customer.v1" / "Customer.v1.proto").exists()
    assert (out / "customer" / "Customer.v1" / "schema-manifest.json").exists()


def test_emit_protobuf_projection_uses_resolved_source_field_types(tmp_path):
    (tmp_path / "customer.mdl").write_text(
        """
domain customer {
  owner: "customer-team"

  entity Customer @ 1 (additive) {
    @key customerId: uuid
    email: string
    joinedAt?: timestamp
  }

  projection CustomerSummary @ 1
    from customer.Customer @ 1 as c
  {
    customerId <- c.customerId
    email <- c.email
    joinedAt <- c.joinedAt
    displayName = c.email
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)

    artifacts = emit_protobuf(workspace, tmp_path / "out")

    proto = next(art for art in artifacts if art.ref == "customer.CustomerSummary@1" and art.path.suffix == ".proto")
    assert proto.path == tmp_path / "out" / "customer" / "CustomerSummary.v1" / "CustomerSummary.v1.proto"
    assert (
        proto.content
        == """syntax = "proto3";

package modelable.customer.v1;

import "google/protobuf/timestamp.proto";

message CustomerSummary {
  string customer_id = 1;
  string email = 2;
  google.protobuf.Timestamp joined_at = 3;
  string display_name = 4;
}
"""
    )
