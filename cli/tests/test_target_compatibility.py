from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from modelable.cli import cli
from modelable.compat.diff import compare_index_decls, compare_model_versions, compare_projection_versions
from modelable.compat.targets import (
    AXES,
    SEVERITIES,
    compare_governance_review,
    compare_grpc_artifacts,
    compare_projection_rebuild,
    compare_protobuf_manifests,
    compare_source_representation,
    compare_storage_migration,
)
from modelable.compiler.workspace import load_workspace
from modelable.emitters.grpc import emit_grpc
from modelable.emitters.protobuf import emit_protobuf
from modelable.parser.parse import parse_text_to_ir


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _protobuf_artifacts(path: Path):
    return emit_protobuf(load_workspace(path), path.parent / "out")


def _grpc_artifacts(path: Path):
    return emit_grpc(load_workspace(path), path.parent / "grpc-out")


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


def test_validate_compat_target_choices_match_the_registry():
    result = CliRunner().invoke(cli, ["validate-compat", "--help"])

    assert "protobuf" in result.output
    assert "grpc" in result.output


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
    finding = next(f for f in report.findings if f.code == "nullability_changed")
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
