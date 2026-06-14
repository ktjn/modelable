import sqlite3
from pathlib import Path

from modelable.compiler.workspace import load_workspace
from modelable.registry.index import build_registry


def test_registry_package_exports_build_registry():
    from modelable.registry import build_registry as exported

    assert exported is build_registry


def _write_customer_model(path: Path) -> None:
    path.write_text(
        """
domain customer {
  owner: "customer-platform"

  entity Customer @ 1 (additive) {
    @key customerId: uuid
    @pii email?: string
    status: enum(active, blocked)
  }
}
""",
        encoding="utf-8",
    )


def test_build_registry_writes_sqlite_index(tmp_path):
    source = tmp_path / "customer.mdl"
    _write_customer_model(source)
    workspace = load_workspace(source)

    registry_path = build_registry(workspace, tmp_path / ".modelable")

    assert registry_path == tmp_path / ".modelable" / "registry.db"
    assert registry_path.exists()


def test_build_registry_populates_domain_model_versions_and_fields(tmp_path):
    source = tmp_path / "customer.mdl"
    _write_customer_model(source)
    workspace = load_workspace(source)
    registry_path = build_registry(workspace, tmp_path / ".modelable")

    with sqlite3.connect(registry_path) as conn:
        assert conn.execute("select name, owner from domains").fetchall() == [("customer", "customer-platform")]
        assert conn.execute("select domain_name, name, kind from models").fetchall() == [
            ("customer", "Customer", "entity")
        ]
        assert conn.execute("select domain_name, model_name, version, change_kind from model_versions").fetchall() == [
            ("customer", "Customer", 1, "additive")
        ]
        assert conn.execute(
            """
            select field_name, position, optional, is_key, is_pii
            from fields
            order by position
            """
        ).fetchall() == [
            ("customerId", 0, 0, 1, 0),
            ("email", 1, 1, 0, 1),
            ("status", 2, 0, 0, 0),
        ]


def test_build_registry_stores_classification(tmp_path):
    source = tmp_path / "payments.mdl"
    source.write_text(
        """
domain payments {
  owner: "test-team"
  entity Payment @ 1 (additive) {
    @key paymentId: uuid
    @classification("secret") cardNumber: string
    @classification("internal") amount: decimal(10, 2)
    currency: string
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(source)
    registry_path = build_registry(workspace, tmp_path / ".modelable")

    with sqlite3.connect(registry_path) as conn:
        rows = conn.execute("select field_name, classification from fields order by position").fetchall()
    assert rows == [
        ("paymentId", None),
        ("cardNumber", "secret"),
        ("amount", "internal"),
        ("currency", None),
    ]


def test_build_registry_populates_default_access_policies(tmp_path):
    source = tmp_path / "workspace.mdl"
    source.write_text(
        """
domain customer {
  owner: "customer-platform"

  entity Customer @ 1 (additive) {
    @key customerId: uuid
    legalName: string
  }
}

domain billing {
  owner: "billing-platform"

  projection BillingCustomer @ 1
    from customer.Customer @ 1 as c
  {
    billingCustomerId <- c.customerId
    name <- c.legalName
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(source)
    registry_path = build_registry(workspace, tmp_path / ".modelable")

    with sqlite3.connect(registry_path) as conn:
        rows = conn.execute(
            """
            select subject_ref, action, grantee
            from access_policies
            order by subject_ref, action, grantee
            """
        ).fetchall()

    assert rows == [
        ("billing.BillingCustomer@1", "manage_access", "billing-platform"),
        ("billing.BillingCustomer@1", "project", "billing"),
        ("billing.BillingCustomer@1", "read", "billing"),
        ("billing.BillingCustomer@1", "subscribe", "billing"),
        ("billing.BillingCustomer@1", "transfer", "billing-platform"),
        ("billing.BillingCustomer@1", "write", "billing-platform"),
        ("customer.Customer@1", "manage_access", "customer-platform"),
        ("customer.Customer@1", "project", "customer"),
        ("customer.Customer@1", "read", "customer"),
        ("customer.Customer@1", "subscribe", "customer"),
        ("customer.Customer@1", "transfer", "customer-platform"),
        ("customer.Customer@1", "write", "customer-platform"),
    ]


def test_build_registry_uses_explicit_access_policies(tmp_path):
    source = tmp_path / "workspace.mdl"
    source.write_text(
        """
domain customer {
  owner: "customer-platform"

  entity Customer @ 1 (additive) {
    @key customerId: uuid
    access {
      entity billing [read, project]
      property email billing [read]
    }
    email?: string
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(source)
    registry_path = build_registry(workspace, tmp_path / ".modelable")

    with sqlite3.connect(registry_path) as conn:
        rows = conn.execute(
            """
            select subject_ref, action, grantee
            from access_policies
            order by subject_ref, action, grantee
            """
        ).fetchall()

    assert rows == [
        ("customer.Customer@1", "project", "billing"),
        ("customer.Customer@1", "read", "billing"),
        ("customer.Customer@1.email", "read", "billing"),
    ]


def test_build_registry_populates_compatibility_reports(tmp_path):
    source = tmp_path / "workspace.mdl"
    source.write_text(
        """
domain customer {
  owner: "customer-platform"

  entity Customer @ 1 (additive) {
    @key customerId: uuid
    name: string
  }

  entity Customer @ 2 (breaking) {
    @key customerId: uuid
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(source)
    registry_path = build_registry(workspace, tmp_path / ".modelable")

    with sqlite3.connect(registry_path) as conn:
        rows = conn.execute(
            """
            select domain_name, model_name, from_version, to_version, status
            from compatibility_reports
            order by from_version, to_version
            """
        ).fetchall()

    assert rows == [("customer", "Customer", 1, 2, "breaking")]


def test_build_registry_populates_enum_compatibility_reports(tmp_path):
    source = tmp_path / "workspace.mdl"
    source.write_text(
        """
domain customer {
  owner: "customer-platform"

  entity Customer @ 1 (additive) {
    @key customerId: uuid
    status: enum(active, blocked)
  }

  entity Customer @ 2 (breaking) {
    @key customerId: uuid
    status: enum(active, blocked, archived)
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(source)
    registry_path = build_registry(workspace, tmp_path / ".modelable")

    with sqlite3.connect(registry_path) as conn:
        rows = conn.execute(
            """
            select domain_name, model_name, from_version, to_version, status
            from compatibility_reports
            order by from_version, to_version
            """
        ).fetchall()

    assert rows == [("customer", "Customer", 1, 2, "breaking")]


def test_build_registry_populates_lineage_edges(tmp_path):
    source = tmp_path / "workspace.mdl"
    source.write_text(
        """
domain customer {
  owner: "customer-platform"

  entity Customer @ 1 (additive) {
    @key customerId: uuid
    legalName: string
  }
}

domain billing {
  owner: "billing-platform"

  projection BillingCustomer @ 1
    from customer.Customer @ 1 as c
  {
    billingId <- c.customerId
    displayName = c.legalName
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(source)
    registry_path = build_registry(workspace, tmp_path / ".modelable")

    with sqlite3.connect(registry_path) as conn:
        rows = conn.execute(
            """
            select source_ref, target_ref, edge_kind
            from lineage_edges
            order by source_ref, target_ref
            """
        ).fetchall()

    assert rows == [
        (
            "customer.Customer@1.customerId",
            "billing.BillingCustomer@1.billingId",
            "direct",
        ),
        (
            "customer.Customer@1.legalName",
            "billing.BillingCustomer@1.displayName",
            "computed",
        ),
    ]
