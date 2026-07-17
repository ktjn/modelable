from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from modelable.cli import cli
from modelable.compiler.workspace import load_workspace
from modelable.emitters.protobuf import emit_protobuf
from modelable.registry.signature import compute_version_signature


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


def test_emit_protobuf_maps_use_native_map_type_and_manifest_metadata(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain platform {
  owner: "platform-team"

  entity Widget @ 1 (additive) {
    @key widgetId: uuid
    attributes: map<string, int>
    counts?: map<u32, u64>
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)

    artifacts = emit_protobuf(workspace, tmp_path / "out")

    proto = next(art for art in artifacts if art.ref == "platform.Widget@1" and art.path.suffix == ".proto")
    assert "map<string, int64> attributes = 2;" in proto.content
    assert "map<uint32, uint64> counts = 3;" in proto.content
    assert "optional map" not in proto.content
    assert "bytes attributes" not in proto.content
    assert "bytes counts" not in proto.content

    manifest = next(
        art for art in artifacts if art.ref == "platform.Widget@1" and art.path.name == "schema-manifest.json"
    )
    fields = {field["name"]: field for field in json.loads(manifest.content)["schemas"][0]["fields"]}
    assert fields["attributes"]["type"] == "map<string, int64>"
    assert fields["attributes"]["map"] == {"key_type": "string", "value_type": "int64"}
    assert fields["counts"]["type"] == "map<uint32, uint64>"
    assert fields["counts"]["map"] == {"key_type": "uint32", "value_type": "uint64"}


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


def test_emit_protobuf_semantic_bundles_are_stable_and_flatten_chains(tmp_path):
    (tmp_path / "semantic.mdl").write_text(
        """
domain platform {
  owner: "platform-team"

  semantic EntityId : uuid
  semantic OrderId : EntityId
  semantic SchemaId : u32 { registry: true }
  semantic RecordedAt : timestamp
  semantic ContentHash : binary(32)
  semantic Amount : decimal(12, 2)
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)

    artifacts = emit_protobuf(
        workspace,
        tmp_path / "out",
        registry_ids={"platform.SchemaId": 7},
    )

    bundle = next(art for art in artifacts if art.path.name == "semantic-types.proto")
    assert bundle.target == "protobuf"
    assert bundle.ref == "platform.semantic-types"
    assert bundle.artifact_id == "platform.semantic-types"
    assert bundle.path == tmp_path / "out" / "platform" / "semantic-types.proto"
    assert (
        bundle.content
        == """syntax = "proto3";

package modelable.platform.semantic;

import "google/protobuf/timestamp.proto";

message Amount {
  string value = 1;
}

message ContentHash {
  bytes value = 1;
}

message EntityId {
  string value = 1;
}

message OrderId {
  string value = 1;
}

message RecordedAt {
  google.protobuf.Timestamp value = 1;
}

message SchemaId {
  uint32 value = 1;
}
"""
    )


def test_emit_protobuf_semantic_bundles_are_domain_scoped_and_deterministic(tmp_path):
    (tmp_path / "semantic.mdl").write_text(
        """
domain zeta {
  owner: "zeta-team"
  semantic ZetaId : u64
}

domain alpha {
  owner: "alpha-team"
  semantic AlphaId : i32
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)

    first = emit_protobuf(workspace, tmp_path / "first")
    second = emit_protobuf(workspace, tmp_path / "second")
    first_bundles = [(art.ref, art.content) for art in first if art.path.name == "semantic-types.proto"]
    second_bundles = [(art.ref, art.content) for art in second if art.path.name == "semantic-types.proto"]

    assert first_bundles == second_bundles
    assert [ref for ref, _ in first_bundles] == [
        "alpha.semantic-types",
        "zeta.semantic-types",
    ]


def test_emit_protobuf_models_import_nominal_semantic_wrappers(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain platform {
  owner: "platform-team"
  semantic SchemaId : u32 { registry: true }
}

domain runtime {
  owner: "runtime-team"
  semantic CommandId : uuid

  entity RuntimeConfig @ 1 (additive) {
    @key commandId: CommandId
    schemaId: SchemaId
    relatedSchemaIds: array<SchemaId>
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)

    artifacts = emit_protobuf(workspace, tmp_path / "out")
    proto = next(art for art in artifacts if art.ref == "runtime.RuntimeConfig@1" and art.path.suffix == ".proto")

    assert 'import "platform/semantic-types.proto";' in proto.content
    assert 'import "runtime/semantic-types.proto";' in proto.content
    assert proto.content.index('import "platform/semantic-types.proto";') < proto.content.index(
        'import "runtime/semantic-types.proto";'
    )
    assert ".modelable.runtime.semantic.CommandId command_id = 1;" in proto.content
    assert ".modelable.platform.semantic.SchemaId schema_id = 2;" in proto.content
    assert "repeated .modelable.platform.semantic.SchemaId related_schema_ids = 3;" in proto.content


def test_emit_protobuf_projection_preserves_source_semantic_type(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain platform {
  owner: "platform-team"
  semantic SchemaId : u32 { registry: true }

  entity Schema @ 1 (additive) {
    @key schemaId: SchemaId
  }

  projection SchemaView @ 1
    from platform.Schema @ 1 as s
  {
    schemaId <- s.schemaId
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)

    artifacts = emit_protobuf(workspace, tmp_path / "out")
    proto = next(art for art in artifacts if art.ref == "platform.SchemaView@1" and art.path.suffix == ".proto")

    assert 'import "platform/semantic-types.proto";' in proto.content
    assert ".modelable.platform.semantic.SchemaId schema_id = 1;" in proto.content


def test_emit_protobuf_keeps_nonsemantic_named_type_fallbacks(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain example {
  owner: "example-team"

  value Address @ 1 (additive) {
    line1: string
  }

  entity Customer @ 1 (additive) {
    @key customerId: uuid
    address: Address
    attributes: map<string, string>
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)

    artifacts = emit_protobuf(workspace, tmp_path / "out")
    proto = next(art for art in artifacts if art.ref == "example.Customer@1" and art.path.suffix == ".proto")

    assert "bytes address = 2;" in proto.content
    assert "map<string, string> attributes = 3;" in proto.content
    assert "semantic-types.proto" not in proto.content


def test_emit_protobuf_rejects_ambiguous_unqualified_semantic_reference(tmp_path):
    (tmp_path / "model.mdl").write_text(
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
    workspace = load_workspace(tmp_path)

    with pytest.raises(
        ValueError,
        match=r"ambiguous semantic type 'SharedId'.*alpha.SharedId.*beta.SharedId",
    ):
        emit_protobuf(workspace, tmp_path / "out")


def test_emit_protobuf_manifest_separates_canonical_and_semantic_identity(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain platform {
  owner: "platform-team"
  semantic SchemaId : u32 { registry: true }
  semantic Label : string

  entity Schema @ 3 (additive) {
    @key schemaId: SchemaId
    parentSchemaId?: SchemaId
    label: Label
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    version = workspace.mdl.domains[0].models["Schema"][0]

    artifacts = emit_protobuf(
        workspace,
        tmp_path / "out",
        registry_ids={"platform.SchemaId": 11, "platform.Label": 99},
    )
    manifest = next(
        art for art in artifacts if art.ref == "platform.Schema@3" and art.path.name == "schema-manifest.json"
    )
    schema = json.loads(manifest.content)["schemas"][0]

    assert schema["modelable_signature"] == compute_version_signature("platform", "Schema", version)
    assert schema["schema_fingerprint"] != schema["modelable_signature"]
    assert schema["semantic_types"] == [
        {
            "ref": "platform.Label",
            "proto_type": ".modelable.platform.semantic.Label",
            "underlying_type": "string",
        },
        {
            "ref": "platform.SchemaId",
            "proto_type": ".modelable.platform.semantic.SchemaId",
            "underlying_type": "uint32",
            "registry_id": 11,
        },
    ]
    fields = {field["name"]: field for field in schema["fields"]}
    assert fields["schemaId"]["semantic_type"] == "platform.SchemaId"
    assert fields["parentSchemaId"]["semantic_type"] == "platform.SchemaId"
    assert fields["label"]["semantic_type"] == "platform.Label"


def test_emit_protobuf_projection_manifest_has_canonical_signature(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain platform {
  owner: "platform-team"
  semantic SchemaId : u32 { registry: true }

  entity Schema @ 1 (additive) {
    @key schemaId: SchemaId
  }

  projection SchemaView @ 2
    from platform.Schema @ 1 as s
  {
    schemaId <- s.schemaId
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    version = workspace.mdl.domains[0].projections["SchemaView"][0]
    artifacts = emit_protobuf(workspace, tmp_path / "out")
    manifest = next(
        art for art in artifacts if art.ref == "platform.SchemaView@2" and art.path.name == "schema-manifest.json"
    )
    schema = json.loads(manifest.content)["schemas"][0]

    assert schema["modelable_signature"] == compute_version_signature("platform", "SchemaView", version)
    assert schema["semantic_types"][0]["ref"] == "platform.SchemaId"
    assert "registry_id" not in schema["semantic_types"][0]


def test_emit_protobuf_registry_allocation_does_not_change_wire_fingerprint(
    tmp_path,
):
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
    without_id = emit_protobuf(workspace, tmp_path / "without")
    with_id = emit_protobuf(
        workspace,
        tmp_path / "with",
        registry_ids={"platform.SchemaId": 23},
    )

    def schema(artifacts):
        manifest = next(art for art in artifacts if art.path.name == "schema-manifest.json")
        return json.loads(manifest.content)["schemas"][0]

    assert schema(without_id)["schema_fingerprint"] == schema(with_id)["schema_fingerprint"]
    assert "registry_id" not in schema(without_id)["semantic_types"][0]
    assert schema(with_id)["semantic_types"][0]["registry_id"] == 23


@pytest.mark.parametrize("registry_id", [True, 0, -1, 2**32])
def test_emit_protobuf_rejects_invalid_registry_id(tmp_path, registry_id):
    (tmp_path / "model.mdl").write_text(
        """
domain platform {
  owner: "platform-team"
  semantic SchemaId : u32 { registry: true }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)

    with pytest.raises(
        ValueError,
        match=r"registry id for platform.SchemaId must be between 1 and 4294967295",
    ):
        emit_protobuf(
            workspace,
            tmp_path / "out",
            registry_ids={"platform.SchemaId": registry_id},
        )


def test_compile_protobuf_passes_registry_allocations_to_manifest(tmp_path):
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
            ["compile", str(mdl), "--target", "protobuf", "--out", str(out)],
        )

    assert result.exit_code == 0, result.output
    schema = json.loads((out / "platform" / "Schema.v1" / "schema-manifest.json").read_text(encoding="utf-8"))[
        "schemas"
    ][0]
    assert schema["semantic_types"][0]["registry_id"] == 1


def test_compile_protobuf_domain_scope_preserves_semantic_ambiguity(tmp_path):
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
            "protobuf",
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
