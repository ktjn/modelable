from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from modelable.cli import cli
from modelable.compiler.workspace import load_workspace
from modelable.conversion import build_conversion_plans
from modelable.conversion_plan import build_conversion_plan
from modelable.planner.plans import build_plan_documents


def test_conversion_report_classifies_direct_projection(tmp_path: Path) -> None:
    source = tmp_path / "workspace.mdl"
    source.write_text(
        """
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    @key
    customerId: uuid
  }
  projection CustomerReply @ 1 from customer.Customer @ 1 as c {
    customerId <- c.customerId
  }
}
""".strip(),
        encoding="utf-8",
    )
    result = CliRunner().invoke(cli, ["conversions", "--path", str(source), "--format", "json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["plans"][0]["classification"] == "total_reversible"


def test_conversion_plan_consumer_preserves_classification(tmp_path: Path) -> None:
    source = tmp_path / "workspace.mdl"
    source.write_text(
        """
domain customer {
  entity Customer @ 1 (additive) {
    @key
    customerId: uuid
    email: string
  }
  projection CustomerReply @ 1 from customer.Customer @ 1 as c {
    customerId <- c.customerId
  }
}
""".strip(),
        encoding="utf-8",
    )
    workspace = load_workspace(source.parent)
    plan = next(item for item in build_plan_documents(workspace) if item["projection"] == "CustomerReply")

    assert build_conversion_plan(plan).as_dict() == build_conversion_plans(workspace)[0].as_dict()


def test_migration_plan_reports_removed_field(tmp_path: Path) -> None:
    source = tmp_path / "workspace.mdl"
    source.write_text(
        """
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) { @key customerId: uuid email: string }
  entity Customer @ 2 (breaking) { @key customerId: uuid }
}
""".strip()
        .replace("{ @key customerId: uuid email: string }", "{\n    @key\n    customerId: uuid\n    email: string\n  }")
        .replace("{ @key customerId: uuid }", "{\n    @key\n    customerId: uuid\n  }"),
        encoding="utf-8",
    )
    result = CliRunner().invoke(
        cli,
        [
            "migration",
            "plan",
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

    assert result.exit_code == 0, result.output
    facts = json.loads(result.output)["facts"]
    assert any(fact["kind"] == "field_removal" for fact in facts)
