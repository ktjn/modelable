from __future__ import annotations

import json

from click.testing import CliRunner

from modelable.cli import cli
from modelable.compiler.workspace import load_workspace
from modelable.emitters.avro import emit_avro

SOURCE = """
domain customer {
  owner: "customer-team"

  entity Customer @ 1 (additive) {
    @key customerId: uuid
    createdAt: timestamp
    birthDate: date
    amount: decimal(10, 2)
    payload: binary(16)
    tags: array<string>
    labels: map<string, string>
    status: enum(active, deleted)
    nickname?: string
  }

  projection CustomerEvent @ 1
    from customer.Customer @ 1 as c
  {
    customerId <- c.customerId
    status <- c.status
  }
}
"""


def test_emit_avro_models_and_event_records_with_logical_types(tmp_path) -> None:
    (tmp_path / "customer.mdl").write_text(SOURCE, encoding="utf-8")

    artifacts = emit_avro(load_workspace(tmp_path), tmp_path / "out")
    by_ref = {artifact.ref: artifact for artifact in artifacts}

    assert set(by_ref) == {"customer.Customer@1", "customer.CustomerEvent@1"}
    model = by_ref["customer.Customer@1"].content
    fields = {field["name"]: field for field in model["fields"]}

    assert model["type"] == "record"
    assert model["name"] == "CustomerV1"
    assert model["namespace"] == "customer"
    assert fields["customerId"]["type"] == {"type": "string", "logicalType": "uuid"}
    assert fields["createdAt"]["type"] == {"type": "long", "logicalType": "timestamp-millis"}
    assert fields["birthDate"]["type"] == {"type": "int", "logicalType": "date"}
    assert fields["amount"]["type"] == {
        "type": "bytes",
        "logicalType": "decimal",
        "precision": 10,
        "scale": 2,
    }
    assert fields["payload"]["type"] == {"type": "fixed", "name": "CustomerpayloadFixed", "size": 16}
    assert fields["tags"]["type"] == {"type": "array", "items": "string"}
    assert fields["labels"]["type"] == {"type": "map", "values": "string"}
    assert fields["status"]["type"] == {"type": "enum", "name": "CustomerstatusEnum", "symbols": ["active", "deleted"]}
    assert fields["nickname"]["type"] == ["null", "string"]
    assert fields["nickname"]["default"] is None

    event = by_ref["customer.CustomerEvent@1"].content
    assert [field["name"] for field in event["fields"]] == ["customerId", "status"]


def test_compile_avro_writes_deterministic_avsc_artifacts(tmp_path) -> None:
    source = tmp_path / "customer.mdl"
    source.write_text(SOURCE, encoding="utf-8")
    out = tmp_path / "dist"

    result = CliRunner().invoke(cli, ["compile", str(source), "--target", "avro", "--out", str(out)])

    assert result.exit_code == 0, result.output
    artifact = out / "customer" / "Customer.v1.avsc"
    assert artifact.exists()
    assert json.loads(artifact.read_text(encoding="utf-8"))["name"] == "CustomerV1"


def test_emit_avro_accepts_defaults_for_structured_logical_schemas(tmp_path) -> None:
    source = """
domain billing {
  owner: "billing-team"

  entity Invoice @ 1 (additive) {
    @key invoiceId: uuid
    amount: decimal(10, 2) = 0
    issuedAt: timestamp = 0
  }
}
"""
    (tmp_path / "billing.mdl").write_text(source, encoding="utf-8")

    artifacts = emit_avro(load_workspace(tmp_path), tmp_path / "out")
    fields = {field["name"]: field for field in artifacts[0].content["fields"]}

    assert fields["amount"]["default"] == "0"
    assert fields["issuedAt"]["default"] == "0"
