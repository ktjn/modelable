import json
import sqlite3
from pathlib import Path

from modelable.compiler.workspace import load_workspace
from modelable.registry.index import build_registry
from modelable.registry.resolver import resolve_model_ref


def _write_workspace(path: Path) -> None:
    path.write_text(
        """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }

  entity Customer @ 2 (additive) {
    @key customerId: uuid
    email?: string
  }

  entity Customer @ 3 (additive) {
    @key customerId: uuid
    email?: string
    status?: string
  }
}

domain billing {
  owner: "test-team"
  projection BillingCustomer @ 1
    from customer.Customer @ >=1 <3 as c
  {
    billingCustomerId <- c.customerId
  }
}
""",
        encoding="utf-8",
    )


def test_resolve_model_ref_exact_version(tmp_path):
    source = tmp_path / "workspace.mdl"
    _write_workspace(source)
    workspace = load_workspace(source)

    resolved = resolve_model_ref(workspace.mdl, "customer.Customer", 2)

    assert resolved.domain_name == "customer"
    assert resolved.model_name == "Customer"
    assert resolved.version.version == 2


def test_resolve_model_ref_range_uses_highest_matching_version(tmp_path):
    source = tmp_path / "workspace.mdl"
    _write_workspace(source)
    workspace = load_workspace(source)
    projection = workspace.mdl.domains[1].projections["BillingCustomer"][0]

    resolved = resolve_model_ref(
        workspace.mdl,
        projection.source.model,
        projection.source.version,
    )

    assert resolved.version.version == 2


def test_load_workspace_reports_unresolved_projection_source(tmp_path):
    source = tmp_path / "workspace.mdl"
    source.write_text(
        """
domain billing {
  owner: "test-team"
  projection MissingCustomer @ 1
    from customer.Customer @ 1 as c
  {
    id <- c.customerId
  }
}
""",
        encoding="utf-8",
    )

    workspace = load_workspace(source)

    assert any(
        "unresolved model reference customer.Customer@1" in diagnostic.message for diagnostic in workspace.errors
    )


def test_build_registry_persists_resolved_source_versions(tmp_path):
    source = tmp_path / "workspace.mdl"
    _write_workspace(source)
    workspace = load_workspace(source)

    registry_path = build_registry(workspace, tmp_path / ".modelable")

    with sqlite3.connect(registry_path) as conn:
        [(source_version_json,)] = conn.execute(
            """
            select source_version_json
            from projection_versions
            where domain_name = 'billing' and projection_name = 'BillingCustomer'
            """
        ).fetchall()

    assert json.loads(source_version_json) == {"kind": "exact", "version": 2}
