from modelable.compiler.workspace import WorkspaceDocumentSource, load_workspace_from_sources
from modelable.lsp.workspace import LspWorkspaceIndex


def test_lsp_workspace_index_rebuilds_from_in_memory_documents():
    index = LspWorkspaceIndex()
    workspace = index.upsert_document(
        "inmemory://customer.mdl",
        """
domain customer {
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
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""",
    )

    assert index.remove_document("inmemory://customer.mdl") is None
    assert index.workspace is None

