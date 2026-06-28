from pathlib import Path

import pytest

from modelable.compiler.workspace import discover_mdl_files, load_workspace


def _write_model(path: Path, domain: str, model: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""
domain {domain} {{
  owner: "test-team"
  entity {model} @ 1 (additive) {{
    @key id: uuid
  }}
}}
""",
        encoding="utf-8",
    )


def test_discover_mdl_files_returns_single_file(tmp_path):
    mdl = tmp_path / "customer.mdl"
    _write_model(mdl, "customer", "Customer")

    assert discover_mdl_files(mdl) == [mdl]


def test_discover_mdl_files_returns_directory_files_in_stable_order(tmp_path):
    second = tmp_path / "z-last.mdl"
    first = tmp_path / "nested" / "a-first.mdl"
    ignored = tmp_path / "notes.txt"
    _write_model(second, "orders", "Order")
    _write_model(first, "customer", "Customer")
    ignored.write_text("not modelable", encoding="utf-8")

    assert discover_mdl_files(tmp_path) == [first, second]


def test_load_workspace_parses_all_discovered_files(tmp_path):
    _write_model(tmp_path / "customer.mdl", "customer", "Customer")
    _write_model(tmp_path / "orders.mdl", "orders", "Order")

    workspace = load_workspace(tmp_path)

    assert [source.path.name for source in workspace.sources] == [
        "customer.mdl",
        "orders.mdl",
    ]
    assert [domain.name for domain in workspace.mdl.domains] == ["customer", "orders"]
    assert workspace.errors == []


def test_discover_mdl_files_rejects_path_without_mdl_files(tmp_path):
    with pytest.raises(FileNotFoundError):
        discover_mdl_files(tmp_path)


def test_load_workspace_reports_duplicate_domains_across_files(tmp_path):
    _write_model(tmp_path / "customer-a.mdl", "customer", "Customer")
    _write_model(tmp_path / "customer-b.mdl", "customer", "CustomerProfile")

    workspace = load_workspace(tmp_path)

    assert any("duplicate domain 'customer'" in diagnostic.message for diagnostic in workspace.errors)


def test_load_workspace_reports_duplicate_model_versions_across_files(tmp_path):
    _write_model(tmp_path / "customer-v1-a.mdl", "customer", "Customer")
    _write_model(tmp_path / "customer-v1-b.mdl", "customer", "Customer")

    workspace = load_workspace(tmp_path)

    assert any("duplicate model version customer.Customer@1" in diagnostic.message for diagnostic in workspace.errors)


def test_load_workspace_reports_auto_projection_generated_name_conflict(tmp_path):
    mdl = tmp_path / "customer.mdl"
    mdl.write_text(
        """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }

  auto projections Customer @ 1 {
    db
    request
    reply
    event
  }

  projection CustomerReply @ 1
    from customer.Customer @ 1 as c
  {
    customerId <- c.customerId
  }
}
""",
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)

    assert any(
        "generated projection name customer.CustomerReply@1 conflicts" in diagnostic.message
        for diagnostic in workspace.errors
    )


def test_load_workspace_deduplicates_identical_bindings_across_files(tmp_path):
    (tmp_path / "customer.mdl").write_text(
        """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}

binding pg-conn {
  adapter: postgres
}

binding customer-pg {
  adapter: pg-conn
  model: customer.Customer @ 1
  table: "customers"
}
""",
        encoding="utf-8",
    )
    (tmp_path / "order.mdl").write_text(
        """
domain order {
  owner: "test-team"
  entity Order @ 1 (additive) {
    @key orderId: uuid
  }
}

binding pg-conn {
  adapter: postgres
}

binding order-pg {
  adapter: pg-conn
  model: order.Order @ 1
  table: "orders"
}
""",
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)
    assert not workspace.errors
    # identical pg-conn bindings must be deduplicated to a single entry
    pg_conn_count = sum(1 for b in workspace.mdl.bindings if b.name == "pg-conn")
    assert pg_conn_count == 1


def test_load_workspace_errors_on_conflicting_binding_definitions(tmp_path):
    (tmp_path / "a.mdl").write_text(
        """
domain alpha {
  owner: "test-team"
  entity Alpha @ 1 (additive) {
    @key alphaId: uuid
  }
}

binding shared-conn {
  adapter: postgres
}
""",
        encoding="utf-8",
    )
    (tmp_path / "b.mdl").write_text(
        """
domain beta {
  owner: "test-team"
  entity Beta @ 1 (additive) {
    @key betaId: uuid
  }
}

binding shared-conn {
  adapter: clickhouse
}
""",
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)
    # same binding name with different adapter is a conflict
    assert any("binding 'shared-conn'" in d.message for d in workspace.errors)
