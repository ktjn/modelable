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
