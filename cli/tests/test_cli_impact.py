from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from modelable.cli import cli

FIXTURE = Path(__file__).parent / "fixtures" / "customer.mdl"


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
    change_node = next(node for node in graph["nodes"] if node["id"] == "change:removed_field:email")
    assert change_node["kind"] == "change"
    assert change_node["field"] == "email"
    assert change_node["change_kind"] == "removed_field"
    assert {
        "kind": "causes",
        "source": "customer.Customer@1",
        "target": "change:removed_field:email",
    } in graph["edges"]
    assert {
        "kind": "causes",
        "source": "change:removed_field:email",
        "target": "billing.BillingCustomer@1",
    } in graph["edges"]


def test_impact_graph_omits_nonbreaking_changes(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        cli,
        [
            "impact",
            "--from",
            "customer.Customer@1",
            "--to",
            "customer.Customer@2",
            "--path",
            str(FIXTURE),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert not any(node["kind"] == "change" for node in payload["consequence_graph"]["nodes"])
