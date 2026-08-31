from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from modelable.cli import cli
from modelable.emitters.targets import list_implemented_codegen_targets

PRODUCER_V1 = """
domain customer {
  owner: "customer-platform"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    displayName: string
  }
}
"""

PRODUCER_V2 = """
domain customer {
  owner: "customer-platform"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    displayName: string
  }
  entity Customer @ 2 (additive) {
    @key customerId: uuid
    displayName: string
    nickname?: string
  }
}
"""

CONSUMER = """
domain analytics {
  owner: "analytics-platform"
  projection CustomerSummary @ 1
    from customer.Customer @ 1 as c
  {
    customerId <- c.customerId
    name <- c.displayName
  }
}
"""


def test_offline_feature_fixture_compiles_consumer_for_every_implemented_target(tmp_path: Path) -> None:
    producer_v1 = tmp_path / "producer-v1.mdl"
    producer_v1.write_text(PRODUCER_V1.strip() + "\n", encoding="utf-8")
    producer_v2 = tmp_path / "producer-v2.mdl"
    producer_v2.write_text(PRODUCER_V2.strip() + "\n", encoding="utf-8")
    consumer = tmp_path / "consumer.mdl"
    consumer.write_text(CONSUMER.strip() + "\n", encoding="utf-8")
    snapshot = tmp_path / ".modelable"
    runner = CliRunner()

    resolved = runner.invoke(cli, ["registry", "resolve", str(producer_v1), "--out", str(snapshot)])
    assert resolved.exit_code == 0, resolved.output

    diff = runner.invoke(
        cli,
        ["registry", "diff", str(producer_v2), "--out", str(snapshot), "--format", "json"],
    )
    assert diff.exit_code == 0, diff.output
    assert "customer.Customer@2 (model)" in json.loads(diff.output)["added"]

    for target in list_implemented_codegen_targets():
        output = tmp_path / "generated" / target.name
        compiled = runner.invoke(
            cli,
            [
                "compile",
                str(consumer),
                "--target",
                target.name,
                "--snapshot",
                str(snapshot),
                "--out",
                str(output),
            ],
        )
        assert compiled.exit_code == 0, f"{target.name}: {compiled.output}"
        assert any(output.rglob("*")), f"{target.name} emitted no artifacts"
