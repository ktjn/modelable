from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from click.testing import CliRunner

from modelable.cli import cli
from modelable.emitters.targets import list_implemented_codegen_targets

RUST_FIXTURE = Path(__file__).parent / "fixtures" / "offline-rust-consumer"

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


def test_offline_feature_fixture_rust_consumer_runs_locked_offline(tmp_path: Path) -> None:
    producer = tmp_path / "producer.mdl"
    producer.write_text(PRODUCER_V1.strip() + "\n", encoding="utf-8")
    consumer = tmp_path / "consumer.mdl"
    consumer.write_text(CONSUMER.strip() + "\n", encoding="utf-8")
    snapshot = tmp_path / ".modelable"
    output = tmp_path / "generated" / "rust"
    runner = CliRunner()

    resolved = runner.invoke(cli, ["registry", "resolve", str(producer), "--out", str(snapshot)])
    assert resolved.exit_code == 0, resolved.output
    compiled = runner.invoke(
        cli,
        [
            "compile",
            str(consumer),
            "--target",
            "rust",
            "--snapshot",
            str(snapshot),
            "--out",
            str(output),
        ],
    )
    assert compiled.exit_code == 0, compiled.output

    _write_rust_consumer(tmp_path)
    result = subprocess.run(
        ["cargo", "test", "--quiet", "--locked", "--offline"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"cargo test failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"


def test_offline_feature_fixture_commands_use_snapshot_without_network(tmp_path: Path, monkeypatch) -> None:
    producer_v1 = tmp_path / "producer-v1.mdl"
    producer_v1.write_text(PRODUCER_V1.strip() + "\n", encoding="utf-8")
    producer_v2 = tmp_path / "producer-v2.mdl"
    producer_v2.write_text(PRODUCER_V2.strip() + "\n", encoding="utf-8")
    candidate_v2 = tmp_path / "candidate-v2.mdl"
    candidate_v2.write_text(
        PRODUCER_V2.replace(
            "  entity Customer @ 1 (additive) {\n    @key customerId: uuid\n    displayName: string\n  }\n",
            "",
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    consumer = tmp_path / "consumer.mdl"
    consumer.write_text(CONSUMER.strip() + "\n", encoding="utf-8")
    snapshot = tmp_path / ".modelable"
    runner = CliRunner()

    def forbidden_network_call(*_args, **_kwargs):
        raise AssertionError("offline feature qualification contacted the network")

    monkeypatch.setattr("urllib.request.urlopen", forbidden_network_call)
    resolved = runner.invoke(cli, ["registry", "resolve", str(producer_v1), "--out", str(snapshot)])
    assert resolved.exit_code == 0, resolved.output

    for arguments in (
        ["validate", str(producer_v1)],
        [
            "compile",
            str(consumer),
            "--target",
            "json-schema",
            "--snapshot",
            str(snapshot),
            "--out",
            str(tmp_path / "validated-artifacts"),
        ],
    ):
        result = runner.invoke(cli, arguments)
        assert result.exit_code == 0, f"{arguments}: {result.output}"

    diff = runner.invoke(
        cli,
        ["registry", "diff", str(producer_v2), "--out", str(snapshot), "--format", "json"],
    )
    assert diff.exit_code == 0, diff.output
    assert "customer.Customer@2 (model)" in json.loads(diff.output)["added"]

    impact = runner.invoke(
        cli,
        [
            "impact",
            "--from",
            "customer.Customer@1",
            "--to",
            "customer.Customer@2",
            "--path",
            str(candidate_v2),
            "--snapshot",
            str(snapshot),
            "--format",
            "json",
        ],
    )
    assert impact.exit_code == 0, impact.output
    assert json.loads(impact.output)["consequences"]

    rebuilt = runner.invoke(cli, ["registry", "rebuild-index", "--out", str(snapshot)])
    assert rebuilt.exit_code == 0, rebuilt.output
    assert (snapshot / "registry.db").exists()


def _write_rust_consumer(tmp_path: Path) -> None:
    shutil.copytree(RUST_FIXTURE, tmp_path, dirs_exist_ok=True)
    source = tmp_path / "src"
    source.mkdir()
    (source / "lib.rs").write_text(
        """
#[path = "../generated/rust/customer/customer_customer_v1.rs"]
mod customer;
#[path = "../generated/rust/analytics/analytics_customer_summary_v1.rs"]
mod analytics;

#[cfg(test)]
mod tests {
    use super::analytics::AnalyticsCustomerSummaryV1;
    use super::customer::CustomerCustomerV1;
    use uuid::Uuid;

    #[test]
    fn generated_contracts_compile_and_preserve_identity() {
        let id = Uuid::parse_str("123e4567-e89b-12d3-a456-426614174000").unwrap();
        let customer = CustomerCustomerV1 { customer_id: id, display_name: String::from("Alice") };
        let summary = AnalyticsCustomerSummaryV1 { customer_id: id, name: String::from("Alice") };

        assert_eq!(customer.customer_id, summary.customer_id);
        assert_eq!(CustomerCustomerV1::SCHEMA_VERSION, 1);
        assert_eq!(AnalyticsCustomerSummaryV1::SCHEMA_VERSION, 1);
        assert_eq!(CustomerCustomerV1::SCHEMA_CONTENT_SIGNATURE.len(), 32);
        assert_eq!(AnalyticsCustomerSummaryV1::SCHEMA_CONTENT_SIGNATURE.len(), 32);
    }
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
