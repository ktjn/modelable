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
        assert conn.execute("select name, owner from domains").fetchall() == [
            ("customer", "customer-platform")
        ]
        assert conn.execute("select domain_name, name, kind from models").fetchall() == [
            ("customer", "Customer", "entity")
        ]
        assert conn.execute(
            "select domain_name, model_name, version, change_kind from model_versions"
        ).fetchall() == [("customer", "Customer", 1, "additive")]
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
