from pathlib import Path

import pytest

from modelable.compiler.workspace import discover_mdl_files, load_workspace


def _write_model(path: Path, domain: str, model: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""
domain {domain} {{
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

    assert any("duplicate domain 'customer'" in error for _, error in workspace.errors)


def test_load_workspace_reports_duplicate_model_versions_across_files(tmp_path):
    _write_model(tmp_path / "customer-v1-a.mdl", "customer", "Customer")
    _write_model(tmp_path / "customer-v1-b.mdl", "customer", "Customer")

    workspace = load_workspace(tmp_path)

    assert any("duplicate model version customer.Customer@1" in error for _, error in workspace.errors)
