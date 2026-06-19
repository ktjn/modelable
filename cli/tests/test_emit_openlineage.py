from __future__ import annotations

import json

from click.testing import CliRunner

from modelable.cli import cli
from modelable.compiler.workspace import load_workspace
from modelable.emitters.openlineage import emit_openlineage


def test_emit_openlineage_projection_event_with_column_lineage(tmp_path):
    (tmp_path / "customer.mdl").write_text(
        """
domain customer {
  owner: "customer-team"
  description: "Manage customers and accounts"

  entity Customer @ 1 (additive) {
    @key customerId: uuid
    @pii
    @classification("confidential")
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
    artifacts = emit_openlineage(workspace, tmp_path / "out")

    projection_art = next(art for art in artifacts if art.ref == "customer.CustomerSummary@1")
    assert projection_art.target == "openlineage"
    assert projection_art.artifact_id == "customer.CustomerSummary.v1"
    assert projection_art.path == tmp_path / "out" / "customer.CustomerSummary.v1.openlineage.json"

    event = projection_art.content
    assert event["eventType"] == "COMPLETE"
    assert event["producer"] == "https://github.com/ktjn/modelable"
    assert event["job"] == {
        "namespace": "modelable://customer",
        "name": "compile/customer.CustomerSummary.v1",
    }
    assert event["run"]["runId"] == "modelable-customer-CustomerSummary-v1"
    assert event["inputs"] == [
        {
            "namespace": "modelable://customer",
            "name": "customer.Customer.v1",
            "facets": {
                "schema": {
                    "_producer": "https://github.com/ktjn/modelable",
                    "_schemaURL": "https://openlineage.io/spec/facets/1-1-1/SchemaDatasetFacet.json",
                    "fields": [
                        {"name": "customerId", "type": "uuid"},
                        {"name": "email", "type": "string", "description": "classification=confidential; pii=true"},
                        {"name": "name", "type": "string"},
                    ],
                }
            },
        }
    ]

    output = event["outputs"][0]
    assert output["namespace"] == "modelable://customer"
    assert output["name"] == "customer.CustomerSummary.v1"
    assert output["facets"]["schema"]["fields"] == [
        {"name": "customerId", "type": "uuid"},
        {"name": "name", "type": "string"},
        {"name": "email", "type": "string", "description": "classification=confidential; pii=true"},
        {"name": "displayName", "type": "string"},
    ]
    assert output["facets"]["columnLineage"] == {
        "_producer": "https://github.com/ktjn/modelable",
        "_schemaURL": "https://openlineage.io/spec/facets/1-2-0/ColumnLineageDatasetFacet.json",
        "fields": {
            "customerId": {
                "inputFields": [
                    {"namespace": "modelable://customer", "name": "customer.Customer.v1", "field": "customerId"}
                ]
            },
            "name": {
                "inputFields": [{"namespace": "modelable://customer", "name": "customer.Customer.v1", "field": "name"}]
            },
            "email": {
                "inputFields": [{"namespace": "modelable://customer", "name": "customer.Customer.v1", "field": "email"}]
            },
            "displayName": {
                "inputFields": [{"namespace": "modelable://customer", "name": "customer.Customer.v1", "field": "name"}],
                "transformationDescription": "c.name",
                "transformationType": "TRANSFORMATION",
            },
        },
    }


def test_compile_openlineage_writes_json_artifact(tmp_path):
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
    result = CliRunner().invoke(cli, ["compile", str(mdl), "--target", "openlineage", "--out", str(out)])

    assert result.exit_code == 0, result.output
    artifact = out / "customer.Customer.v1.openlineage.json"
    assert artifact.exists()
    event = json.loads(artifact.read_text(encoding="utf-8"))
    assert event["outputs"][0]["name"] == "customer.Customer.v1"
