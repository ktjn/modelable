from __future__ import annotations

from modelable.compiler.workspace import load_workspace
from modelable.emitters.openmetadata import emit_openmetadata


def test_emit_openmetadata(tmp_path):
    (tmp_path / "customer.mdl").write_text(
        """
domain customer {
  owner: "customer-team"
  description: "Manage customers and accounts"

  entity Customer @ 1 {
    @key customerId: uuid
    name: string
  }

  projection CustomerSummary @ 1
    from customer.Customer @ 1 as c
  {
    customerId <- c.customerId
    name <- c.name
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
    assert len(data["assets"]) == 1  # Projection

    asset = data["assets"][0]
    assert asset["name"] == "CustomerSummary"
    assert asset["kind"] == "projection"
