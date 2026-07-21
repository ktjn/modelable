import json

import pytest

import modelable.browser.dispatch as browser_dispatch
from modelable.browser import (
    dispatch_browser_request,
)
from modelable.browser.graph import build_browser_graph
from modelable.compiler.workspace import load_workspace

VALID_SOURCE = (
    "domain customer {\n"
    '  owner: "team"\n'
    "  entity Customer @ 1 (additive) {\n"
    "    @key customerId: uuid\n"
    "    name: string\n"
    "  }\n"
    "\n"
    "  projection CustomerView @ 1\n"
    "    from customer.Customer @ 1 as c\n"
    "  {\n"
    "    customerId <- c.customerId\n"
    "    displayName = c.name\n"
    "  }\n"
    "}\n"
)
URI = "file:///customer.mdl"
SOURCES = [{"uri": URI, "text": VALID_SOURCE, "version": 1}]


@pytest.fixture(autouse=True)
def reset_browser_dispatch():
    browser_dispatch._reset_compiler_for_tests()


def dispatch(method, payload):
    return json.loads(dispatch_browser_request(method, json.dumps(payload)))


def open_workspace(revision=100):
    result = dispatch("workspace.open", {"workspaceRevision": revision, "sources": SOURCES})
    assert result["ok"]
    return result


def test_graph_domain_mode_excludes_version_and_field_nodes():
    open_workspace()
    result = dispatch("workspace.graph", {"workspaceRevision": 100, "mode": "domain"})

    assert result["ok"]
    graph = result["result"]["graph"]
    assert graph["schema_version"] == 1
    node_kinds = {node["kind"] for node in graph["nodes"]}
    assert node_kinds <= {"domain", "entity", "projection"}
    assert "version" not in node_kinds
    assert "field" not in node_kinds


def test_graph_entity_mode_includes_all_node_kinds():
    open_workspace()
    result = dispatch("workspace.graph", {"workspaceRevision": 100, "mode": "entity"})

    assert result["ok"]
    graph = result["result"]["graph"]
    node_kinds = {node["kind"] for node in graph["nodes"]}
    assert "domain" in node_kinds
    assert "entity" in node_kinds
    assert "version" in node_kinds
    assert "field" in node_kinds
    assert "projection" in node_kinds


def test_graph_maps_node_kinds_correctly():
    open_workspace()
    result = dispatch("workspace.graph", {"workspaceRevision": 100, "mode": "entity"})

    graph = result["result"]["graph"]
    node_kinds = [node["kind"] for node in graph["nodes"]]
    assert "domain" in node_kinds
    assert "entity" in node_kinds
    assert "version" in node_kinds
    assert "field" in node_kinds
    assert "projection" in node_kinds
    for node in graph["nodes"]:
        assert node["kind"] not in {"model", "model_version", "projection_version", "projection_field"}


def test_graph_maps_edge_kinds_correctly():
    open_workspace()
    result = dispatch("workspace.graph", {"workspaceRevision": 100, "mode": "entity"})

    graph = result["result"]["graph"]
    edge_kinds = {edge["kind"] for edge in graph["edges"]}
    assert "contains" in edge_kinds
    assert "projects" in edge_kinds
    for edge in graph["edges"]:
        assert edge["kind"] not in {
            "owns",
            "version_of",
            "contains_field",
            "has_projection",
            "version_of_projection",
            "maps_to",
        }


def test_graph_edge_ids_are_deterministic():
    open_workspace()
    result1 = dispatch("workspace.graph", {"workspaceRevision": 100, "mode": "entity"})
    open_workspace(101)
    result2 = dispatch("workspace.graph", {"workspaceRevision": 101, "mode": "entity"})

    ids1 = [edge["id"] for edge in result1["result"]["graph"]["edges"]]
    ids2 = [edge["id"] for edge in result2["result"]["graph"]["edges"]]
    assert ids1 == ids2


def test_graph_nodes_have_metadata():
    open_workspace()
    result = dispatch("workspace.graph", {"workspaceRevision": 100, "mode": "entity"})

    graph = result["result"]["graph"]
    entity_nodes = [n for n in graph["nodes"] if n["kind"] == "entity"]
    assert len(entity_nodes) >= 1
    assert "domain" in entity_nodes[0]["metadata"]
    assert "name" in entity_nodes[0]["metadata"]


def test_graph_source_range_is_null():
    open_workspace()
    result = dispatch("workspace.graph", {"workspaceRevision": 100, "mode": "entity"})

    for node in result["result"]["graph"]["nodes"]:
        assert node["source_range"] is None


def test_graph_returns_workspace_revision_and_mode():
    open_workspace()
    result = dispatch("workspace.graph", {"workspaceRevision": 100, "mode": "domain"})

    assert result["result"]["workspace_revision"] == 100
    assert result["result"]["mode"] == "domain"


def test_graph_rejects_stale_workspace():
    open_workspace(50)
    result = dispatch("workspace.graph", {"workspaceRevision": 49, "mode": "domain"})

    assert not result["ok"]
    assert result["error"]["code"] == "STALE_WORKSPACE"


def test_graph_rejects_invalid_mode():
    open_workspace()
    result = dispatch("workspace.graph", {"workspaceRevision": 100, "mode": "invalid"})

    assert not result["ok"]
    assert result["error"]["code"] == "INVALID_REQUEST"


def test_graph_rejects_missing_fields():
    open_workspace()
    result = dispatch("workspace.graph", {"workspaceRevision": 100})

    assert not result["ok"]
    assert result["error"]["code"] == "INVALID_REQUEST"


def test_graph_rejects_extra_fields():
    open_workspace()
    result = dispatch("workspace.graph", {"workspaceRevision": 100, "mode": "domain", "extra": True})

    assert not result["ok"]
    assert result["error"]["code"] == "INVALID_REQUEST"


def test_graph_empty_workspace_returns_empty_graph():
    empty_source = 'domain empty {\n  owner: "team"\n}\n'
    dispatch(
        "workspace.open", {"workspaceRevision": 100, "sources": [{"uri": URI, "text": empty_source, "version": 1}]}
    )
    result = dispatch("workspace.graph", {"workspaceRevision": 100, "mode": "entity"})

    assert result["ok"]
    graph = result["result"]["graph"]
    assert len(graph["nodes"]) == 1
    assert graph["nodes"][0]["kind"] == "domain"
    assert len(graph["edges"]) == 0


def test_build_browser_graph_directly(tmp_path):
    mdl = tmp_path / "workspace.mdl"
    mdl.write_text(VALID_SOURCE, encoding="utf-8")
    workspace = load_workspace(tmp_path)
    result = build_browser_graph(workspace, "entity", 42)

    assert result.workspace_revision == 42
    assert result.mode == "entity"
    assert result.graph.schema_version == 1
    assert len(result.graph.nodes) > 0
    assert len(result.graph.edges) > 0
    assert all(node.kind in {"domain", "entity", "version", "field", "projection"} for node in result.graph.nodes)
    assert all(edge.kind in {"contains", "projects"} for edge in result.graph.edges)
