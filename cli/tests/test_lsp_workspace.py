from modelable.lsp.workspace import LspWorkspaceIndex, WorkspaceDocumentSource


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
""".strip("\n"),
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


def test_lsp_workspace_index_keeps_last_parseable_workspace_during_invalid_edit():
    index = LspWorkspaceIndex()
    uri = "inmemory://customer.mdl"
    workspace = index.upsert_document(
        uri,
        """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""",
    )

    after_invalid_edit = index.upsert_document(uri, "domain broken {")

    assert after_invalid_edit is workspace
    assert index.workspace is workspace
    assert index.documents[uri].text == "domain broken {"
    assert index.language.current_document(uri).version == 2
    assert not index.language.is_semantically_current()


def test_lsp_workspace_index_preserves_version_for_no_op_text_updates():
    index = LspWorkspaceIndex()
    uri = "inmemory://customer.mdl"
    index.upsert_document(uri, "")
    revision = index.language.revision

    index.upsert_document(uri, "")

    assert index.language.current_document(uri).version == 1
    assert index.language.revision == revision


def test_lsp_workspace_index_ignores_background_reload_for_user_opened_document():
    index = LspWorkspaceIndex()
    uri = "inmemory://customer.mdl"
    index.upsert_document(uri, "")

    index.load_background_document(uri, "domain background {}")

    assert index.documents[uri].text == ""
    assert index.language.current_document(uri).version == 1


def test_lsp_workspace_index_close_reloads_disk_and_increments_version(tmp_path):
    path = tmp_path / "workspace.mdl"
    path.write_text("", encoding="utf-8")
    uri = path.as_uri()
    index = LspWorkspaceIndex()
    index.upsert_document(uri, "domain broken {")
    path.write_text(
        """
domain customer {
  owner: "test-team"
}
""",
        encoding="utf-8",
    )

    workspace = index.close_document(uri)

    assert workspace is not None
    assert index.documents[uri].text == path.read_text(encoding="utf-8")
    assert index.language.current_document(uri).version == 2


def test_lsp_workspace_index_background_reload_increments_version():
    index = LspWorkspaceIndex()
    uri = "inmemory://customer.mdl"
    index.load_background_document(uri, "")

    index.load_background_document(uri, "domain customer {}")

    assert index.language.current_document(uri).version == 2


def test_lsp_workspace_index_keeps_public_document_mapping_mutations_live():
    index = LspWorkspaceIndex()
    uri = "inmemory://customer.mdl"
    workspace = index.upsert_document(
        uri,
        """
domain customer {
  owner: "test-team"
}
""",
    )

    index.documents[uri] = WorkspaceDocumentSource(
        path=None,
        uri=uri,
        text="domain broken {",
    )

    assert index.documents[uri].text == "domain broken {"
    assert index.language.current_document(uri).text == "domain broken {"
    assert index.language.current_document(uri).version == 2
    assert index.workspace is workspace

    del index.documents[uri]

    assert uri not in index.documents
    assert index.language.current_document(uri) is None
    assert index.workspace is None
