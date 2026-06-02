from modelable.compiler.workspace import WorkspaceDocumentSource, load_workspace_from_sources
from modelable.lsp.workspace import LspWorkspaceIndex


def test_lsp_workspace_index_normalizes_file_uri_paths(tmp_path):
    path = tmp_path / "workspace.mdl"
    path.write_text(
        """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""".strip(
            "\n"
        ),
        encoding="utf-8",
    )

    index = LspWorkspaceIndex()
    index.upsert_document(path.as_uri(), path.read_text(encoding="utf-8"))

    assert index.documents[path.as_uri()].path == path


def test_lsp_workspace_index_rebuilds_from_in_memory_documents():
    index = LspWorkspaceIndex()
    workspace = index.upsert_document(
        "inmemory://customer.mdl",
        """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""",
    )

    assert workspace is not None
    assert workspace.mdl.domains[0].name == "customer"
    assert index.workspace is workspace


def test_lsp_workspace_index_removes_documents():
    index = LspWorkspaceIndex()
    index.upsert_document(
        "inmemory://customer.mdl",
        """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""",
    )

    assert index.remove_document("inmemory://customer.mdl") is None
    assert index.workspace is None
