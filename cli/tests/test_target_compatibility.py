from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from click.testing import CliRunner

from modelable.cli import cli
from modelable.compat.diff import compare_index_decls, compare_model_versions, compare_projection_versions
from modelable.compat.targets import (
    AXES,
    SEVERITIES,
    compare_governance_review,
    compare_grpc_artifacts,
    compare_model_storage_migration,
    compare_openapi_artifacts,
    compare_projection_rebuild,
    compare_protobuf_manifests,
    compare_semantic_compatibility,
    compare_source_representation,
    compare_storage_migration,
)
from modelable.compiler.workspace import load_workspace
from modelable.consequence_protocol import validate_consequence_graph
from modelable.emitters.base import EmittedArtifact
from modelable.emitters.grpc import emit_grpc
from modelable.emitters.openapi import emit_openapi
from modelable.emitters.protobuf import emit_protobuf
from modelable.parser.parse import parse_text_to_ir


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _openapi_artifacts(path: Path):
    return emit_openapi(load_workspace(path), path.parent / "out")


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
