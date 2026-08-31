from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from modelable.cli import cli
from modelable.planner.protocol import PLAN_V1_SCHEMA, load_plan, migrate_plan, serialize_plan


def _fixture() -> Path:
    return Path(__file__).parent / "fixtures" / "plan_v0" / "billing.BillingCustomer.v1.plan.json"


def test_plan_validate_reports_valid_identity() -> None:
    result = CliRunner().invoke(cli, ["plan", "validate", str(_fixture())])

    assert result.exit_code == 0, result.output
    assert "valid: true" in result.output
    assert "schema: modelable.plan/v0" in result.output
    assert "identity: billing.BillingCustomer@1" in result.output


def test_plan_validate_json_format_is_canonical_serialization() -> None:
    result = CliRunner().invoke(cli, ["plan", "validate", str(_fixture()), "--format", "json"])

    assert result.exit_code == 0, result.output
    assert result.output == _fixture().read_text(encoding="utf-8")


def test_plan_validate_reports_protocol_errors(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.plan.json"
    invalid.write_text('{"$schema":"modelable.plan/v2"}', encoding="utf-8")

    result = CliRunner().invoke(cli, ["plan", "validate", str(invalid)])

    assert result.exit_code == 1
    assert "Error:" in result.output
    assert "unsupported plan schema 'modelable.plan/v2'" in result.output


def test_plan_migrate_emits_canonical_v1_json() -> None:
    result = CliRunner().invoke(cli, ["plan", "migrate", str(_fixture()), "--to", PLAN_V1_SCHEMA])

    assert result.exit_code == 0, result.output
    expected = serialize_plan(migrate_plan(load_plan(_fixture()), PLAN_V1_SCHEMA))
    assert result.output == expected


def test_plan_migrate_rejects_unsupported_target() -> None:
    result = CliRunner().invoke(cli, ["plan", "migrate", str(_fixture()), "--to", "modelable.plan/v2"])

    assert result.exit_code != 0
    assert "Invalid value for '--to'" in result.output
