from __future__ import annotations

from modelable.compiler.workspace import load_workspace
from modelable.emitters.openmetadata import emit_openmetadata


def test_emit_openmetadata(tmp_path):
    (tmp_path / "customer.mdl").write_text(
        """
domain customer {
  owner: "customer-team"
  description: "Manage customers and accounts"

  entity Customer @ 1 (additive) {
    @key customerId: uuid
    @pii
    @classification("confidential")
    @owner("identity-team")
    email: string
    name: string
  }

  projection CustomerSummary @ 1
    from customer.Customer @ 1 as c
  {
    customerId <- c.customerId
    name <- c.name
    email <- c.email
    displayName = c.name
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_openmetadata(workspace, tmp_path / "out")

    # Verify artifacts
    assert len(artifacts) == 1  # Only one domain

    art = artifacts[0]
    assert art.target == "openmetadata"
    assert art.ref == "customer"

    # Parse json
    data = art.content
    assert data["name"] == "customer"
    assert data["description"] == "Manage customers and accounts"
    assert data["owner"] == "customer-team"
    assert len(data["assets"]) == 2

    model_asset = next(asset for asset in data["assets"] if asset["name"] == "Customer")
    assert model_asset["kind"] == "entity"
    assert model_asset["version"] == 1
    assert model_asset["fullyQualifiedName"] == "modelable.customer.Customer.v1"
    assert model_asset["fields"] == [
        {
            "name": "customerId",
            "type": "uuid",
            "required": True,
            "key": True,
            "pii": False,
            "classification": None,
            "owner": None,
        },
        {
            "name": "email",
            "type": "string",
            "required": True,
            "key": False,
            "pii": True,
            "classification": "confidential",
            "owner": "identity-team",
        },
        {
            "name": "name",
            "type": "string",
            "required": True,
            "key": False,
            "pii": False,
            "classification": None,
            "owner": None,
        },
    ]

    projection_asset = next(asset for asset in data["assets"] if asset["name"] == "CustomerSummary")
    assert projection_asset["kind"] == "projection"
    assert projection_asset["version"] == 1
    assert projection_asset["fullyQualifiedName"] == "modelable.customer.CustomerSummary.v1"
    assert projection_asset["source"] == {
        "model": "customer.Customer",
        "version": {"kind": "exact", "version": 1},
        "alias": "c",
    }
    assert projection_asset["fields"] == [
        {
            "name": "customerId",
            "mapping": "direct",
            "source": "customer.Customer@1.customerId",
            "pii": False,
            "classification": None,
        },
        {
            "name": "name",
            "mapping": "direct",
            "source": "customer.Customer@1.name",
            "pii": False,
            "classification": None,
        },
        {
            "name": "email",
            "mapping": "direct",
            "source": "customer.Customer@1.email",
            "pii": True,
            "classification": "confidential",
        },
        {
            "name": "displayName",
            "mapping": "computed",
            "expression": "c.name",
            "pii": False,
            "classification": None,
        },
    ]
    assert data["lineage"] == [
        {
            "from": "modelable.customer.Customer.v1.customerId",
            "to": "modelable.customer.CustomerSummary.v1.customerId",
            "kind": "direct",
        },
        {
            "from": "modelable.customer.Customer.v1.name",
            "to": "modelable.customer.CustomerSummary.v1.name",
            "kind": "direct",
        },
        {
            "from": "modelable.customer.Customer.v1.email",
            "to": "modelable.customer.CustomerSummary.v1.email",
            "kind": "direct",
        },
    ]
