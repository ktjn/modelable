from __future__ import annotations

import json

import pytest

from modelable.compiler.workspace import load_workspace
from modelable.emitters.protobuf import emit_protobuf
from modelable.parser import parse_text_to_ir
from modelable.parser.ir import ParseError


def test_parse_model_protobuf_reservations():
    mdl = parse_text_to_ir(
        """
domain billing {
  owner: "billing"

  entity Customer @ 2 (additive) {
    reserved protobuf {
      numbers: [3, 7]
      names: ["legacy_status", "old_status"]
    }

    @key customerId: uuid
    displayName?: string
  }
}
"""
    )

    customer = mdl.domains[0].models["Customer"][0]
    assert customer.protobuf_reservations is not None
    assert customer.protobuf_reservations.numbers == [3, 7]
    assert customer.protobuf_reservations.names == ["legacy_status", "old_status"]


def test_parse_projection_protobuf_reservations():
    mdl = parse_text_to_ir(
        """
domain billing {
  owner: "billing"

  entity Customer @ 1 (additive) {
    @key customerId: uuid
    status: string
  }

  projection CustomerView @ 2 from billing.Customer@1 as c {
    reserved protobuf {
      numbers: [2]
      names: ["status"]
    }

    customerId <- c.customerId
  }
}
"""
    )

    projection = mdl.domains[0].projections["CustomerView"][0]
    assert projection.protobuf_reservations is not None
    assert projection.protobuf_reservations.numbers == [2]
    assert projection.protobuf_reservations.names == ["status"]


def test_reject_duplicate_protobuf_reservation_numbers():
    with pytest.raises(ParseError, match="duplicate protobuf reservation number"):
        parse_text_to_ir(
            """
domain billing {
  owner: "billing"
  entity Customer @ 2 (additive) {
    reserved protobuf {
      numbers: [3, 3]
    }
    @key customerId: uuid
  }
}
"""
        )


def test_reject_empty_protobuf_reservation_block():
    with pytest.raises(ParseError, match="must reserve at least one number or name"):
        parse_text_to_ir(
            """
domain billing {
  owner: "billing"
  entity Customer @ 2 (additive) {
    reserved protobuf {
    }
    @key customerId: uuid
  }
}
"""
        )


def test_emit_protobuf_renders_reserved_numbers_and_names(tmp_path):
    source = tmp_path / "model.mdl"
    source.write_text(
        """
domain billing {
  owner: "billing"
  entity Customer @ 2 (additive) {
    reserved protobuf {
      numbers: [3, 7]
      names: ["legacy_status"]
    }
    @key customerId: uuid
  }
}
""",
        encoding="utf-8",
    )
    artifacts = emit_protobuf(load_workspace(source), tmp_path / "out")
    proto = next(artifact for artifact in artifacts if artifact.path.name == "Customer.v2.proto")

    assert "  reserved 3, 7;" in proto.content
    assert '  reserved "legacy_status";' in proto.content


def test_emit_protobuf_manifest_records_reservations_and_fingerprint_changes(tmp_path):
    source = tmp_path / "model.mdl"
    source.write_text(
        """
domain billing {
  owner: "billing"
  entity Customer @ 2 (additive) {
    reserved protobuf {
      numbers: [3]
      names: ["legacy_status"]
    }
    @key customerId: uuid
  }
}
""",
        encoding="utf-8",
    )
    artifacts = emit_protobuf(load_workspace(source), tmp_path / "out")
    manifest = next(artifact for artifact in artifacts if artifact.path.name == "schema-manifest.json")
    schema = json.loads(manifest.content)["schemas"][0]

    assert schema["reservations"] == {"numbers": [3], "names": ["legacy_status"]}

    without_reservations = tmp_path / "without.mdl"
    without_reservations.write_text(
        """
domain billing {
  owner: "billing"
  entity Customer @ 2 (additive) {
    @key customerId: uuid
  }
}
""",
        encoding="utf-8",
    )
    without_manifest = next(
        artifact
        for artifact in emit_protobuf(load_workspace(without_reservations), tmp_path / "without")
        if artifact.path.name == "schema-manifest.json"
    )
    assert json.loads(without_manifest.content)["schemas"][0]["schema_fingerprint"] != schema["schema_fingerprint"]


def test_emit_protobuf_rejects_field_colliding_with_reserved_number(tmp_path):
    source = tmp_path / "model.mdl"
    source.write_text(
        """
domain billing {
  owner: "billing"
  entity Customer @ 2 (additive) {
    reserved protobuf {
      numbers: [2]
    }
    @key customerId: uuid
    displayName: string
  }
}
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="reserved protobuf field number 2"):
        emit_protobuf(load_workspace(source), tmp_path / "out")
