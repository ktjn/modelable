from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from modelable.cli import cli


def test_impact_json_reports_projection_consequences(tmp_path: Path) -> None:
    source = tmp_path / "workspace.mdl"
    source.write_text(
        """
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    @key
    customerId: uuid
    email: string
  }
  entity Customer @ 2 (breaking) {
    @key
    customerId: uuid
  }
}
domain billing {
  owner: "billing-team"
  projection BillingCustomer @ 1 from customer.Customer @ 1 as c {
    id <- c.customerId
    emailAddress <- c.email
  }
}
""".strip(),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli,
        [
            "impact",
            "--from",
            "customer.Customer@1",
            "--to",
            "customer.Customer@2",
            "--path",
            str(source),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["kind"] == "consequence_report"
    assert payload["status"] == "breaking"
    assert any(item["action"] == "breaking" for item in payload["consequences"])
    assert any("billing.BillingCustomer@1" in item["causal_path"] for item in payload["consequences"])
    graph = payload["consequence_graph"]
    assert graph["kind"] == "consequence_graph"
    assert {node["id"] for node in graph["nodes"]} >= {
        "customer.Customer@1",
        "customer.Customer@2",
        "billing.BillingCustomer@1",
    }
    assert {
        "kind": "causes",
        "source": "customer.Customer@1",
        "target": "customer.Customer@2",
    } in graph["edges"]
    assert {
        "kind": "causes",
        "source": "customer.Customer@1",
        "target": "billing.BillingCustomer@1",
    } in graph["edges"]
