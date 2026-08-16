from __future__ import annotations

import json

from click.testing import CliRunner
from jsonschema import Draft202012Validator

from modelable.cli import cli
from modelable.compiler.workspace import load_workspace
from modelable.emitters.openapi import emit_openapi

_AUTO_PROJECTION_FIXTURE = """
domain customer {
  owner: "customer-platform"

  entity Customer @ 1 (additive) {
    @key
    customerId: uuid
    legalName: string
    @pii
    email: string
    @classification("secret")
    internalRiskNotes?: string
    status: enum(active, suspended, deleted)
    @server
    createdAt: timestamp
    @server
    updatedAt?: timestamp
  }

  auto projections Customer @ 1 {
    db

    request exclude [internalRiskNotes]

    reply exclude [@pii, @classification("secret")]

    event on [created, deleted]
  }
}
"""


def test_emit_openapi_emits_one_document_with_request_and_reply_schemas(tmp_path):
    (tmp_path / "customer.mdl").write_text(_AUTO_PROJECTION_FIXTURE, encoding="utf-8")
    workspace = load_workspace(tmp_path)

    artifacts = emit_openapi(workspace, tmp_path / "out")

    assert len(artifacts) == 1
    doc = artifacts[0]
    assert doc.target == "openapi"
    assert doc.path == tmp_path / "out" / "openapi.json"
    assert doc.artifact_id == "openapi"

    schemas = doc.content["components"]["schemas"]
    assert "customer.CustomerRequest.v1" in schemas
    assert "customer.CustomerReply.v1" in schemas
    assert doc.content["openapi"] == "3.1.0"
    assert doc.content["paths"] == {}

    request_props = schemas["customer.CustomerRequest.v1"]["properties"]
    assert "createdAt" not in request_props  # @server field excluded from request
    assert "internalRiskNotes" not in request_props  # explicit exclude
    assert "customerId" in request_props
    assert "email" in request_props  # @pii allowed in request, only excluded from reply

    reply_props = schemas["customer.CustomerReply.v1"]["properties"]
    assert "email" not in reply_props  # @pii excluded from reply
    assert "internalRiskNotes" not in reply_props  # @classification("secret") excluded
    assert "customerId" in reply_props
    assert "createdAt" in reply_props  # @server fields ARE included in reply

    assert schemas["customer.CustomerRequest.v1"]["x-modelable"]["kind"] == "request"
    assert schemas["customer.CustomerReply.v1"]["x-modelable"]["kind"] == "reply"
    assert schemas["customer.CustomerRequest.v1"]["x-modelable"]["domain"] == "customer"
    assert "customer.CustomerDb.v1" not in schemas  # db kind excluded by default


def test_emit_openapi_includes_hand_authored_and_event_excludes_db(tmp_path):
    (tmp_path / "customer.mdl").write_text(_AUTO_PROJECTION_FIXTURE, encoding="utf-8")
    (tmp_path / "billing.mdl").write_text(
        """
domain billing {
  owner: "billing-team"

  projection BillingCustomer @ 1
    from customer.Customer @ 1 as c
  {
    customerId <- c.customerId
    legalName <- c.legalName
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)

    artifacts = emit_openapi(workspace, tmp_path / "out")
    schemas = artifacts[0].content["components"]["schemas"]

    assert "billing.BillingCustomer.v1" in schemas
    assert schemas["billing.BillingCustomer.v1"]["x-modelable"]["kind"] == "projection"

    assert "customer.CustomerEvent.v1" in schemas
    assert schemas["customer.CustomerEvent.v1"]["x-modelable"]["kind"] == "event"

    assert "customer.CustomerDb.v1" not in schemas


def test_emit_openapi_type_mapping_matches_design_table(tmp_path):
    (tmp_path / "catalog.mdl").write_text(
        """
domain catalog {
  owner: "catalog-team"

  entity Product @ 1 (additive) {
    @key productId: uuid
    price: decimal(10, 2)
    thumbnailHash: binary(32)
    tags: array<string>
    attributes: map<string, string>
    status: enum(draft, published, archived)
  }

  projection ProductSummary @ 1
    from catalog.Product @ 1 as p
  {
    productId <- p.productId
    price <- p.price
    thumbnailHash <- p.thumbnailHash
    tags <- p.tags
    attributes <- p.attributes
    status <- p.status
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)

    artifacts = emit_openapi(workspace, tmp_path / "out")
    props = artifacts[0].content["components"]["schemas"]["catalog.ProductSummary.v1"]["properties"]

    assert props["price"]["type"] == "string"
    assert props["price"]["pattern"] == r"^-?\d+(\.\d+)?$"
    assert props["thumbnailHash"] == {
        "type": "string",
        "contentEncoding": "base64",
        "x-modelable-fixed-length": 32,
    }
    assert props["tags"] == {"type": "array", "items": {"type": "string"}}
    assert props["attributes"] == {"type": "object", "additionalProperties": {"type": "string"}}
    assert props["status"] == {"type": "string", "enum": ["draft", "published", "archived"]}


def test_emit_openapi_ref_type_resolves_to_dollar_ref(tmp_path):
    (tmp_path / "catalog.mdl").write_text(
        """
domain catalog {
  owner: "catalog-team"

  entity Brand @ 1 (additive) {
    @key brandId: uuid
    name: string
  }

  entity Product @ 1 (additive) {
    @key productId: uuid
    brand: ref<catalog.Brand @ 1>
  }

  projection ProductSummary @ 1
    from catalog.Product @ 1 as p
  {
    productId <- p.productId
    brand <- p.brand
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)

    artifacts = emit_openapi(workspace, tmp_path / "out")
    schemas = artifacts[0].content["components"]["schemas"]
    brand_prop = schemas["catalog.ProductSummary.v1"]["properties"]["brand"]

    assert brand_prop == {"$ref": "#/components/schemas/catalog.Brand.v1"}


def test_emit_openapi_is_deterministic_across_runs(tmp_path):
    (tmp_path / "customer.mdl").write_text(_AUTO_PROJECTION_FIXTURE, encoding="utf-8")
    workspace = load_workspace(tmp_path)

    first = emit_openapi(workspace, tmp_path / "out")
    second = emit_openapi(workspace, tmp_path / "out")

    assert first[0].content_hash == second[0].content_hash
    assert json.dumps(first[0].content, sort_keys=True) == json.dumps(second[0].content, sort_keys=True)


def test_emit_openapi_sorts_schemas_and_paths_by_identity(tmp_path):
    (tmp_path / "zeta.mdl").write_text(
        """
domain zeta {
  owner: "zeta-team"

  entity Zed @ 1 (additive) {
    @key id: uuid
    value: string
  }

  auto projections Zed @ 1 {
    reply
  }
}
""",
        encoding="utf-8",
    )
    (tmp_path / "alpha.mdl").write_text(
        """
domain alpha {
  owner: "alpha-team"

  entity Able @ 1 (additive) {
    @key id: uuid
    value: string
  }

  auto projections Able @ 1 {
    reply
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)

    document = emit_openapi(workspace, tmp_path / "out")[0].content

    assert list(document["components"]["schemas"]) == [
        "alpha.AbleReply.v1",
        "zeta.ZedReply.v1",
    ]


def test_emit_openapi_document_envelope_is_minimal_and_valid(tmp_path):
    (tmp_path / "customer.mdl").write_text(_AUTO_PROJECTION_FIXTURE, encoding="utf-8")
    workspace = load_workspace(tmp_path)

    artifacts = emit_openapi(workspace, tmp_path / "out")
    doc = artifacts[0].content

    assert set(doc.keys()) == {"openapi", "info", "components", "paths"}
    assert doc["paths"] == {}
    assert "title" in doc["info"]
    assert "version" in doc["info"]
    assert artifacts[0].warnings == []


def test_emit_openapi_components_schemas_validate_as_json_schema_2020_12(tmp_path):
    (tmp_path / "customer.mdl").write_text(_AUTO_PROJECTION_FIXTURE, encoding="utf-8")
    workspace = load_workspace(tmp_path)

    artifacts = emit_openapi(workspace, tmp_path / "out")
    fragment = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": artifacts[0].content["components"]["schemas"],
    }
    Draft202012Validator.check_schema(fragment)  # raises on failure


def test_compile_openapi_writes_single_document(tmp_path):
    mdl = tmp_path / "customer.mdl"
    mdl.write_text(_AUTO_PROJECTION_FIXTURE, encoding="utf-8")

    out = tmp_path / "dist"
    runner = CliRunner()
    result = runner.invoke(cli, ["compile", str(mdl), "--target", "openapi", "--out", str(out)])

    assert result.exit_code == 0, result.output
    doc_path = out / "openapi.json"
    assert doc_path.exists()
    doc = json.loads(doc_path.read_text(encoding="utf-8"))
    assert doc["openapi"] == "3.1.0"
    assert "customer.CustomerRequest.v1" in doc["components"]["schemas"]
