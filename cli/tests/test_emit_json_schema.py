import hashlib
import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from jsonschema import Draft202012Validator

from modelable.cli import cli
from modelable.compiler.workspace import load_workspace
from modelable.emitters.json_schema import emit_json_schema


def test_emit_simple_model(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text(
        """
domain customer {
  owner: "customer-team"
  contact: "customer-team@example.com"
  description: "Customer identity and lifecycle."
    entity Customer @ 1 (additive) {
    @key customerId: uuid
    name: string
    age?: int
    marketingConsent: bool = false
    address: object {
      line1: string
      line2?: string
    }
    active: bool
    balance: decimal(12, 2)
    tags: array<string>
    meta: map<string, int>
    status: enum(active, blocked)
    createdAt: timestamp
    birthDate: date
    wakeTime: time
    ttl: duration
    avatar: binary
  }
}
""",
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)
    artifacts = emit_json_schema(workspace, tmp_path / "out")
    assert len(artifacts) == 1

    art = artifacts[0]
    assert art.target == "json-schema"
    assert art.ref == "customer.Customer@1"
    assert art.artifact_id == "customer.Customer.v1"
    assert art.content_hash == hashlib.sha256(
        json.dumps(art.content, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()

    schema = art.content
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["type"] == "object"
    assert schema["title"] == "Customer"
    assert schema["x-modelable"]["domain"] == "customer"
    assert schema["x-modelable"]["owner"] == "customer-team"
    assert schema["x-modelable"]["contact"] == "customer-team@example.com"
    assert schema["x-modelable"]["description"] == "Customer identity and lifecycle."
    assert schema["x-modelable"]["version"] == 1

    props = schema["properties"]
    assert props["customerId"]["type"] == "string"
    assert props["customerId"]["format"] == "uuid"
    assert props["customerId"]["x-modelable-field"]["key"] is True

    assert props["name"]["type"] == "string"
    assert props["age"]["type"] == "integer"
    assert props["age"]["format"] == "int64"
    assert "age" not in schema.get("required", [])
    assert "customerId" in schema["required"]
    assert props["marketingConsent"]["default"] is False

    assert props["address"]["$ref"] == "#/$defs/Address"
    assert schema["$defs"]["Address"]["type"] == "object"
    assert schema["$defs"]["Address"]["properties"]["line1"]["type"] == "string"
    assert "line2" not in schema["$defs"]["Address"].get("required", [])

    assert props["active"]["type"] == "boolean"
    assert props["balance"]["type"] == "string"
    assert props["balance"]["pattern"] == r"^-?\d+(\.\d+)?$"

    assert props["tags"]["type"] == "array"
    assert props["tags"]["items"]["type"] == "string"

    assert props["meta"]["type"] == "object"
    assert props["meta"]["additionalProperties"]["type"] == "integer"

    assert props["status"]["type"] == "string"
    assert props["status"]["enum"] == ["active", "blocked"]

    assert props["createdAt"]["format"] == "date-time"
    assert props["birthDate"]["format"] == "date"
    assert props["wakeTime"]["format"] == "time"
    assert props["ttl"]["format"] == "duration"
    assert props["avatar"]["contentEncoding"] == "base64"

    # Schema must validate
    Draft202012Validator.check_schema(schema)


def test_emit_projection_with_lineage(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text(
        """
domain customer {
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    legalName: string
    @pii
    email?: string
  }

  projection CustomerBrief @ 1
    from customer.Customer @ 1 as c
    where c.status == "active"
    group by c.status
  {
    briefId <- c.customerId
    displayName = c.legalName + " (" + c.email + ")"
  }
}
""",
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)
    artifacts = emit_json_schema(workspace, tmp_path / "out")
    proj_artifacts = [a for a in artifacts if a.ref == "customer.CustomerBrief@1"]
    assert len(proj_artifacts) == 1

    schema = proj_artifacts[0].content
    props = schema["properties"]

    assert schema["x-modelable"]["where"] == 'c.status == "active"'
    assert schema["x-modelable"]["groupBy"] == ["c.status"]
    assert props["briefId"]["x-modelable-lineage"]["kind"] == "direct"
    assert props["briefId"]["x-modelable-lineage"]["source"] == "c.customerId"
    assert props["briefId"]["x-modelable-lineage"]["sourceModel"] == "customer.Customer"

    assert props["displayName"]["x-modelable-lineage"]["kind"] == "computed"
    assert "c.legalName" in props["displayName"]["x-modelable-lineage"]["expression"]

    Draft202012Validator.check_schema(schema)


def test_emit_classification_extension(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text(
        """
domain customer {
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    @classification("confidential")
    ssn?: string
  }
}
""",
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)
    artifacts = emit_json_schema(workspace, tmp_path / "out")
    props = artifacts[0].content["properties"]
    assert props["ssn"]["x-modelable-classification"] == "confidential"


def test_emit_ref_type(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text(
        """
domain customer {
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    address: ref<address.Address>
  }
}
""",
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)
    artifacts = emit_json_schema(workspace, tmp_path / "out")
    props = artifacts[0].content["properties"]
    assert props["address"]["type"] == "string"
    assert props["address"]["x-modelable-ref"] == "address.Address"


def test_emit_inline_object_uses_nested_defs(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text(
        """
domain customer {
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    shipping: object {
      address: object {
        line1: string
        line2?: string
      }
    }
  }
}
""",
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)
    artifacts = emit_json_schema(workspace, tmp_path / "out")
    schema = artifacts[0].content

    assert schema["properties"]["shipping"]["$ref"] == "#/$defs/Shipping"
    assert schema["$defs"]["Shipping"]["properties"]["address"]["$ref"] == "#/$defs/ShippingAddress"
    assert schema["$defs"]["Shipping"]["title"] == "Shipping"
    assert schema["$defs"]["ShippingAddress"]["title"] == "ShippingAddress"
    assert schema["$defs"]["ShippingAddress"]["properties"]["line1"]["type"] == "string"
    assert "line2" not in schema["$defs"]["ShippingAddress"].get("required", [])


def test_emit_named_type_warns_on_placeholder(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text(
        """
domain customer {
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    address: Address
  }
}
""",
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)
    artifacts = emit_json_schema(workspace, tmp_path / "out")
    art = artifacts[0]
    assert art.content["properties"]["address"]["$ref"] == "#/$defs/Address"
    assert art.content["$defs"]["Address"]["x-modelable-field"]["namedType"] == "Address"
    assert art.content["$defs"]["Address"]["title"] == "Address"
    assert art.warnings
    assert any("EMIT002" in warning for warning in art.warnings)


def test_emit_validates_against_draft202012(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text(
        """
domain customer {
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    name: string
  }
}
""",
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)
    artifacts = emit_json_schema(workspace, tmp_path / "out")
    for art in artifacts:
        assert not art.warnings
        Draft202012Validator.check_schema(art.content)


def test_cli_compile_json_schema_writes_files(tmp_path):
    mdl = tmp_path / "customer.mdl"
    mdl.write_text(
        """
domain customer {
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    name: string
  }
}
""",
        encoding="utf-8",
    )

    out = tmp_path / "dist" / "jsonschema"
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            cli,
            ["compile", str(mdl), "--target", "json-schema", "--out", str(out)],
        )

    assert result.exit_code == 0
    assert (out / "customer.Customer.v1.json").exists()
    schema = json.loads((out / "customer.Customer.v1.json").read_text(encoding="utf-8"))
    assert schema["title"] == "Customer"
    Draft202012Validator.check_schema(schema)
