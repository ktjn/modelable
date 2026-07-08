import json

from modelable.compiler.workspace import load_workspace
from modelable.registry.ids import allocate_registry_ids, read_lock_file, write_lock_file


def _write_mdl(path, text):
    path.write_text(text, encoding="utf-8")


def test_allocate_assigns_ids_in_domain_then_name_order(tmp_path):
    mdl_path = tmp_path / "test.mdl"
    _write_mdl(
        mdl_path,
        """
domain platform {
  owner: "test-team"
  semantic SchemaId : u32 { registry: true }
  semantic CommandId : u32 { registry: true }
}

domain billing {
  owner: "test-team"
  semantic InvoiceKind : u8 { registry: true }
}
""",
    )
    workspace = load_workspace(mdl_path)
    ids = allocate_registry_ids(workspace.mdl, {})
    assert ids == {
        "billing.InvoiceKind": 1,
        "platform.CommandId": 2,
        "platform.SchemaId": 3,
    }


def test_allocate_never_reassigns_existing_ids(tmp_path):
    mdl_path = tmp_path / "test.mdl"
    _write_mdl(
        mdl_path,
        """
domain platform {
  owner: "test-team"
  semantic SchemaId : u32 { registry: true }
  semantic CommandId : u32 { registry: true }
}
""",
    )
    workspace = load_workspace(mdl_path)
    ids = allocate_registry_ids(workspace.mdl, {"platform.SchemaId": 7})
    assert ids["platform.SchemaId"] == 7
    assert ids["platform.CommandId"] == 8


def test_allocate_ignores_non_registry_semantic_types(tmp_path):
    mdl_path = tmp_path / "test.mdl"
    _write_mdl(
        mdl_path,
        """
domain platform {
  owner: "test-team"
  semantic ModuleId : u32
  semantic SchemaId : u32 { registry: true }
}
""",
    )
    workspace = load_workspace(mdl_path)
    ids = allocate_registry_ids(workspace.mdl, {})
    assert ids == {"platform.SchemaId": 1}


def test_allocate_raises_on_orphaned_id_by_default(tmp_path):
    mdl_path = tmp_path / "test.mdl"
    _write_mdl(
        mdl_path,
        """
domain platform {
  owner: "test-team"
  semantic SchemaId : u32 { registry: true }
}
""",
    )
    workspace = load_workspace(mdl_path)
    try:
        allocate_registry_ids(workspace.mdl, {"platform.CommandId": 1, "platform.SchemaId": 2})
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "platform.CommandId" in str(exc)


def test_allocate_keeps_orphaned_id_unreused_when_allowed(tmp_path):
    mdl_path = tmp_path / "test.mdl"
    _write_mdl(
        mdl_path,
        """
domain platform {
  owner: "test-team"
  semantic SchemaId : u32 { registry: true }
}
""",
    )
    workspace = load_workspace(mdl_path)
    ids = allocate_registry_ids(
        workspace.mdl,
        {"platform.CommandId": 1, "platform.SchemaId": 2},
        allow_orphaned=True,
    )
    assert ids == {"platform.CommandId": 1, "platform.SchemaId": 2}
    # A later new registration must not reuse the orphaned id.
    _write_mdl(
        mdl_path,
        """
domain platform {
  owner: "test-team"
  semantic SchemaId : u32 { registry: true }
  semantic EventId : u32 { registry: true }
}
""",
    )
    workspace2 = load_workspace(mdl_path)
    ids2 = allocate_registry_ids(workspace2.mdl, ids, allow_orphaned=True)
    assert ids2["platform.EventId"] == 3


def test_read_lock_file_missing_returns_empty(tmp_path):
    assert read_lock_file(tmp_path / "registry-ids.lock") == {}


def test_write_then_read_lock_file_round_trips_sorted_by_id(tmp_path):
    path = tmp_path / "registry-ids.lock"
    write_lock_file(path, {"b.Z": 2, "a.A": 1})
    raw = path.read_text(encoding="utf-8")
    assert list(json.loads(raw).keys()) == ["a.A", "b.Z"]
    assert read_lock_file(path) == {"a.A": 1, "b.Z": 2}
