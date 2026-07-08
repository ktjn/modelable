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


def test_emit_protobuf_fixed_width_integers(tmp_path):
    (tmp_path / "types.mdl").write_text(
        """
domain types {
  owner: "test-team"

  entity Widths @ 1 (additive) {
    @key id: uuid
    a: u8
    b: u16
    c: u32
    d: u64
    e: u128
    f: i8
    g: i16
    h: i32
    i: i64
    j: i128
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)

    artifacts = emit_protobuf(workspace, tmp_path / "out")

    proto = next(art for art in artifacts if art.path.name == "Widths.v1.proto")
    assert "uint32 a = 2;" in proto.content
    assert "uint32 b = 3;" in proto.content
    assert "uint32 c = 4;" in proto.content
    assert "uint64 d = 5;" in proto.content
    assert "bytes e = 6;" in proto.content
    assert "int32 f = 7;" in proto.content
    assert "int32 g = 8;" in proto.content
    assert "int32 h = 9;" in proto.content
    assert "int64 i = 10;" in proto.content
    assert "bytes j = 11;" in proto.content

    manifest = next(art for art in artifacts if art.path.name == "schema-manifest.json")
    fields_by_name = {f["name"]: f for f in json.loads(manifest.content)["schemas"][0]["fields"]}
    assert fields_by_name["a"]["type"] == "uint32"
    assert fields_by_name["d"]["type"] == "uint64"
    assert fields_by_name["e"]["type"] == "bytes"
    assert fields_by_name["e"]["fixed_length"] == 16
    assert fields_by_name["j"]["type"] == "bytes"
    assert fields_by_name["j"]["fixed_length"] == 16
    assert "fixed_length" not in fields_by_name["a"]
    assert "fixed_length" not in fields_by_name["i"]


def test_emit_protobuf_fixed_length_binary(tmp_path):
    (tmp_path / "types.mdl").write_text(
        """
domain types {
  owner: "test-team"

  entity Widths @ 1 (additive) {
    @key id: uuid
    keyHash: binary(32)
    avatar: binary
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)

    artifacts = emit_protobuf(workspace, tmp_path / "out")

    proto = next(art for art in artifacts if art.path.name == "Widths.v1.proto")
    assert "bytes key_hash = 2;" in proto.content
    assert "bytes avatar = 3;" in proto.content

    manifest = next(art for art in artifacts if art.path.name == "schema-manifest.json")
    fields_by_name = {f["name"]: f for f in json.loads(manifest.content)["schemas"][0]["fields"]}
    assert fields_by_name["keyHash"]["type"] == "bytes"
    assert fields_by_name["keyHash"]["fixed_length"] == 32
    assert "fixed_length" not in fields_by_name["avatar"]


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
