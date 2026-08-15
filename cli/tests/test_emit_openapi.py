from __future__ import annotations

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
