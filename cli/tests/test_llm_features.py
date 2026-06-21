from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from modelable.cli import cli
from modelable.compiler.workspace import load_workspace
from modelable.llm.config import resolve_llm_config
from modelable.llm.context import (
    build_model_summary,
    build_projection_summary,
    build_workspace_summary,
)
from modelable.llm.importers import import_from_text
from modelable.llm.redaction import redact_sensitive_values
from modelable.parser.ir import AiConfig


def _read_provenance(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _provenance_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.provenance.json")


def test_redaction_masks_secrets():
    text = "token=abc123 password=secret api_key: supersecret"
    redacted = redact_sensitive_values(text)
    assert "[REDACTED]" in redacted
    assert "abc123" not in redacted
    assert "secret" not in redacted


def test_model_config_resolution_order():
    workspace = type(
        "WorkspaceLike", (), {"ai": AiConfig(provider="anthropic", model="workspace-model", repair_attempts=2)}
    )()
    config = resolve_llm_config(flag_model="flag-model", workspace=workspace, env={"MODELABLE_LLM_MODEL": "env-model"})
    assert config.model == "flag-model"
    assert config.source == "flag"

    config = resolve_llm_config(workspace=workspace, env={"MODELABLE_LLM_MODEL": "env-model"})
    assert config.model == "env-model"
    assert config.source == "environment"

    config = resolve_llm_config(workspace=workspace, env={})
    assert config.model == "workspace-model"
    assert config.source == "workspace"
    assert config.repair_attempts == 2

    config = resolve_llm_config(workspace=workspace, env={"MODELABLE_LLM_REPAIR_ATTEMPTS": "3"})
    assert config.repair_attempts == 3
    assert config.source == "environment"


def test_workspace_and_model_summaries(tmp_path):
    mdl = tmp_path / "customer.mdl"
    mdl.write_text(
        """
workspace default {
  ai {
    provider: "anthropic"
    model: "workspace-model"
    repair_attempts: 2
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
    assert workspace.mdl.workspace is not None
    assert workspace.mdl.workspace.ai is not None
    assert workspace.mdl.workspace.ai.repair_attempts == 2

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
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    name: string
  }
}

domain billing {
  owner: "test-team"
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


def test_json_schema_importer_preserves_modelable_extensions():
    imported = import_from_text(
        json.dumps(
            {
                "title": "FallbackTitle",
                "type": "object",
                "x-modelable": {
                    "domain": "customer",
                    "name": "Customer",
                    "version": 3,
                },
                "required": ["customerId", "email"],
                "properties": {
                    "customerId": {
                        "type": "string",
                        "format": "uuid",
                        "x-modelable-field": {"key": True},
                    },
                    "email": {
                        "type": "string",
                        "x-modelable-field": {"pii": True, "owner": "identity-team"},
                        "x-modelable-classification": "confidential",
                    },
                    "address": {
                        "type": "string",
                        "x-modelable-ref": "address.Address",
                    },
                },
            }
        ),
        "json-schema",
    )

    text = imported.to_mdl()
    assert "domain customer" in text
    assert "entity Customer @ 3 (additive)" in text
    assert "@key customerId: uuid" in text
    assert '@pii @classification("confidential") @owner("identity-team") email: string' in text
    assert "address?: ref<address.Address>" in text


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


def test_dbt_importer_maps_columns_and_meta():
    imported = import_from_text(
        """
version: 2
models:
  - name: Customer
    columns:
      - name: customerId
        data_type: text
        constraints:
          - type: primary_key
      - name: email
        data_type: text
        constraints:
          - type: not_null
        meta:
          modelable_pii: true
          modelable_classification: restricted
      - name: loyaltyTier
        data_type: text
""",
        "dbt",
        domain_name="customer",
    )
    text = imported.to_mdl()
    assert "domain customer" in text
    assert "entity Customer @ 1 (additive)" in text
    assert "@key customerId: string" in text
    assert '@pii @classification("restricted") email: string' in text
    assert "loyaltyTier?: string" in text


def test_dbt_importer_selects_named_model():
    source = """
version: 2
models:
  - name: Customer
    columns:
      - name: customerId
        data_type: text
  - name: Order
    columns:
      - name: orderId
        data_type: text
"""
    imported = import_from_text(source, "dbt", domain_name="orders", source_name="Order")
    text = imported.to_mdl()
    assert "entity Order @ 1 (additive)" in text
    assert "orderId?: string" in text


def test_dbt_importer_bootstraps_source_table():
    imported = import_from_text(
        """
version: 2
sources:
  - name: raw_customer
    tables:
      - name: customers
        columns:
          - name: customerId
            data_type: text
            constraints:
              - type: primary_key
          - name: email
            data_type: text
            meta:
              modelable_pii: true
""",
        "dbt",
        domain_name="customer",
        source_name="customers",
    )

    text = imported.to_mdl()
    assert "domain customer" in text
    assert "entity Customers @ 1 (additive)" in text
    assert "@key customerId: string" in text
    assert "@pii email?: string" in text


def test_dbt_importer_bootstraps_manifest_source_table():
    source = {
        "nodes": {},
        "sources": {
            "source.raw_customer.customers": {
                "name": "customers",
                "resource_type": "source",
                "columns": {
                    "customerId": {
                        "data_type": "text",
                        "constraints": [{"type": "primary_key"}],
                    },
                    "email": {
                        "data_type": "text",
                        "meta": {"modelable_pii": True},
                    },
                },
            }
        },
    }

    imported = import_from_text(
        json.dumps(source),
        "dbt",
        domain_name="customer",
        source_name="customers",
    )

    text = imported.to_mdl()
    assert "domain customer" in text
    assert "entity Customers @ 1 (additive)" in text
    assert "@key customerId: string" in text
    assert "@pii email?: string" in text


def test_dbt_importer_preserves_data_tests_and_unique_key_config():
    imported = import_from_text(
        """
version: 2
models:
  - name: Customer
    config:
      unique_key: customerId
    columns:
      - name: customerId
        data_type: text
        data_tests:
          - unique
          - not_null
      - name: email
        data_type: text
        tests:
          - not_null
      - name: loyaltyTier
        data_type: text
        data_tests:
          - unique
""",
        "dbt",
        domain_name="customer",
    )

    text = imported.to_mdl()
    assert "@key customerId: string" in text
    assert "email: string" in text
    assert "loyaltyTier?: string" in text


def test_dbt_manifest_importer_preserves_data_tests_and_unique_key_config():
    source = {
        "nodes": {
            "model.shop.Customer": {
                "name": "Customer",
                "resource_type": "model",
                "config": {"unique_key": ["customerId"]},
                "columns": {
                    "customerId": {
                        "data_type": "text",
                        "data_tests": ["unique", "not_null"],
                    },
                    "email": {
                        "data_type": "text",
                        "tests": ["not_null"],
                    },
                    "loyaltyTier": {
                        "data_type": "text",
                        "data_tests": ["unique"],
                    },
                },
            }
        }
    }

    imported = import_from_text(json.dumps(source), "dbt", domain_name="customer", source_name="Customer")

    text = imported.to_mdl()
    assert "@key customerId: string" in text
    assert "email: string" in text
    assert "loyaltyTier?: string" in text


def test_dbt_importer_selects_latest_model_version():
    imported = import_from_text(
        """
version: 2
models:
  - name: Customer
    latest_version: 2
    columns:
      - name: customerId
        data_type: text
        constraints:
          - type: primary_key
      - name: email
        data_type: text
    versions:
      - v: 1
        columns:
          - name: customerId
            data_type: text
            constraints:
              - type: primary_key
          - name: email
            data_type: text
      - v: 2
        columns:
          - name: customerId
            data_type: text
            constraints:
              - type: primary_key
          - name: email
            data_type: text
          - name: loyaltyTier
            data_type: text
""",
        "dbt",
        domain_name="customer",
        source_name="Customer",
    )

    text = imported.to_mdl()
    assert "entity Customer @ 2 (additive)" in text
    assert "@key customerId: string" in text
    assert "email?: string" in text
    assert "loyaltyTier?: string" in text


def test_dbt_importer_selects_named_model_version():
    imported = import_from_text(
        """
version: 2
models:
  - name: Customer
    latest_version: 2
    columns:
      - name: customerId
        data_type: text
    versions:
      - v: 1
        columns:
          - name: customerId
            data_type: text
          - name: email
            data_type: text
      - v: 2
        columns:
          - name: customerId
            data_type: text
          - name: email
            data_type: text
          - name: loyaltyTier
            data_type: text
""",
        "dbt",
        domain_name="customer",
        source_name="Customer@1",
    )

    text = imported.to_mdl()
    assert "entity Customer @ 1 (additive)" in text
    assert "email?: string" in text
    assert "loyaltyTier" not in text


def test_dbt_manifest_importer_selects_latest_model_version():
    source = {
        "nodes": {
            "model.shop.Customer.v1": {
                "name": "Customer",
                "resource_type": "model",
                "version": 1,
                "latest_version": 2,
                "columns": {
                    "customerId": {"data_type": "text"},
                    "email": {"data_type": "text"},
                },
            },
            "model.shop.Customer.v2": {
                "name": "Customer",
                "resource_type": "model",
                "version": 2,
                "latest_version": 2,
                "columns": {
                    "customerId": {"data_type": "text"},
                    "email": {"data_type": "text"},
                    "loyaltyTier": {"data_type": "text"},
                },
            },
        }
    }

    imported = import_from_text(json.dumps(source), "dbt", domain_name="customer", source_name="Customer")

    text = imported.to_mdl()
    assert "entity Customer @ 2 (additive)" in text
    assert "loyaltyTier?: string" in text


def test_cli_generate_auto_detects_odcs_yaml(tmp_path):
    contract = tmp_path / "customer_contract.yml"
    contract.write_text(
        """
apiVersion: v3.0.2
kind: DataContract
name: customer-contract
schema:
  - name: Customer
    properties:
      - name: customerId
        logicalType: string
        primaryKey: true
      - name: email
        logicalType: string
        pii: true
        required: true
""",
        encoding="utf-8",
    )

    runner = CliRunner()
    output = tmp_path / "customer.mdl"
    result = runner.invoke(cli, ["generate", "--from", str(contract), "--domain", "customer", "--output", str(output)])

    assert result.exit_code == 0, result.output
    assert "format=odcs" in result.output
    generated = output.read_text(encoding="utf-8")
    assert "domain customer" in generated
    assert "entity Customer @ 1 (additive)" in generated
    assert "@key customerId: string" in generated
    assert "@pii email: string" in generated


def test_odcs_importer_preserves_classification_metadata_without_type():
    imported = import_from_text(
        """
apiVersion: v3.0.2
kind: DataContract
name: customer-contract
schema:
  - name: Customer
    properties:
      - name: email
        classification: restricted
        personalData: true
""",
        "odcs",
        domain_name="customer",
    )

    text = imported.to_mdl()
    assert '@pii @classification("restricted") email?: string' in text


def test_odcs_importer_respects_false_boolean_flags():
    imported = import_from_text(
        """
apiVersion: v3.0.2
kind: DataContract
name: customer-contract
schema:
  - name: Customer
    properties:
      - name: email
        logicalType: string
        required: "false"
        primaryKey: "false"
        personalData: "false"
""",
        "odcs",
        domain_name="customer",
    )

    text = imported.to_mdl()
    assert "email?: string" in text
    assert "@key" not in text
    assert "@pii" not in text


def test_odcs_importer_preserves_modelable_custom_properties():
    imported = import_from_text(
        """
apiVersion: v3.1.0
kind: DataContract
name: customer.Customer.v2
version: "2"
domain: customer
schema:
  - name: Customer
    properties:
      - name: customerId
        logicalType: string
        required: true
        primaryKey: true
        customProperties:
          - property: modelableType
            value: uuid
      - name: email
        logicalType: string
        required: true
        classification: confidential
        customProperties:
          - property: modelablePii
            value: true
          - property: modelableOwner
            value: identity-team
      - name: status
        logicalType: string
        customProperties:
          - property: modelableType
            value: enum(active,blocked)
          - property: modelableEnum
            value:
              - active
              - blocked
      - name: accountIds
        logicalType: array
        customProperties:
          - property: modelableType
            value: array<ref<Account>>
      - name: lifetimeValue
        logicalType: number
        customProperties:
          - property: modelableType
            value: decimal(12,2)
""",
        "odcs",
        domain_name="customer",
    )

    text = imported.to_mdl()
    assert "entity Customer @ 2 (additive)" in text
    assert "@key customerId: uuid" in text
    assert '@pii @classification("confidential") @owner("identity-team") email: string' in text
    assert "status?: enum(active, blocked)" in text
    assert "accountIds?: array<ref<Account>>" in text
    assert "lifetimeValue?: decimal(12, 2)" in text


def test_fhir_importer_maps_elements_to_fields():
    source = json.dumps(
        {
            "resourceType": "StructureDefinition",
            "name": "Patient",
            "type": "Patient",
            "snapshot": {
                "element": [
                    {"path": "Patient", "min": 0, "max": "*"},
                    {"path": "Patient.id", "min": 0, "max": "1", "type": [{"code": "id"}]},
                    {"path": "Patient.active", "min": 0, "max": "1", "type": [{"code": "boolean"}]},
                    {"path": "Patient.birthDate", "min": 0, "max": "1", "type": [{"code": "date"}]},
                    {
                        "path": "Patient.managingOrganization",
                        "min": 0,
                        "max": "1",
                        "type": [
                            {
                                "code": "Reference",
                                "targetProfile": ["http://hl7.org/fhir/StructureDefinition/Organization"],
                            }
                        ],
                    },
                    {"path": "Patient.name", "min": 0, "max": "*", "type": [{"code": "HumanName"}]},
                ]
            },
        }
    )
    imported = import_from_text(source, "fhir", domain_name="clinical")
    text = imported.to_mdl()
    assert "domain clinical" in text
    assert "entity Patient @ 1 (additive)" in text
    assert "@key id?: string" in text
    assert "active?: bool" in text
    assert "birthDate?: date" in text
    assert "managingOrganization?: ref<Organization>" in text
    assert "name?: array<HumanName>" in text
    assert any("HumanName" in warning for warning in imported.warnings)


def test_fhir_importer_names_extension_slices_from_slice_name():
    source = json.dumps(
        {
            "resourceType": "StructureDefinition",
            "name": "Patient",
            "type": "Patient",
            "snapshot": {
                "element": [
                    {"path": "Patient", "min": 0, "max": "*"},
                    {
                        "path": "Patient.extension",
                        "sliceName": "race",
                        "min": 0,
                        "max": "*",
                        "type": [
                            {
                                "code": "Extension",
                                "profile": ["http://hl7.org/fhir/us/core/StructureDefinition/us-core-race"],
                            }
                        ],
                    },
                ]
            },
        }
    )

    imported = import_from_text(source, "fhir", domain_name="clinical")

    text = imported.to_mdl()
    assert "race?: array<Extension>" in text
    assert "extension?: array<Extension>" not in text
    assert any("us-core-race" in warning for warning in imported.warnings)


def test_fhir_importer_uses_simple_extension_value_type():
    source = json.dumps(
        {
            "resourceType": "StructureDefinition",
            "name": "Patient",
            "type": "Patient",
            "snapshot": {
                "element": [
                    {"path": "Patient", "min": 0, "max": "*"},
                    {
                        "id": "Patient.extension:birthSex",
                        "path": "Patient.extension",
                        "sliceName": "birthSex",
                        "min": 0,
                        "max": "1",
                        "type": [
                            {
                                "code": "Extension",
                                "profile": ["http://hl7.org/fhir/us/core/StructureDefinition/us-core-birthsex"],
                            }
                        ],
                    },
                    {
                        "id": "Patient.extension:birthSex.value[x]",
                        "path": "Patient.extension.value[x]",
                        "min": 1,
                        "max": "1",
                        "type": [{"code": "code"}],
                    },
                ]
            },
        }
    )

    imported = import_from_text(source, "fhir", domain_name="clinical")

    text = imported.to_mdl()
    assert "birthSex?: string" in text
    assert "birthSex?: Extension" not in text
    assert any("us-core-birthsex" in warning for warning in imported.warnings)


def test_fhir_importer_preserves_repeating_simple_extension_value_type():
    source = json.dumps(
        {
            "resourceType": "StructureDefinition",
            "name": "Patient",
            "type": "Patient",
            "snapshot": {
                "element": [
                    {"path": "Patient", "min": 0, "max": "*"},
                    {
                        "id": "Patient.extension:nationality",
                        "path": "Patient.extension",
                        "sliceName": "nationality",
                        "min": 0,
                        "max": "*",
                        "type": [{"code": "Extension"}],
                    },
                    {
                        "id": "Patient.extension:nationality.value[x]",
                        "path": "Patient.extension.value[x]",
                        "min": 1,
                        "max": "1",
                        "type": [{"code": "string"}],
                    },
                ]
            },
        }
    )

    imported = import_from_text(source, "fhir", domain_name="clinical")

    text = imported.to_mdl()
    assert "nationality?: array<string>" in text
    assert "nationality?: array<Extension>" not in text


def test_fhir_importer_names_direct_slices_from_slice_name():
    source = json.dumps(
        {
            "resourceType": "StructureDefinition",
            "name": "Patient",
            "type": "Patient",
            "snapshot": {
                "element": [
                    {"path": "Patient", "min": 0, "max": "*"},
                    {
                        "path": "Patient.identifier",
                        "sliceName": "medicalRecordNumber",
                        "min": 0,
                        "max": "*",
                        "type": [{"code": "Identifier"}],
                    },
                ]
            },
        }
    )

    imported = import_from_text(source, "fhir", domain_name="clinical")

    text = imported.to_mdl()
    assert "medicalRecordNumber?: array<Identifier>" in text
    assert "identifier?: array<Identifier>" not in text
    assert any("medicalRecordNumber" in warning for warning in imported.warnings)


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

    result = runner.invoke(
        cli, ["recommend", "--path", str(tmp_path), "--ref", "customer.Customer@1", "--consumer", "billing"]
    )
    assert result.exit_code == 0
    assert "billing" in result.output

    output = tmp_path / "generated.mdl"
    result = runner.invoke(cli, ["generate", "--from", "customer lifecycle data", "--output", str(output)])
    assert result.exit_code == 0
    assert output.exists()
    provenance = _read_provenance(_provenance_path(output))
    assert provenance["command"] == "generate"
    assert provenance["artifact_path"] == str(output)
    assert provenance["inputs"]["source"] == "prompt"
    assert "audit:" in result.output
    assert "provider: local" in result.output
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
    result = runner.invoke(
        cli, ["import", str(schema), "--format", "json-schema", "--domain", "customer", "--output", str(imported)]
    )
    assert result.exit_code == 0
    assert imported.exists()
    provenance = _read_provenance(_provenance_path(imported))
    assert provenance["command"] == "import"
    assert provenance["inputs"]["format"] == "json-schema"
    assert provenance["inputs"]["domain"] == "customer"
    assert "audit:" in result.output
    assert "provider: local" in result.output
    assert "entity Customer @ 1" in imported.read_text(encoding="utf-8")

    projection = tmp_path / "projection.mdl"
    result = runner.invoke(
        cli,
        [
            "suggest-projection",
            "--path",
            str(tmp_path),
            "--source",
            "customer.Customer@1",
            "--consumer",
            "billing",
            "--output",
            str(projection),
        ],
    )
    assert result.exit_code == 0
    assert projection.exists()
    provenance = _read_provenance(_provenance_path(projection))
    assert provenance["command"] == "suggest-projection"
    assert provenance["inputs"]["consumer"] == "billing"
    assert "audit:" in result.output
    assert "provider: local" in result.output
    assert "projection CustomerView @ 1" in projection.read_text(encoding="utf-8")


def test_cli_suggest_projection_validates_generated_output(tmp_path, monkeypatch):
    from modelable.commands import llm as llm_commands

    mdl = tmp_path / "workspace.mdl"
    mdl.write_text(
        """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    name: string
  }
}
""",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        llm_commands,
        "suggest_projection",
        lambda *_args, **_kwargs: """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    name: string
  }
}
""".strip(),
    )
    runner = CliRunner()
    projection = tmp_path / "projection.mdl"
    result = runner.invoke(
        cli,
        [
            "suggest-projection",
            "--path",
            str(tmp_path),
            "--source",
            "customer.Customer@1",
            "--consumer",
            "billing",
            "--output",
            str(projection),
        ],
    )
    assert result.exit_code != 0
    assert "suggested projection failed validation" in result.output
    assert not projection.exists()
    assert not _provenance_path(projection).exists()


def test_cli_suggest_projection_reports_parse_errors(tmp_path, monkeypatch):
    from modelable.commands import llm as llm_commands

    mdl = tmp_path / "workspace.mdl"
    mdl.write_text(
        """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    name: string
  }
}
""",
        encoding="utf-8",
    )

    monkeypatch.setattr(llm_commands, "suggest_projection", lambda *_args, **_kwargs: "not valid mdl")
    runner = CliRunner()
    projection = tmp_path / "projection.mdl"
    result = runner.invoke(
        cli,
        [
            "suggest-projection",
            "--path",
            str(tmp_path),
            "--source",
            "customer.Customer@1",
            "--consumer",
            "billing",
            "--output",
            str(projection),
        ],
    )
    assert result.exit_code != 0
    assert "invalid syntax" in result.output or "No terminal matches" in result.output
    assert not projection.exists()
    assert not _provenance_path(projection).exists()


def test_cli_update_model_field(tmp_path):
    mdl = tmp_path / "workspace.mdl"
    mdl.write_text(
        """
domain customer {
  owner: "test-team"
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
    assert "audit:" in result.output
    assert "provider: local" in result.output
    assert "model: modelable-local" in result.output
    provenance = _read_provenance(_provenance_path(mdl))
    assert provenance["command"] == "update"
    assert provenance["inputs"]["ref"] == "customer.Customer@1"
    updated = mdl.read_text(encoding="utf-8")
    assert "email?: string" in updated
    assert "loyaltyTier: string" in updated


def test_cli_update_preview_shows_diff_without_writing(tmp_path):
    mdl = tmp_path / "workspace.mdl"
    original = """
domain customer {
  owner: "test-team"
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
    assert not _provenance_path(mdl).exists()


def test_cli_update_projection_field(tmp_path):
    mdl = tmp_path / "workspace.mdl"
    mdl.write_text(
        """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    name: string
  }
}

domain billing {
  owner: "test-team"
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
    provenance = _read_provenance(_provenance_path(mdl))
    assert provenance["command"] == "update"
    updated = mdl.read_text(encoding="utf-8")
    assert "displayName <- c.name" in updated
    assert "status <- c.name" in updated


def _attachments_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.attachments.json")


def test_cli_attach_dbt_creates_breaking_version(tmp_path):
    mdl = tmp_path / "workspace.mdl"
    mdl.write_text(
        """
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    @pii email: string
    name: string
  }
}
""",
        encoding="utf-8",
    )

    schema = tmp_path / "customer_schema.yml"
    schema.write_text(
        """
version: 2
models:
  - name: Customer
    columns:
      - name: customerId
        data_type: text
        constraints:
          - type: primary_key
      - name: email
        data_type: text
        meta:
          modelable_pii: true
        constraints:
          - type: not_null
      - name: name
        data_type: text
        constraints:
          - type: not_null
      - name: loyaltyTier
        data_type: text
""",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "attach",
            "customer.Customer@1",
            "--source",
            str(schema),
            "--source-format",
            "dbt",
            "--source-name",
            "Customer",
            "--path",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    updated = mdl.read_text(encoding="utf-8")
    assert "entity Customer @ 1 (additive)" in updated
    assert "entity Customer @ 2 (breaking)" in updated
    assert "@key customerId: string" in updated
    assert "loyaltyTier?: string" in updated
    assert "new version 2 (breaking)" in " ".join(result.output.split())

    attachments = json.loads(_attachments_path(mdl).read_text(encoding="utf-8"))
    assert len(attachments) == 1
    record = attachments[0]
    assert record["ref"] == "customer.Customer@1"
    assert record["source_format"] == "dbt"
    assert record["source_name"] == "Customer"
    assert record["from_version"] == 1
    assert record["to_version"] == 2
    assert record["change_kind"] == "breaking"
    change_kinds = {change["kind"] for change in record["changes"]}
    assert "type_changed" in change_kinds
    assert "added_field" in change_kinds


def test_cli_attach_no_diff_skips_new_version(tmp_path):
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

    schema = tmp_path / "customer_schema.yml"
    schema.write_text(
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
    result = runner.invoke(
        cli,
        [
            "attach",
            "customer.Customer@1",
            "--source",
            str(schema),
            "--source-format",
            "dbt",
            "--source-name",
            "Customer",
            "--path",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "no new version created" in " ".join(result.output.split())
    assert mdl.read_text(encoding="utf-8").count("entity Customer @") == 1
    assert not _attachments_path(mdl).exists()


def test_cli_attach_preview_does_not_write(tmp_path):
    mdl = tmp_path / "workspace.mdl"
    original = """
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    @key customerId: string
    name: string
  }
}
"""
    mdl.write_text(original, encoding="utf-8")

    schema = tmp_path / "customer_schema.yml"
    schema.write_text(
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
      - name: phone
        data_type: text
""",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "attach",
            "customer.Customer@1",
            "--source",
            str(schema),
            "--source-format",
            "dbt",
            "--source-name",
            "Customer",
            "--path",
            str(tmp_path),
            "--preview",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "@@" in result.output
    assert "entity Customer @ 2 (additive)" in result.output
    assert mdl.read_text(encoding="utf-8") == original
    assert not _attachments_path(mdl).exists()


_TRANSFORM_MDL = """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    name: string
  }
}
"""

_TRANSFORM_REF = "customer.Customer@1"


def _transform_tmp(tmp_path):
    (tmp_path / "customer.mdl").write_text(_TRANSFORM_MDL, encoding="utf-8")
    return tmp_path


def test_transform_csharp(tmp_path):
    from modelable.llm.engine import transform_ref_to_target

    result = transform_ref_to_target(_transform_tmp(tmp_path), _TRANSFORM_REF, "csharp")
    assert "Customer" in result.content
    assert "customerId" in result.content.lower() or "CustomerId" in result.content


def test_transform_java(tmp_path):
    from modelable.llm.engine import transform_ref_to_target

    result = transform_ref_to_target(_transform_tmp(tmp_path), _TRANSFORM_REF, "java")
    assert "Customer" in result.content


def test_transform_python(tmp_path):
    from modelable.llm.engine import transform_ref_to_target

    result = transform_ref_to_target(_transform_tmp(tmp_path), _TRANSFORM_REF, "python")
    assert "Customer" in result.content


def test_transform_rust(tmp_path):
    from modelable.llm.engine import transform_ref_to_target

    result = transform_ref_to_target(_transform_tmp(tmp_path), _TRANSFORM_REF, "rust")
    assert "Customer" in result.content


def test_transform_go(tmp_path):
    from modelable.llm.engine import transform_ref_to_target

    result = transform_ref_to_target(_transform_tmp(tmp_path), _TRANSFORM_REF, "go")
    assert "Customer" in result.content


def test_transform_cli_csharp(tmp_path):
    _transform_tmp(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["transform", _TRANSFORM_REF, "--to", "csharp", "--path", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "Customer" in result.output


def test_transform_cli_writes_audit_summary(tmp_path):
    _transform_tmp(tmp_path)
    runner = CliRunner()
    output = tmp_path / "customer.cs"
    result = runner.invoke(
        cli,
        [
            "transform",
            _TRANSFORM_REF,
            "--to",
            "csharp",
            "--path",
            str(tmp_path),
            "--out",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    assert output.exists()
    provenance = _read_provenance(_provenance_path(output))
    assert provenance["command"] == "transform"
    assert provenance["inputs"]["target"] == "csharp"
    assert "audit:" in result.output
    assert "provider: local" in result.output
    assert "Customer" in result.output


def test_transform_cli_explain(tmp_path):
    _transform_tmp(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "transform",
            _TRANSFORM_REF,
            "--to",
            "typescript",
            "--path",
            str(tmp_path),
            "--explain",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Explanation:" in result.output
    assert "typescript" in result.output
    assert "Customer" in result.output


_TRANSFORM_MDL_WITH_PROJECTION = """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    name: string
  }

  projection CustomerView @ 1
    from customer.Customer @ 1 as c
  {
    customerId <- c.customerId
    name <- c.name
  }
}
"""

_TRANSFORM_PROJECTION_REF = "customer.CustomerView@1"


def _transform_projection_tmp(tmp_path):
    (tmp_path / "customer.mdl").write_text(_TRANSFORM_MDL_WITH_PROJECTION, encoding="utf-8")
    return tmp_path


def test_transform_projection_ref_typescript(tmp_path):
    from modelable.llm.engine import transform_ref_to_target

    result = transform_ref_to_target(_transform_projection_tmp(tmp_path), _TRANSFORM_PROJECTION_REF, "typescript")
    assert "CustomerView" in result.content


def test_transform_projection_ref_csharp(tmp_path):
    from modelable.llm.engine import transform_ref_to_target

    result = transform_ref_to_target(_transform_projection_tmp(tmp_path), _TRANSFORM_PROJECTION_REF, "csharp")
    assert "CustomerView" in result.content


def test_transform_projection_ref_json_schema(tmp_path):
    import os

    os.chdir(tmp_path)
    from modelable.llm.engine import transform_ref_to_target

    result = transform_ref_to_target(_transform_projection_tmp(tmp_path), _TRANSFORM_PROJECTION_REF, "json-schema")
    assert "CustomerView" in result.content or "customerView" in result.content.lower()


def test_chat_ask_slash_command_uses_provider_when_configured(tmp_path):
    """'/ask' inside chat must route through the LLM provider, not the heuristic fallback."""
    from dataclasses import dataclass

    from modelable.compiler.workspace import load_workspace
    from modelable.llm.chat import ChatState, chat_turn
    from modelable.llm.providers import LLMRequest, LLMResponse

    mdl = tmp_path / "workspace.mdl"
    mdl.write_text(
        """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    email?: string
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)

    calls: list[LLMRequest] = []

    @dataclass(frozen=True)
    class CapturingProvider:
        def complete(self, req: LLMRequest) -> LLMResponse:
            calls.append(req)
            return LLMResponse(content="captured", provider="test", model="test")

    state = ChatState()
    chat_turn(
        workspace, "/ask what fields does Customer have?", path=tmp_path, state=state, provider=CapturingProvider()
    )

    assert calls, "/ask should have called the LLM provider, but provider was never invoked"


def test_chat_ask_slash_command_falls_back_to_heuristic_when_no_provider(tmp_path):
    from modelable.compiler.workspace import load_workspace
    from modelable.llm.chat import ChatState, chat_turn

    mdl = tmp_path / "workspace.mdl"
    mdl.write_text(
        """
domain customer {
  owner: "data-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    state = ChatState()
    response = chat_turn(workspace, "/ask Who owns customer.Customer@1?", path=tmp_path, state=state, provider=None)
    assert "data-team" in response


def test_transform_unknown_ref_raises(tmp_path):
    import pytest

    from modelable.llm.engine import transform_ref_to_target

    _transform_tmp(tmp_path)
    with pytest.raises(ValueError, match="Unknown model or projection"):
        transform_ref_to_target(tmp_path, "customer.NoSuch@1", "typescript")
