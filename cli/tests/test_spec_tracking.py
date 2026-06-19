from __future__ import annotations

import json
from pathlib import Path

import yaml
from click.testing import CliRunner

from modelable.cli import cli


def _write_customer_workspace(tmp_path: Path) -> Path:
    mdl = tmp_path / "workspace.mdl"
    mdl.write_text(
        """
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    @key customerId: string
    name: string
  }
}
""",
        encoding="utf-8",
    )
    return mdl


def test_spec_add_writes_source_controlled_config(tmp_path: Path) -> None:
    _write_customer_workspace(tmp_path)
    source = tmp_path / "customer_schema.yml"
    source.write_text(
        """
version: 2
models:
  - name: Customer
    columns:
      - name: customerId
        data_type: text
        constraints:
          - type: primary_key
      - name: name
        data_type: text
        constraints:
          - type: not_null
""",
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli,
        [
            "spec",
            "add",
            "customer-dbt",
            "--kind",
            "dbt",
            "--source",
            str(source),
            "--ref",
            "customer.Customer@1",
            "--source-name",
            "Customer",
            "--path",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.output
    config_path = tmp_path / ".modelable" / "specs.yml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert config == {
        "specs": [
            {
                "id": "customer-dbt",
                "kind": "dbt",
                "source": str(source),
                "ref": "customer.Customer@1",
                "source_name": "Customer",
                "update_policy": "preview",
            }
        ]
    }


def test_spec_status_reports_clean_and_drifted_specs(tmp_path: Path) -> None:
    _write_customer_workspace(tmp_path)
    source = tmp_path / "customer_schema.yml"
    source.write_text(
        """
version: 2
models:
  - name: Customer
    columns:
      - name: customerId
        data_type: text
        constraints:
          - type: primary_key
      - name: name
        data_type: text
        constraints:
          - type: not_null
""",
        encoding="utf-8",
    )
    runner = CliRunner()
    add = runner.invoke(
        cli,
        [
            "spec",
            "add",
            "customer-dbt",
            "--kind",
            "dbt",
            "--source",
            str(source),
            "--ref",
            "customer.Customer@1",
            "--source-name",
            "Customer",
            "--path",
            str(tmp_path),
        ],
    )
    assert add.exit_code == 0, add.output

    clean = runner.invoke(cli, ["spec", "status", "--path", str(tmp_path), "--json"])
    assert clean.exit_code == 0, clean.output
    payload = json.loads(clean.output)
    assert payload["specs"][0]["status"] == "clean"
    assert payload["specs"][0]["change_kind"] is None

    source.write_text(
        """
version: 2
models:
  - name: Customer
    columns:
      - name: customerId
        data_type: text
        constraints:
          - type: primary_key
      - name: name
        data_type: text
        constraints:
          - type: not_null
      - name: email
        data_type: text
""",
        encoding="utf-8",
    )

    drifted = runner.invoke(cli, ["spec", "status", "--path", str(tmp_path), "--json"])
    assert drifted.exit_code == 0, drifted.output
    payload = json.loads(drifted.output)
    assert payload["specs"][0]["status"] == "drifted"
    assert payload["specs"][0]["change_kind"] == "additive"
    assert payload["specs"][0]["change_count"] == 1


def test_spec_sync_preview_does_not_write_and_write_records_attachment(tmp_path: Path) -> None:
    mdl = _write_customer_workspace(tmp_path)
    original = mdl.read_text(encoding="utf-8")
    source = tmp_path / "customer_schema.yml"
    source.write_text(
        """
version: 2
models:
  - name: Customer
    columns:
      - name: customerId
        data_type: text
        constraints:
          - type: primary_key
      - name: name
        data_type: text
        constraints:
          - type: not_null
      - name: email
        data_type: text
""",
        encoding="utf-8",
    )
    runner = CliRunner()
    add = runner.invoke(
        cli,
        [
            "spec",
            "add",
            "customer-dbt",
            "--kind",
            "dbt",
            "--source",
            str(source),
            "--ref",
            "customer.Customer@1",
            "--source-name",
            "Customer",
            "--path",
            str(tmp_path),
        ],
    )
    assert add.exit_code == 0, add.output

    preview = runner.invoke(cli, ["spec", "sync", "customer-dbt", "--path", str(tmp_path), "--preview"])
    assert preview.exit_code == 0, preview.output
    assert "entity Customer @ 2 (additive)" in preview.output
    assert mdl.read_text(encoding="utf-8") == original

    write = runner.invoke(cli, ["spec", "sync", "customer-dbt", "--path", str(tmp_path), "--write"])
    assert write.exit_code == 0, write.output
    assert "new version 2 (additive)" in " ".join(write.output.split())
    assert "entity Customer @ 2 (additive)" in mdl.read_text(encoding="utf-8")
    attachments = json.loads((tmp_path / "workspace.mdl.attachments.json").read_text(encoding="utf-8"))
    assert attachments[0]["spec_id"] == "customer-dbt"
    assert attachments[0]["source_format"] == "dbt"


def test_odcs_importer_is_available_for_tracked_specs(tmp_path: Path) -> None:
    _write_customer_workspace(tmp_path)
    source = tmp_path / "customer.contract.yaml"
    source.write_text(
        """
apiVersion: v3.1.0
kind: DataContract
id: customer-contract
schema:
  - name: Customer
    physicalName: customer
    properties:
      - name: customerId
        logicalType: string
        required: true
        primaryKey: true
      - name: name
        logicalType: string
        required: true
      - name: email
        logicalType: string
""",
        encoding="utf-8",
    )
    runner = CliRunner()
    add = runner.invoke(
        cli,
        [
            "spec",
            "add",
            "customer-odcs",
            "--kind",
            "odcs",
            "--source",
            str(source),
            "--ref",
            "customer.Customer@1",
            "--source-name",
            "Customer",
            "--path",
            str(tmp_path),
        ],
    )
    assert add.exit_code == 0, add.output

    status = runner.invoke(cli, ["spec", "status", "--path", str(tmp_path), "--json"])
    assert status.exit_code == 0, status.output
    payload = json.loads(status.output)
    assert payload["specs"][0]["status"] == "drifted"
    assert payload["specs"][0]["change_kind"] == "additive"


def test_cli_attach_accepts_odcs_sources(tmp_path: Path) -> None:
    mdl = _write_customer_workspace(tmp_path)
    source = tmp_path / "customer.contract.yaml"
    source.write_text(
        """
apiVersion: v3.1.0
kind: DataContract
id: customer-contract
schema:
  - name: Customer
    properties:
      - name: customerId
        logicalType: string
        required: true
        primaryKey: true
      - name: name
        logicalType: string
        required: true
      - name: email
        logicalType: string
""",
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli,
        [
            "attach",
            "customer.Customer@1",
            "--source",
            str(source),
            "--source-format",
            "odcs",
            "--source-name",
            "Customer",
            "--path",
            str(tmp_path),
            "--preview",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "entity Customer @ 2 (additive)" in result.output
    assert mdl.read_text(encoding="utf-8").count("entity Customer @") == 1
