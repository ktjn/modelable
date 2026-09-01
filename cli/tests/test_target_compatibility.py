from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from click.testing import CliRunner

from modelable.cli import cli
from modelable.compat.diff import compare_index_decls, compare_model_versions, compare_projection_versions
from modelable.compat.targets import (
    AXES,
    SEVERITIES,
    compare_avro_artifacts,
    compare_data_backfill,
    compare_event_sink_artifacts,
    compare_fhir_artifacts,
    compare_governance_review,
    compare_grpc_artifacts,
    compare_json_schema_artifacts,
    compare_model_storage_migration,
    compare_odcs_artifacts,
    compare_openapi_artifacts,
    compare_projection_rebuild,
    compare_protobuf_manifests,
    compare_semantic_compatibility,
    compare_source_representation,
    compare_sql_artifacts,
    compare_storage_migration,
)
from modelable.compiler.workspace import load_workspace
from modelable.consequence_protocol import validate_consequence_graph
from modelable.emitters.avro import emit_avro
from modelable.emitters.base import EmittedArtifact
from modelable.emitters.fhir import emit_fhir_profile
from modelable.emitters.grpc import emit_grpc
from modelable.emitters.json_schema import emit_json_schema
from modelable.emitters.openapi import emit_openapi
from modelable.emitters.protobuf import emit_protobuf
from modelable.emitters.sql import emit_sql
from modelable.parser.parse import parse_text_to_ir


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _openapi_artifacts(path: Path):
    return emit_openapi(load_workspace(path), path.parent / "out")


def _avro_artifacts(path: Path):
    return emit_avro(load_workspace(path), path.parent / "out")


def _json_schema_artifacts(path: Path):
    return emit_json_schema(load_workspace(path), path.parent / "out")


def _sql_artifacts(path: Path, dialect: str):
    return emit_sql(load_workspace(path), path.parent / "out", dialect)


def _fhir_artifacts(path: Path):
    return emit_fhir_profile(load_workspace(path), path.parent / "out")


def _synthetic_fhir_artifact(content: dict[str, Any], *, ref: str = "billing.CustomerView@1") -> EmittedArtifact:
    return EmittedArtifact(
        target="fhir-profile",
        ref=ref,
        artifact_id="billing.CustomerView.v1",
        path=Path("billing/CustomerView.v1.fhir.json"),
        content=json.dumps(content),
        content_hash="test",
    )


def _synthetic_odcs_artifact(content: dict[str, Any], *, ref: str = "billing.CustomerView@1") -> EmittedArtifact:
    return EmittedArtifact(
        target="odcs",
        ref=ref,
        artifact_id="billing.CustomerView.v1",
        path=Path("billing/CustomerView.v1.odcs.yaml"),
        content=yaml.safe_dump(content),
        content_hash="test",
    )


def _synthetic_sql_artifact(content: object, *, target: str = "sql-postgres") -> EmittedArtifact:
    return EmittedArtifact(
        target=target,
        ref="billing.CustomerView@1",
        artifact_id="billing.CustomerView.v1",
        path=Path("billing/CustomerView.v1.sql"),
        content=content,
        content_hash="test",
    )


def _synthetic_json_schema_artifact(content: object) -> EmittedArtifact:
    return EmittedArtifact(
        target="json-schema",
        ref="billing.Customer@1",
        artifact_id="billing.Customer.v1",
        path=Path("billing/Customer.v1.json"),
        content=content,
        content_hash="test",
    )


def _synthetic_avro_artifact(content: object, *, target: str = "avro") -> EmittedArtifact:
    return EmittedArtifact(
        target=target,
        ref="billing.Customer@1",
        artifact_id="billing.Customer.v1",
        path=Path("billing/Customer.v1.avsc"),
        content=content,
        content_hash="test",
    )


def test_fhir_compat_reports_element_cardinality_narrowing():
    old = {
        "resourceType": "StructureDefinition",
        "snapshot": {
            "element": [
                {"path": "Patient", "min": 0, "max": "1"},
                {"path": "Patient.name", "min": 0, "max": "1", "type": [{"code": "string"}]},
            ]
        },
    }
    new = {
        "resourceType": "StructureDefinition",
        "snapshot": {
            "element": [
                {"path": "Patient", "min": 0, "max": "1"},
                {"path": "Patient.name", "min": 1, "max": "1", "type": [{"code": "string"}]},
            ]
        },
    }

    report = compare_fhir_artifacts(
        [_synthetic_fhir_artifact(old)],
        [_synthetic_fhir_artifact(new)],
    )

    assert report.target == "fhir-profile"
    assert report.status == "breaking"
    finding = next(item for item in report.findings if item.code == "element_min_increased")
    assert finding.axis == "wire_compatibility"
    assert finding.severity == "breaking"


def test_fhir_compat_reports_removed_and_type_changed_elements():
    old = {
        "snapshot": {
            "element": [
                {"path": "Patient", "min": 0, "max": "1"},
                {"path": "Patient.name", "min": 0, "max": "1", "type": [{"code": "string"}]},
                {"path": "Patient.birthDate", "min": 0, "max": "1", "type": [{"code": "date"}]},
            ]
        }
    }
    new = {
        "snapshot": {
            "element": [
                {"path": "Patient", "min": 0, "max": "1"},
                {"path": "Patient.name", "min": 0, "max": "1", "type": [{"code": "HumanName"}]},
            ]
        }
    }

    report = compare_fhir_artifacts(
        [_synthetic_fhir_artifact(old)],
        [_synthetic_fhir_artifact(new)],
    )

    assert {finding.code for finding in report.findings} == {"element_removed", "element_type_changed"}


def test_fhir_compat_allows_optional_element_addition_and_widening():
    old = {"snapshot": {"element": [{"path": "Patient", "min": 0, "max": "1"}]}}
    new = {
        "snapshot": {
            "element": [
                {"path": "Patient", "min": 0, "max": "1"},
                {"path": "Patient.name", "min": 0, "max": "*", "type": [{"code": "string"}]},
            ]
        }
    }

    report = compare_fhir_artifacts(
        [_synthetic_fhir_artifact(old)],
        [_synthetic_fhir_artifact(new)],
    )

    assert report.status == "read_compatible"
    assert report.findings == []


def test_fhir_compat_reports_required_addition_and_maximum_narrowing():
    old = {
        "snapshot": {
            "element": [
                {"path": "Patient"},
                {"path": "Patient.name", "min": 0, "max": "*"},
            ]
        }
    }
    new = {
        "snapshot": {
            "element": [
                {"path": "Patient"},
                {"path": "Patient.name", "min": 0, "max": "1"},
                {"path": "Patient.birthDate", "min": 1, "max": "1"},
            ]
        }
    }

    report = compare_fhir_artifacts(
        [_synthetic_fhir_artifact(old)],
        [_synthetic_fhir_artifact(new)],
    )

    assert {finding.code for finding in report.findings} == {
        "element_required_added",
        "element_max_decreased",
    }


def test_fhir_compat_ignores_malformed_and_non_profile_artifacts():
    malformed = EmittedArtifact(
        target="fhir-profile",
        ref="billing.Malformed@1",
        artifact_id="billing.Malformed.v1",
        path=Path("billing/Malformed.v1.fhir.json"),
        content="not json",
        content_hash="test",
    )
    other_target = EmittedArtifact(
        target="json-schema",
        ref="billing.Other@1",
        artifact_id="billing.Other.v1",
        path=Path("billing/Other.v1.json"),
        content="{}",
        content_hash="test",
    )

    report = compare_fhir_artifacts([malformed, other_target], [])

    assert report.status == "read_compatible"
    assert report.findings == []


def test_odcs_compat_reports_removed_required_property():
    old = {
        "apiVersion": "v3.1.0",
        "schema": [{"properties": [{"name": "customerId", "required": True}]}],
    }
    new = {"apiVersion": "v3.1.0", "schema": [{"properties": []}]}

    report = compare_odcs_artifacts(
        [_synthetic_odcs_artifact(old, ref="billing.Customer@1")],
        [_synthetic_odcs_artifact(new, ref="billing.Customer@1")],
    )

    assert report.status == "breaking"
    assert report.findings[0].code == "property_removed"


def test_odcs_compat_reports_required_type_and_enum_narrowing():
    old = {
        "schema": [
            {
                "properties": [
                    {
                        "name": "status",
                        "logicalType": "string",
                        "required": False,
                        "customProperties": [
                            {"property": "modelableType", "value": "enum(active,blocked)"},
                            {"property": "modelableEnum", "value": ["active", "blocked"]},
                        ],
                    }
                ]
            }
        ]
    }
    new = {
        "schema": [
            {
                "properties": [
                    {
                        "name": "status",
                        "logicalType": "integer",
                        "required": True,
                        "customProperties": [
                            {"property": "modelableType", "value": "enum(active)"},
                            {"property": "modelableEnum", "value": ["active"]},
                        ],
                    },
                    {"name": "email", "logicalType": "string", "required": True},
                ]
            }
        ]
    }

    report = compare_odcs_artifacts([_synthetic_odcs_artifact(old)], [_synthetic_odcs_artifact(new)])

    assert {finding.code for finding in report.findings} == {
        "property_required",
        "property_type_changed",
        "enum_value_removed",
        "property_required_added",
    }


def test_odcs_compat_allows_optional_property_and_enum_widening():
    old = {
        "schema": [
            {
                "properties": [
                    {
                        "name": "status",
                        "logicalType": "string",
                        "required": False,
                        "customProperties": [
                            {"property": "modelableType", "value": "enum(active)"},
                            {"property": "modelableEnum", "value": ["active"]},
                        ],
                    }
                ]
            }
        ]
    }
    new = {
        "schema": [
            {
                "properties": [
                    {
                        "name": "status",
                        "logicalType": "string",
                        "required": False,
                        "customProperties": [
                            {"property": "modelableType", "value": "enum(active,blocked)"},
                            {"property": "modelableEnum", "value": ["active", "blocked"]},
                        ],
                    },
                    {"name": "nickname", "logicalType": "string", "required": False},
                ]
            }
        ]
    }

    report = compare_odcs_artifacts([_synthetic_odcs_artifact(old)], [_synthetic_odcs_artifact(new)])

    assert report.status == "read_compatible"
    assert report.findings == []


def test_odcs_compat_reports_new_required_and_removed_contracts():
    required = {"schema": [{"properties": [{"name": "id", "required": True}]}]}

    added = compare_odcs_artifacts([], [_synthetic_odcs_artifact(required, ref="billing.New@1")])
    removed = compare_odcs_artifacts([_synthetic_odcs_artifact(required, ref="billing.Old@1")], [])

    assert added.findings[0].code == "property_required_added"
    assert removed.findings[0].code == "contract_removed"


def test_odcs_compat_ignores_malformed_and_non_object_artifacts():
    malformed = EmittedArtifact(
        target="odcs",
        ref="billing.Malformed@1",
        artifact_id="billing.Malformed.v1",
        path=Path("billing/Malformed.v1.odcs.yaml"),
        content="schema: [",
        content_hash="test",
    )
    non_object = EmittedArtifact(
        target="odcs",
        ref="billing.Scalar@1",
        artifact_id="billing.Scalar.v1",
        path=Path("billing/Scalar.v1.odcs.yaml"),
        content="- scalar",
        content_hash="test",
    )

    report = compare_odcs_artifacts([malformed, non_object], [])

    assert report.status == "read_compatible"
    assert report.findings == []


def test_sql_compat_reports_changed_table_as_storage_migration():
    report = compare_sql_artifacts(
        [_synthetic_sql_artifact("CREATE TABLE customer_view (id UUID NOT NULL);\n")],
        [_synthetic_sql_artifact("CREATE TABLE customer_view (id UUID NOT NULL, name TEXT);\n")],
    )

    assert report.target == "sql-postgres"
    assert report.status == "migration_required"
    assert len(report.findings) == 1
    finding = report.findings[0]
    assert finding.code == "table_definition_changed"
    assert finding.axis == "storage_migration"
    assert finding.severity == "migration_required"


def test_sql_compat_reports_removed_table_as_breaking():
    report = compare_sql_artifacts(
        [_synthetic_sql_artifact("CREATE TABLE customer_view (id UUID NOT NULL);\n")],
        [],
    )

    assert report.status == "breaking"
    assert [finding.code for finding in report.findings] == ["table_removed"]


def test_sql_compat_allows_unchanged_tables():
    content = "CREATE TABLE customer_view (id UUID NOT NULL);\n"

    report = compare_sql_artifacts(
        [_synthetic_sql_artifact(content)],
        [_synthetic_sql_artifact(content)],
    )

    assert report.status == "read_compatible"
    assert report.findings == []


def test_validate_compat_cli_supports_sql_postgres(tmp_path: Path):
    old = _write(
        tmp_path / "old-sql.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
  projection CustomerView @ 1 from billing.Customer @ 1 as c {
    customerId <- c.customerId
  }
}
""",
    )
    new = _write(
        tmp_path / "new-sql.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    displayName: string
  }
  projection CustomerView @ 1 from billing.Customer @ 1 as c {
    customerId <- c.customerId
    displayName <- c.displayName
  }
}
""",
    )

    result = CliRunner().invoke(
        cli,
        ["validate-compat", "--from", str(old), "--to", str(new), "--target", "sql-postgres"],
    )

    assert result.exit_code == 1
    assert "target: sql-postgres" in result.output
    assert "table_definition_changed" in result.output


def test_avro_compat_rejects_added_required_field(tmp_path: Path):
    old = _write(
        tmp_path / "old.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""",
    )
    new = _write(
        tmp_path / "new.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    displayName: string
  }
}
""",
    )

    report = compare_avro_artifacts(_avro_artifacts(old), _avro_artifacts(new))

    assert report.target == "avro"
    assert report.status == "breaking"
    finding = next(item for item in report.findings if item.code == "required_field_added")
    assert finding.axis == "wire_compatibility"
    assert finding.severity == "breaking"


def test_validate_compat_cli_supports_avro(tmp_path: Path):
    old = _write(
        tmp_path / "old.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""",
    )
    new = _write(
        tmp_path / "new.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    displayName: string
  }
}
""",
    )

    result = CliRunner().invoke(
        cli,
        ["validate-compat", "--from", str(old), "--to", str(new), "--target", "avro"],
    )

    assert result.exit_code == 1
    assert "target: avro" in result.output
    assert "required_field_added" in result.output


def test_json_schema_compat_rejects_added_required_property(tmp_path: Path):
    old = _write(
        tmp_path / "old-json-schema.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""",
    )
    new = _write(
        tmp_path / "new-json-schema.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    displayName: string
  }
}
""",
    )

    report = compare_json_schema_artifacts(_json_schema_artifacts(old), _json_schema_artifacts(new))

    assert report.target == "json-schema"
    assert report.status == "breaking"
    finding = next(item for item in report.findings if item.code == "required_property_added")
    assert finding.axis == "source_compatibility"
    assert finding.severity == "breaking"


def test_validate_compat_cli_supports_json_schema(tmp_path: Path):
    old = _write(
        tmp_path / "old-json-schema-cli.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""",
    )
    new = _write(
        tmp_path / "new-json-schema-cli.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    displayName: string
  }
}
""",
    )

    result = CliRunner().invoke(
        cli,
        ["validate-compat", "--from", str(old), "--to", str(new), "--target", "json-schema"],
    )

    assert result.exit_code == 1
    assert "target: json-schema" in result.output
    assert "required_property_added" in result.output


def test_json_schema_compat_reports_removed_and_changed_properties():
    old = {
        "type": "object",
        "properties": {"legacy": {"type": "string"}, "amount": {"type": "integer"}},
        "required": ["legacy", "amount"],
    }
    new = {
        "type": "object",
        "properties": {"amount": {"type": "number"}},
        "required": ["amount"],
    }

    report = compare_json_schema_artifacts(
        [_synthetic_json_schema_artifact(old)],
        [_synthetic_json_schema_artifact(new)],
    )

    assert {finding.code for finding in report.findings} == {"property_removed", "property_type_changed"}


def test_json_schema_compat_allows_optional_property_and_requiredness_widening():
    old = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }
    new = {
        "type": "object",
        "properties": {"name": {"type": "string"}, "nickname": {"type": "string"}},
        "required": [],
    }

    report = compare_json_schema_artifacts(
        [_synthetic_json_schema_artifact(old)],
        [_synthetic_json_schema_artifact(new)],
    )

    assert report.status == "read_compatible"
    assert report.findings == []


def test_json_schema_compat_rejects_making_existing_property_required():
    old = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": [],
    }
    new = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }

    report = compare_json_schema_artifacts(
        [_synthetic_json_schema_artifact(old)],
        [_synthetic_json_schema_artifact(new)],
    )

    assert report.status == "breaking"
    assert [finding.code for finding in report.findings] == ["required_property_added"]


def test_avro_compat_allows_added_optional_field(tmp_path: Path):
    old = _write(
        tmp_path / "old.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""",
    )
    new = _write(
        tmp_path / "new.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    displayName?: string
  }
}
""",
    )

    report = compare_avro_artifacts(_avro_artifacts(old), _avro_artifacts(new))

    assert report.status == "read_compatible"
    assert report.findings == []


def test_avro_compat_reports_schema_and_existing_field_changes():
    old = {
        "type": "record",
        "name": "CustomerV1",
        "namespace": "billing",
        "fields": [
            {"name": "customerId", "type": "string"},
            {"name": "legacy", "type": "string"},
            {"name": "amount", "type": "int"},
        ],
        "x-modelable": {"ref": "billing.Customer@1"},
    }
    new = {
        "type": "record",
        "name": "CustomerV2",
        "namespace": "other",
        "fields": [
            {"name": "customerId", "type": "long"},
            {"name": "amount", "type": "long"},
        ],
        "x-modelable": {"ref": "billing.Customer@1"},
    }

    report = compare_avro_artifacts(
        [_synthetic_avro_artifact(old), _synthetic_avro_artifact("ignored", target="other")],
        [_synthetic_avro_artifact(new)],
    )

    assert {finding.code for finding in report.findings} == {
        "schema_name_changed",
        "field_removed",
        "field_type_changed",
    }


def test_avro_compat_reports_schema_type_changes():
    old = {"type": "record", "x-modelable": {"ref": "billing.Customer@1"}}
    new = {"type": "enum", "x-modelable": {"ref": "billing.Customer@1"}}

    report = compare_avro_artifacts([_synthetic_avro_artifact(old)], [_synthetic_avro_artifact(new)])

    assert [finding.code for finding in report.findings] == ["schema_type_changed"]


def test_openapi_compat_reports_removed_operation_and_response(tmp_path: Path):
    old = _write(
        tmp_path / "old.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key id: uuid
  }
  auto projections Customer @ 1 { reply }
  api Customer @ 1 {
    operation "getCustomer" {
      method: GET
      path: "/customers/{id}"
      responses { 200: CustomerReply @ 1 }
    }
  }
}
""",
    )
    new = _write(
        tmp_path / "new.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key id: uuid
  }
  auto projections Customer @ 1 { reply }
  api Customer @ 1 {
    operation "getCustomer" {
      method: GET
      path: "/customers/{id}"
      responses { 404: CustomerReply @ 1 }
    }
  }
}
""",
    )

    report = compare_openapi_artifacts(_openapi_artifacts(old), _openapi_artifacts(new))

    assert report.target == "openapi"
    assert report.status == "breaking"
    assert [finding.code for finding in report.findings] == ["response_removed"]


def _protobuf_artifacts(path: Path):
    return emit_protobuf(load_workspace(path), path.parent / "out")


def _grpc_artifacts(path: Path):
    return emit_grpc(load_workspace(path), path.parent / "grpc-out")


def _openapi_artifact(document: dict[str, Any]) -> EmittedArtifact:
    return EmittedArtifact(
        target="openapi",
        ref="workspace",
        artifact_id="openapi",
        path=Path("openapi.json"),
        content=document,
        content_hash="test-hash",
    )


def test_openapi_compat_reports_operation_binding_changes():
    old_operation = {
        "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}],
        "requestBody": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Req.v1"}}}},
        "responses": {
            "200": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Reply.v1"}}}},
            "404": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error.v1"}}}},
        },
    }
    new_operation = {
        "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}}],
        "requestBody": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Req.v2"}}}},
        "responses": {"200": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Reply.v2"}}}}},
    }
    old = _openapi_artifact(
        {"openapi": "3.1.0", "paths": {"/customers/{id}": {"get": old_operation}, "/legacy": {"delete": {}}}}
    )
    new = _openapi_artifact({"openapi": "3.1.0", "paths": {"/customers/{id}": {"get": new_operation}}})

    report = compare_openapi_artifacts([old], [new])

    assert report.status == "breaking"
    assert [finding.code for finding in report.findings] == [
        "operation_removed",
        "path_parameters_changed",
        "request_binding_changed",
        "response_removed",
        "response_binding_changed",
    ]


def test_openapi_compat_reports_changed_and_removed_component_schemas():
    old = _openapi_artifact(
        {
            "components": {
                "schemas": {
                    "Billing.CustomerReply.v1": {"type": "object", "required": ["id"]},
                    "Billing.Legacy.v1": {"type": "object"},
                }
            }
        }
    )
    new = _openapi_artifact(
        {
            "components": {
                "schemas": {
                    "Billing.CustomerReply.v1": {"type": "object", "required": ["id", "name"]},
                    "Billing.AddedLater.v1": {"type": "object", "properties": {"id": {"type": "string"}}},
                }
            }
        }
    )

    report = compare_openapi_artifacts([old], [new])

    assert report.status == "breaking"
    assert [(finding.code, finding.ref) for finding in report.findings] == [
        ("schema_removed", "Billing.Legacy.v1"),
        ("schema_changed", "Billing.CustomerReply.v1"),
    ]


def test_openapi_compat_ignores_malformed_non_operation_artifacts():
    empty_report = compare_openapi_artifacts([], [_openapi_artifact({"paths": []})])
    malformed_report = compare_openapi_artifacts(
        [_openapi_artifact({"paths": {"/customers": {"get": {}}}})],
        [
            _openapi_artifact(
                {
                    "paths": {
                        "not-a-path-item": [],
                        "/customers": {
                            "get": {
                                "parameters": ["not-a-parameter", {"in": "query"}],
                                "requestBody": {"content": []},
                                "responses": [],
                            }
                        },
                    }
                }
            )
        ],
    )
    malformed_media_report = compare_openapi_artifacts(
        [_openapi_artifact({"paths": {"/customers": {"get": {"requestBody": {"content": {"application/json": []}}}}}})],
        [_openapi_artifact({"paths": {"/customers": {"get": {"requestBody": {"content": {"application/json": []}}}}}})],
    )

    assert empty_report.status == "read_compatible"
    assert empty_report.findings == []
    assert malformed_report.status == "read_compatible"
    assert malformed_report.findings == []
    assert malformed_media_report.findings == []


def _set_descriptor_hash(artifacts: list[Any], target: str, content_hash: str) -> None:
    manifest_name = "schema-manifest.json" if target == "protobuf" else "service-manifest.json"
    for artifact in artifacts:
        if artifact.path.name != manifest_name or not isinstance(artifact.content, str):
            continue
        manifest = json.loads(artifact.content)
        entry = manifest["schemas"][0] if target == "protobuf" else manifest
        entry["descriptor"] = {"content_hash": content_hash}
        artifact.content = json.dumps(manifest, indent=2) + "\n"
        return
    raise AssertionError(f"missing {manifest_name}")


def _model_version(mdl_text: str, version: int = 1):
    mdl = parse_text_to_ir(mdl_text)
    domain = mdl.domains[0]
    model_name = next(iter(domain.models))
    return next(item for item in domain.models[model_name] if item.version == version)


def _index_decl(mdl_text: str, model: str, version: int = 1):
    mdl = parse_text_to_ir(mdl_text)
    domain = mdl.domains[0]
    return next((decl for decl in domain.index_decls if decl.model == model and decl.version == version), None)


def _projection_versions(old_text: str, new_text: str, name: str = "OrderView"):
    old_mdl = parse_text_to_ir(old_text)
    new_mdl = parse_text_to_ir(new_text)
    old = old_mdl.domains[0].projections[name][0]
    new = new_mdl.domains[0].projections[name][0]
    return new_mdl, old, new


def test_protobuf_compat_allows_added_optional_field(tmp_path):
    old = _write(
        tmp_path / "old.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""",
    )
    new = _write(
        tmp_path / "new.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    displayName?: string
  }
}
""",
    )

    report = compare_protobuf_manifests(_protobuf_artifacts(old), _protobuf_artifacts(new))

    assert report.status == "wire_compatible"
    assert report.findings == []


def test_protobuf_compat_flags_changed_descriptor_for_review(tmp_path):
    source = _write(
        tmp_path / "source.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""",
    )
    old = _protobuf_artifacts(source)
    new = _protobuf_artifacts(source)
    _set_descriptor_hash(old, "protobuf", "old-descriptor-hash")
    _set_descriptor_hash(new, "protobuf", "new-descriptor-hash")

    report = compare_protobuf_manifests(old, new)

    assert report.status == "review_required"
    assert [finding.code for finding in report.findings] == ["descriptor_changed"]


def test_grpc_compat_flags_changed_descriptor_for_review(tmp_path):
    source = _write(
        tmp_path / "source.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""",
    )
    old = _grpc_artifacts(source)
    new = _grpc_artifacts(source)
    _set_descriptor_hash(old, "grpc", "old-descriptor-hash")
    _set_descriptor_hash(new, "grpc", "new-descriptor-hash")

    report = compare_grpc_artifacts(old, new)

    assert report.status == "review_required"
    assert [finding.code for finding in report.findings] == ["descriptor_changed"]


def test_event_sink_compat_flags_removed_operation_as_breaking():
    old = EmittedArtifact(
        target="event-sink",
        ref="workspace#event-sink",
        artifact_id="event-sink",
        path=Path("event-sink.json"),
        content=json.dumps(
            {
                "format": "modelable.event-sink.v1",
                "events": [{"ref": "billing.OrderEvent@1", "operations": ["insert", "delete"]}],
            }
        ),
        content_hash="old",
    )
    new = EmittedArtifact(
        target="event-sink",
        ref="workspace#event-sink",
        artifact_id="event-sink",
        path=Path("event-sink.json"),
        content=json.dumps(
            {
                "format": "modelable.event-sink.v1",
                "events": [{"ref": "billing.OrderEvent@1", "operations": ["insert"]}],
            }
        ),
        content_hash="new",
    )

    report = compare_event_sink_artifacts([old], [new])

    assert report.status == "breaking"
    assert [(finding.code, finding.severity, finding.ref) for finding in report.findings] == [
        ("event_operation_removed", "breaking", "billing.OrderEvent@1")
    ]


def test_event_sink_compat_flags_changed_payload_schema_for_review():
    def artifact(schema_type: str) -> EmittedArtifact:
        return EmittedArtifact(
            target="event-sink",
            ref="workspace#event-sink",
            artifact_id="event-sink",
            path=Path("event-sink.json"),
            content=json.dumps(
                {
                    "format": "modelable.event-sink.v1",
                    "events": [
                        {
                            "ref": "billing.OrderEvent@1",
                            "operations": ["insert"],
                            "payload_schema": {"$ref": "#/components/schemas/OrderEvent"},
                        }
                    ],
                    "components": {"schemas": {"OrderEvent": {"type": schema_type}}},
                }
            ),
            content_hash=schema_type,
        )

    report = compare_event_sink_artifacts([artifact("string")], [artifact("integer")])

    assert report.status == "review_required"
    assert [(finding.code, finding.severity) for finding in report.findings] == [
        ("payload_schema_changed", "review_required")
    ]


def test_compat_accepts_unchanged_descriptor_hash(tmp_path):
    source = _write(
        tmp_path / "source.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""",
    )
    old = _protobuf_artifacts(source)
    new = _protobuf_artifacts(source)
    _set_descriptor_hash(old, "protobuf", "same-descriptor-hash")
    _set_descriptor_hash(new, "protobuf", "same-descriptor-hash")

    report = compare_protobuf_manifests(old, new)

    assert report.status == "wire_compatible"
    assert report.findings == []


def test_protobuf_compat_rejects_removed_field_without_reservation(tmp_path):
    old = _write(
        tmp_path / "old.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    legacyStatus: string
  }
}
""",
    )
    new = _write(
        tmp_path / "new.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""",
    )

    report = compare_protobuf_manifests(_protobuf_artifacts(old), _protobuf_artifacts(new))

    assert report.status == "breaking"
    assert any(finding.code == "removed_field_not_reserved" for finding in report.findings)


def test_protobuf_compat_allows_removed_field_with_number_and_name_reservation(tmp_path):
    old = _write(
        tmp_path / "old.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    legacyStatus: string
  }
}
""",
    )
    new = _write(
        tmp_path / "new.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    reserved protobuf {
      numbers: [2]
      names: ["legacy_status"]
    }
    @key customerId: uuid
  }
}
""",
    )

    report = compare_protobuf_manifests(_protobuf_artifacts(old), _protobuf_artifacts(new))

    assert report.status == "wire_compatible"
    assert report.findings == []


def test_protobuf_compat_rejects_field_number_reuse_by_reorder(tmp_path):
    old = _write(
        tmp_path / "old.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    displayName: string
  }
}
""",
    )
    new = _write(
        tmp_path / "new.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    displayName: string
    @key customerId: uuid
  }
}
""",
    )

    report = compare_protobuf_manifests(_protobuf_artifacts(old), _protobuf_artifacts(new))

    assert report.status == "breaking"
    assert any(finding.code == "field_number_reused" for finding in report.findings)


def test_protobuf_compat_rejects_target_type_change(tmp_path):
    old = _write(
        tmp_path / "old.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    score: int
  }
}
""",
    )
    new = _write(
        tmp_path / "new.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    score: string
  }
}
""",
    )

    report = compare_protobuf_manifests(_protobuf_artifacts(old), _protobuf_artifacts(new))

    assert report.status == "breaking"
    assert any(finding.code == "field_type_changed" for finding in report.findings)


def test_protobuf_compat_rejects_inline_enum_reorder(tmp_path):
    old = _write(
        tmp_path / "old.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    status: enum(active, blocked)
  }
}
""",
    )
    new = _write(
        tmp_path / "new.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    status: enum(blocked, active)
  }
}
""",
    )

    report = compare_protobuf_manifests(_protobuf_artifacts(old), _protobuf_artifacts(new))

    assert report.status == "breaking"
    assert any(finding.code == "enum_value_reused" for finding in report.findings)


def test_grpc_compat_reports_changed_secondary_index_as_read_rebuild(tmp_path):
    old = _write(
        tmp_path / "old.mdl",
        """
domain billing {
  owner: "billing"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    customerId: uuid
    createdAt: timestamp
  }
  index Order @ 1 {
    primary orderId
    secondary by_customer {
      key: [customerId]
    }
  }
}
""",
    )
    new = _write(
        tmp_path / "new.mdl",
        """
domain billing {
  owner: "billing"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    customerId: uuid
    createdAt: timestamp
  }
  index Order @ 1 {
    primary orderId
    secondary by_customer {
      key: [customerId]
      sort: [createdAt desc]
    }
  }
}
""",
    )

    report = compare_grpc_artifacts(_grpc_artifacts(old), _grpc_artifacts(new))

    assert report.status == "requires_read_rebuild"
    assert any(finding.code == "read_index_changed" for finding in report.findings)


def test_validate_compat_cli_passes_wire_compatible_change(tmp_path):
    old = _write(
        tmp_path / "old.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""",
    )
    new = _write(
        tmp_path / "new.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    displayName?: string
  }
}
""",
    )

    result = CliRunner().invoke(
        cli,
        ["validate-compat", "--from", str(old), "--to", str(new), "--target", "protobuf"],
    )

    assert result.exit_code == 0
    assert "status: wire_compatible" in result.output
    assert "- no target compatibility findings" in result.output


def test_validate_compat_rejects_unsupported_target_capabilities_before_emission(tmp_path):
    source = _write(
        tmp_path / "union.mdl",
        """
domain payments {
  owner: "payments"
  entity Card @ 1 (additive) { @key id: uuid }
  entity Bank @ 1 (additive) { @key id: uuid }
  entity Payment @ 1 (additive) {
    @key id: uuid
    method: union<kind> { card: ref<Card>, bank: ref<Bank> }
  }
}
""",
    )

    result = CliRunner().invoke(
        cli,
        ["validate-compat", "--from", str(source), "--to", str(source), "--target", "protobuf"],
    )

    assert result.exit_code != 0
    assert "does not support required capability 'unions'" in result.output


def test_validate_compat_cli_passes_openapi_without_operations(tmp_path):
    source = """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
"""
    old = _write(tmp_path / "old.mdl", source)
    new = _write(tmp_path / "new.mdl", source)

    result = CliRunner().invoke(
        cli,
        [
            "validate-compat",
            "--from",
            str(old),
            "--to",
            str(new),
            "--target",
            "openapi",
        ],
    )

    assert result.exit_code == 0
    assert "target: openapi" in result.output
    assert "status: read_compatible" in result.output
    assert "- no target compatibility findings" in result.output


def test_validate_compat_cli_fails_breaking_change(tmp_path):
    old = _write(
        tmp_path / "old.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    legacyStatus: string
  }
}
""",
    )
    new = _write(
        tmp_path / "new.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""",
    )

    result = CliRunner().invoke(
        cli,
        ["validate-compat", "--from", str(old), "--to", str(new), "--target", "protobuf"],
    )

    assert result.exit_code == 1
    assert "status: breaking" in result.output
    assert "removed_field_not_reserved" in result.output


def test_validate_compat_cli_json_exposes_validated_consequence_graph(tmp_path):
    old = _write(
        tmp_path / "old.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    legacyStatus: string
  }
}
""",
    )
    new = _write(
        tmp_path / "new.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""",
    )

    result = CliRunner().invoke(
        cli,
        [
            "validate-compat",
            "--from",
            str(old),
            "--to",
            str(new),
            "--target",
            "protobuf",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["kind"] == "target_consequence_report"
    assert payload["target"] == "protobuf"
    assert payload["status"] == "breaking"
    graph = validate_consequence_graph(payload["consequence_graph"])
    assert graph["$schema"] == "modelable.consequence/v0"
    assert any(item["action"] == "breaking" for item in payload["consequences"])
    assert any(item["causal_path"][:2] == ["protobuf:from", "protobuf:to"] for item in payload["consequences"])


def test_validate_compat_cli_json_keeps_policy_result_machine_readable(tmp_path):
    source = _write(
        tmp_path / "model.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""",
    )
    policy = _write(tmp_path / "policy.yaml", "compatibility:\n  protobuf: compatible\n")

    result = CliRunner().invoke(
        cli,
        [
            "validate-compat",
            "--from",
            str(source),
            "--to",
            str(source),
            "--target",
            "protobuf",
            "--policy",
            str(policy),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["policy"] == {
        "blocking_findings": [],
        "passed": True,
        "target": "protobuf",
        "threshold": "compatible",
    }


def test_validate_compat_target_choices_match_the_registry():
    result = CliRunner().invoke(cli, ["validate-compat", "--help"])

    assert "protobuf" in result.output
    assert "grpc" in result.output
    assert "openapi" in result.output
    assert "avro" in result.output
    assert "json-schema" in result.output
    assert "sql-postgres" in result.output
    assert "sql-clickhouse" in result.output
    assert "fhir-profile" in result.output
    assert "odcs" in result.output


def test_validate_compat_cli_supports_fhir_profile(tmp_path):
    source = _write(
        tmp_path / "model.mdl",
        """
domain clinical {
  owner: "clinical-platform"
  entity Patient @ 1 (additive) {
    @key patientId: uuid
    birthDate?: date
  }

  projection PatientProfile @ 1
    from clinical.Patient @ 1 as p
  {
    patientId <- p.patientId
    birthDate <- p.birthDate
  }
}
""",
    )

    result = CliRunner().invoke(
        cli,
        [
            "validate-compat",
            "--from",
            str(source),
            "--to",
            str(source),
            "--target",
            "fhir-profile",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["target"] == "fhir-profile"
    assert payload["status"] == "read_compatible"


def test_validate_compat_cli_supports_odcs(tmp_path):
    source = _write(
        tmp_path / "model.mdl",
        """
domain billing {
  owner: "billing-platform"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    name?: string
  }
}
""",
    )

    result = CliRunner().invoke(
        cli,
        [
            "validate-compat",
            "--from",
            str(source),
            "--to",
            str(source),
            "--target",
            "odcs",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["target"] == "odcs"
    assert payload["status"] == "read_compatible"


# --- Slice C3: common target-compatibility axis/severity IR -----------------


def test_protobuf_and_grpc_findings_carry_the_common_axis_and_severity(tmp_path):
    old = _write(
        tmp_path / "old.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    legacyStatus: string
  }
}
""",
    )
    new = _write(
        tmp_path / "new.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""",
    )

    report = compare_protobuf_manifests(_protobuf_artifacts(old), _protobuf_artifacts(new))

    assert report.severity == "breaking"
    assert report.findings
    for finding in report.findings:
        assert finding.axis == "wire_compatibility"
        assert finding.axis in AXES
        assert finding.severity in SEVERITIES
    assert any(finding.severity == "breaking" for finding in report.findings)


def test_grpc_read_index_change_maps_to_migration_required_severity(tmp_path):
    old = _write(
        tmp_path / "old.mdl",
        """
domain billing {
  owner: "billing"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    customerId: uuid
    createdAt: timestamp
  }
  index Order @ 1 {
    primary orderId
    secondary by_customer {
      key: [customerId]
    }
  }
}
""",
    )
    new = _write(
        tmp_path / "new.mdl",
        """
domain billing {
  owner: "billing"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    customerId: uuid
    createdAt: timestamp
  }
  index Order @ 1 {
    primary orderId
    secondary by_customer {
      key: [customerId]
      sort: [createdAt desc]
    }
  }
}
""",
    )

    report = compare_grpc_artifacts(_grpc_artifacts(old), _grpc_artifacts(new))

    assert report.severity == "migration_required"
    finding = next(f for f in report.findings if f.code == "read_index_changed")
    assert finding.severity == "migration_required"
    assert finding.axis == "wire_compatibility"


def test_source_representation_classifies_breaking_and_compatible_changes():
    old_version = _model_version(
        """
        domain customer {
          owner: "test-team"
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            name: string
          }
        }
        """
    )
    new_version = _model_version(
        """
        domain customer {
          owner: "test-team"
          entity Customer @ 2 (additive) {
            @key customerId: uuid
            email?: string
          }
        }
        """,
        version=2,
    )

    changes = compare_model_versions(old_version, new_version)
    report = compare_source_representation("customer", "Customer", changes)

    assert report.severity == "breaking"
    removed = next(f for f in report.findings if f.code == "removed_field")
    added = next(f for f in report.findings if f.code == "added_field")
    assert removed.severity == "breaking"
    assert removed.axis == "source_compatibility"
    assert added.severity == "compatible"
    assert added.axis == "source_compatibility"


def test_semantic_compatibility_ignores_storage_changes_from_model_report():
    mdl = parse_text_to_ir(
        """
        domain billing {
          owner: "billing"
          entity Order @ 1 (additive) {
            @key orderId: uuid
          }
          entity Order @ 2 (additive) {
            @key orderId: uuid
          }
          index Order @ 2 {
            primary orderId
            secondary by_order {
              key: [orderId]
            }
          }
        }
        """
    )

    from modelable.compat.checker import check_model_version_compatibility

    model_report = check_model_version_compatibility(mdl, "billing", "Order", 1, 2)
    semantic_report = compare_semantic_compatibility(model_report)

    assert model_report.status == "compatible"
    assert [change.kind for change in model_report.semantic_changes] == []
    assert len(model_report.storage_changes) == 2
    assert all(change.kind == "index_changed" for change in model_report.storage_changes)
    assert semantic_report.status == "compatible"
    assert semantic_report.findings == []
    storage_report = compare_model_storage_migration(model_report)
    assert storage_report.status == "migration_required"
    assert len(storage_report.findings) == 2


def test_data_backfill_reports_required_added_field_with_default():
    from modelable.compat.checker import check_model_version_compatibility

    mdl = parse_text_to_ir(
        """
        domain customer {
          owner: "test-team"
          entity Customer @ 1 (additive) {
            @key id: uuid
            name: string
          }
          entity Customer @ 2 (breaking) {
            @key id: uuid
            name: string
            status: string = "active"
          }
        }
        """
    )

    report = compare_data_backfill(check_model_version_compatibility(mdl, "customer", "Customer", 1, 2))

    assert report.status == "migration_required"
    assert report.severity == "migration_required"
    assert [(finding.code, finding.field) for finding in report.findings] == [("field_added_with_default", "status")]


def test_source_representation_is_the_json_representation_axis_by_reuse():
    # JSON Schema emission adds no wire constraints beyond the shared model
    # contract, so the JSON-representation axis is exactly this function
    # under a different target label -- not a second diff implementation.
    old_version = _model_version(
        """
        domain customer {
          owner: "test-team"
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            status: string
          }
        }
        """
    )
    new_version = _model_version(
        """
        domain customer {
          owner: "test-team"
          entity Customer @ 2 (additive) {
            @key customerId: uuid
            status?: string
          }
        }
        """,
        version=2,
    )

    changes = compare_model_versions(old_version, new_version)
    report = compare_source_representation("customer", "Customer", changes, target="json-schema")

    # required -> optional widens the contract; not breaking.
    assert report.target == "json-schema"
    assert report.severity == "compatible"
    finding = next(f for f in report.findings if f.code == "presence_changed")
    assert finding.axis == "source_compatibility"
    assert finding.severity == "compatible"


def test_storage_migration_reports_index_changes_as_migration_required():
    old_index = _index_decl(
        """
        domain billing {
          owner: "billing"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            customerId: uuid
          }
          index Order @ 1 {
            primary orderId
          }
        }
        """,
        model="Order",
    )
    new_index = _index_decl(
        """
        domain billing {
          owner: "billing"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            customerId: uuid
          }
          index Order @ 1 {
            primary orderId
            secondary by_customer {
              key: [customerId]
            }
          }
        }
        """,
        model="Order",
    )

    index_changes = compare_index_decls(old_index, new_index)
    report = compare_storage_migration("billing", "Order", index_changes)

    assert report.severity == "migration_required"
    assert report.target == "sql"
    for finding in report.findings:
        assert finding.axis == "storage_migration"
        assert finding.severity == "migration_required"


def test_storage_migration_is_compatible_when_no_index_changed():
    report = compare_storage_migration("billing", "Order", [])

    assert report.severity == "compatible"
    assert report.findings == []


def test_projection_rebuild_reports_expression_only_change_as_migration_required():
    mdl, old, new = _projection_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            status: string
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            isShipped = o.status == "shipped"
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            status: string
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            isShipped = o.status == "delivered"
          }
        }
        """,
    )

    changes = compare_projection_versions(mdl, old, new)
    report = compare_projection_rebuild("orders", "OrderView", changes)

    assert report.severity == "migration_required"
    finding = next(f for f in report.findings if f.code == "expression_changed")
    assert finding.axis == "projection_rebuild"
    assert finding.severity == "migration_required"


def test_projection_rebuild_reports_breaking_storage_change_as_breaking():
    mdl, old, new = _projection_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            status: string
          }
          projection OrderView @ 1
            from orders.Order @ 1 as o
            where o.status == "active"
          {
            orderId <- o.orderId
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            status: string
          }
          projection OrderView @ 1
            from orders.Order @ 1 as o
            where o.status == "closed"
          {
            orderId <- o.orderId
          }
        }
        """,
    )

    changes = compare_projection_versions(mdl, old, new)
    report = compare_projection_rebuild("orders", "OrderView", changes)

    assert report.severity == "breaking"
    finding = next(f for f in report.findings if f.code == "where_changed")
    assert finding.axis == "projection_rebuild"
    assert finding.severity == "breaking"


def test_projection_rebuild_is_compatible_when_no_storage_or_lineage_change():
    mdl, old, new = _projection_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
          }
        }
        """,
    )

    changes = compare_projection_versions(mdl, old, new)
    report = compare_projection_rebuild("orders", "OrderView", changes)

    assert report.severity == "compatible"
    assert report.findings == []


def test_governance_review_reports_non_breaking_change_as_review_required():
    mdl, old, new = _projection_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            access {
              entity billing-team [read]
            }
          }
        }
        """,
    )

    changes = compare_projection_versions(mdl, old, new)
    report = compare_governance_review("orders", "OrderView", changes)

    assert report.severity == "review_required"
    finding = next(f for f in report.findings if f.code == "access_grant_added")
    assert finding.axis == "governance_review"
    assert finding.severity == "review_required"


def test_governance_review_reports_breaking_change_as_breaking():
    mdl, old, new = _projection_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            access {
              entity billing-team [read]
            }
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
          }
        }
        """,
    )

    changes = compare_projection_versions(mdl, old, new)
    report = compare_governance_review("orders", "OrderView", changes)

    assert report.severity == "breaking"
    finding = next(f for f in report.findings if f.code == "access_grant_removed")
    assert finding.axis == "governance_review"
    assert finding.severity == "breaking"


# --- Slice C4: configurable compatibility policy, wired into the CLI -------


def test_validate_compat_cli_grpc_migration_required_fails_by_default(tmp_path):
    old = _write(
        tmp_path / "old.mdl",
        """
domain billing {
  owner: "billing"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    customerId: uuid
    createdAt: timestamp
  }
  index Order @ 1 {
    primary orderId
    secondary by_customer {
      key: [customerId]
    }
  }
}
""",
    )
    new = _write(
        tmp_path / "new.mdl",
        """
domain billing {
  owner: "billing"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    customerId: uuid
    createdAt: timestamp
  }
  index Order @ 1 {
    primary orderId
    secondary by_customer {
      key: [customerId]
      sort: [createdAt desc]
    }
  }
}
""",
    )

    result = CliRunner().invoke(
        cli,
        ["validate-compat", "--from", str(old), "--to", str(new), "--target", "grpc"],
    )

    assert result.exit_code == 1
    assert "status: requires_read_rebuild" in result.output


def test_validate_compat_cli_policy_loosens_grpc_migration_required_to_pass(tmp_path):
    old = _write(
        tmp_path / "old.mdl",
        """
domain billing {
  owner: "billing"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    customerId: uuid
    createdAt: timestamp
  }
  index Order @ 1 {
    primary orderId
    secondary by_customer {
      key: [customerId]
    }
  }
}
""",
    )
    new = _write(
        tmp_path / "new.mdl",
        """
domain billing {
  owner: "billing"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    customerId: uuid
    createdAt: timestamp
  }
  index Order @ 1 {
    primary orderId
    secondary by_customer {
      key: [customerId]
      sort: [createdAt desc]
    }
  }
}
""",
    )
    policy = _write(
        tmp_path / "policy.yml",
        """
compatibility:
  grpc: breaking
""",
    )

    result = CliRunner().invoke(
        cli,
        [
            "validate-compat",
            "--from",
            str(old),
            "--to",
            str(new),
            "--target",
            "grpc",
            "--policy",
            str(policy),
        ],
    )

    assert result.exit_code == 0
    assert "policy: threshold=breaking -> pass" in result.output


def test_validate_compat_cli_policy_still_blocks_a_breaking_change(tmp_path):
    old = _write(
        tmp_path / "old.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    legacyStatus: string
  }
}
""",
    )
    new = _write(
        tmp_path / "new.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""",
    )
    # Deliberately as loose as the policy vocabulary allows -- still can't
    # let a breaking change through, since "breaking" is the maximum
    # severity rank and every valid threshold is <= it.
    policy = _write(
        tmp_path / "policy.yml",
        """
compatibility:
  protobuf: migration_required
""",
    )

    result = CliRunner().invoke(
        cli,
        [
            "validate-compat",
            "--from",
            str(old),
            "--to",
            str(new),
            "--target",
            "protobuf",
            "--policy",
            str(policy),
        ],
    )

    assert result.exit_code == 1
    assert "policy: threshold=migration_required -> fail" in result.output
    assert "removed_field_not_reserved" in result.output


def test_validate_compat_cli_rejects_an_invalid_policy_file(tmp_path):
    old = _write(
        tmp_path / "old.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""",
    )
    new = _write(
        tmp_path / "new.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""",
    )
    policy = _write(
        tmp_path / "policy.yml",
        """
compatibility:
  protobuf: super-strict
""",
    )

    result = CliRunner().invoke(
        cli,
        [
            "validate-compat",
            "--from",
            str(old),
            "--to",
            str(new),
            "--target",
            "protobuf",
            "--policy",
            str(policy),
        ],
    )

    assert result.exit_code != 0
    assert "unknown severity" in result.output


def test_governance_review_is_compatible_when_no_governance_change():
    mdl, old, new = _projection_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
          }
        }
        """,
    )

    changes = compare_projection_versions(mdl, old, new)
    report = compare_governance_review("orders", "OrderView", changes)

    assert report.severity == "compatible"
    assert report.findings == []
