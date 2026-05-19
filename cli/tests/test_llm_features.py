from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from modelable.cli import cli
from modelable.compiler.workspace import load_workspace
from modelable.parser.ir import AiConfig
from modelable.llm.config import resolve_llm_config
from modelable.llm.context import build_model_summary, build_projection_summary, build_workspace_summary
from modelable.llm.importers import import_from_text
from modelable.llm.redaction import redact_sensitive_values


def test_redaction_masks_secrets():
    text = "token=abc123 password=secret api_key: supersecret"
    redacted = redact_sensitive_values(text)
    assert "[REDACTED]" in redacted
    assert "abc123" not in redacted
    assert "secret" not in redacted


def test_model_config_resolution_order():
    workspace = type("WorkspaceLike", (), {"ai": AiConfig(provider="anthropic", model="workspace-model")})()
    config = resolve_llm_config(flag_model="flag-model", workspace=workspace, env={"MODELABLE_LLM_MODEL": "env-model"})
    assert config.model == "flag-model"
    assert config.source == "flag"

    config = resolve_llm_config(workspace=workspace, env={"MODELABLE_LLM_MODEL": "env-model"})
    assert config.model == "env-model"
    assert config.source == "environment"

    config = resolve_llm_config(workspace=workspace, env={})
    assert config.model == "workspace-model"
    assert config.source == "workspace"


def test_workspace_and_model_summaries(tmp_path):
    mdl = tmp_path / "customer.mdl"
    mdl.write_text(
        """
workspace default {
  ai {
    provider: "anthropic"
    model: "workspace-model"
  }
}

domain customer {
  owner: "customer-team"

  entity Customer @ 1 (additive) {
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

    summary = build_workspace_summary(workspace)
    assert "domain customer" in summary
    assert "entity Customer @ 1" in summary

    model_summary = build_model_summary(workspace, "customer.Customer@1")
    assert "kind: entity" in model_summary
    assert "customerId" in model_summary

    projection_summary = build_projection_summary(workspace, "customer.CustomerSummary@1")
    assert "source:" in projection_summary
    assert "customerId" in projection_summary


def test_workspace_summary_renders_pinned_versions(tmp_path):
    mdl = tmp_path / "workspace.mdl"
    mdl.write_text(
        """
domain customer {
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    name: string
  }
}

domain billing {
  projection BillingCustomer @ 1
    from customer.Customer @ 1#a3f8b2c1d4e5f6a7 as c
  {
    billingId <- c.customerId
  }
}
""",
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)
    summary = build_workspace_summary(workspace)

    assert "customer.Customer @ 1" in summary
    assert "customer.Customer @ 1#a3f8b2c1d4e5f6a7" in summary or "customer.Customer @ 1#a3f8b2c1d4e5f6a7" in summary


def test_json_schema_importer_round_trips_to_mdl():
    imported = import_from_text(
        json.dumps(
            {
                "title": "Customer",
                "type": "object",
                "required": ["customerId", "name"],
                "properties": {
                    "customerId": {"type": "string", "format": "uuid"},
                    "name": {"type": "string"},
                    "age": {"type": "integer"},
                },
            }
        ),
        "json-schema",
        domain_name="customer",
    )

    text = imported.to_mdl()
    assert "domain customer" in text
    assert "entity Customer @ 1 (additive)" in text
    assert "@key customerId: uuid" in text
    assert "age?: int" in text


def test_sql_importer_marks_primary_key():
    imported = import_from_text(
        """
CREATE TABLE customer.customer (
  customer_id UUID NOT NULL,
  name TEXT,
  PRIMARY KEY (customer_id)
);
""",
        "sql",
        domain_name="customer",
    )
    text = imported.to_mdl()
    assert "@key customer_id: uuid" in text
    assert "name?: string" in text


def test_cli_generate_describe_ask_and_recommend(tmp_path):
    mdl = tmp_path / "workspace.mdl"
    mdl.write_text(
        """
domain customer {
  owner: "customer-team"

  entity Customer @ 1 (additive) {
    @key customerId: uuid
    @pii
    email?: string
    name: string
  }
}
""",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["describe", "customer.Customer@1", "--path", str(tmp_path)])
    assert result.exit_code == 0
    assert "kind: entity" in result.output

    result = runner.invoke(cli, ["ask", "Who owns customer.Customer@1?", "--path", str(tmp_path)])
    assert result.exit_code == 0
    assert "customer-team" in result.output

    result = runner.invoke(cli, ["recommend", "--path", str(tmp_path), "--ref", "customer.Customer@1", "--consumer", "billing"])
    assert result.exit_code == 0
    assert "billing" in result.output

    output = tmp_path / "generated.mdl"
    result = runner.invoke(cli, ["generate", "--from", "customer lifecycle data", "--output", str(output)])
    assert result.exit_code == 0
    assert output.exists()
    assert "entity Customer @ 1" in output.read_text(encoding="utf-8")


def test_cli_import_and_suggest_projection(tmp_path):
    schema = tmp_path / "customer.json"
    schema.write_text(
        json.dumps(
            {
                "title": "Customer",
                "type": "object",
                "required": ["customerId", "name"],
                "properties": {
                    "customerId": {"type": "string", "format": "uuid"},
                    "name": {"type": "string"},
                    "email": {"type": "string"},
                },
            }
        ),
        encoding="utf-8",
    )

    runner = CliRunner()
    imported = tmp_path / "imported.mdl"
    result = runner.invoke(cli, ["import", str(schema), "--format", "json-schema", "--domain", "customer", "--output", str(imported)])
    assert result.exit_code == 0
    assert imported.exists()
    assert "entity Customer @ 1" in imported.read_text(encoding="utf-8")

    projection = tmp_path / "projection.mdl"
    result = runner.invoke(
        cli,
        ["suggest-projection", "--path", str(tmp_path), "--source", "customer.Customer@1", "--consumer", "billing", "--output", str(projection)],
    )
    assert result.exit_code == 0
    assert projection.exists()
    assert "projection CustomerView @ 1" in projection.read_text(encoding="utf-8")


def test_cli_update_model_field(tmp_path):
    mdl = tmp_path / "workspace.mdl"
    mdl.write_text(
        """
domain customer {
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    email: string
  }
}
""",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "update",
            "customer.Customer@1",
            "make email optional and add loyaltyTier as string",
            "--path",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    updated = mdl.read_text(encoding="utf-8")
    assert "email?: string" in updated
    assert "loyaltyTier: string" in updated


def test_cli_update_preview_shows_diff_without_writing(tmp_path):
    mdl = tmp_path / "workspace.mdl"
    original = """
domain customer {
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    email: string
  }
}
"""
    mdl.write_text(original, encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "update",
            "customer.Customer@1",
            "make email optional",
            "--path",
            str(tmp_path),
            "--preview",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "@@" in result.output
    assert "-    email: string" in result.output
    assert "+    email?: string" in result.output
    assert mdl.read_text(encoding="utf-8") == original


def test_cli_update_projection_field(tmp_path):
    mdl = tmp_path / "workspace.mdl"
    mdl.write_text(
        """
domain customer {
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    name: string
  }
}

domain billing {
  projection CustomerBrief @ 1
    from customer.Customer @ 1 as c
  {
    customerId <- c.customerId
    name <- c.name
  }
}
""",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "update",
            "billing.CustomerBrief@1",
            "rename name to displayName and add status from c.name",
            "--path",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    updated = mdl.read_text(encoding="utf-8")
    assert "displayName <- c.name" in updated
    assert "status <- c.name" in updated
