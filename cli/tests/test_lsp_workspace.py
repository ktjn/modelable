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


def _source(uri: str, domain: str) -> WorkspaceDocumentSource:
    return WorkspaceDocumentSource(
        path=None,
        uri=uri,
        text=f'domain {domain} {{\n  owner: "test-team"\n}}',
    )


def _assert_document_snapshots_match(index: LspWorkspaceIndex) -> None:
    assert {uri: source.text for uri, source in index.documents.items()} == {
        uri: document.text for uri, document in index.language.documents.items()
    }


def test_lsp_document_mapping_update_mediates_changes_and_no_ops():
    index = LspWorkspaceIndex()
    first_uri = "inmemory://a.mdl"
    second_uri = "inmemory://b.mdl"
    first = _source(first_uri, "first")
    second = _source(second_uri, "second")

    index.documents.update({second_uri: second, first_uri: first})

    assert index.language.revision == 2
    assert index.language.current_document(first_uri).version == 1
    assert index.language.current_document(second_uri).version == 1
    _assert_document_snapshots_match(index)

    index.documents.update({first_uri: first})

    assert index.language.revision == 2
    assert index.language.current_document(first_uri).version == 1
    _assert_document_snapshots_match(index)


def test_lsp_document_mapping_setdefault_mediates_insert_and_existing_no_op():
    index = LspWorkspaceIndex()
    uri = "inmemory://a.mdl"
    source = _source(uri, "first")

    inserted = index.documents.setdefault(uri, source)
    revision = index.language.revision
    existing = index.documents.setdefault(uri, _source(uri, "replacement"))

    assert inserted == source
    assert existing == source
    assert revision == 1
    assert index.language.revision == revision
    assert index.language.current_document(uri).version == 1
    _assert_document_snapshots_match(index)


def test_lsp_document_mapping_pop_mediates_removal_and_missing_no_op():
    index = LspWorkspaceIndex()
    first_uri = "inmemory://a.mdl"
    second_uri = "inmemory://b.mdl"
    index.upsert_document(first_uri, _source(first_uri, "first").text)
    index.upsert_document(second_uri, _source(second_uri, "second").text)

    removed = index.documents.pop(first_uri)
    revision = index.language.revision
    missing = index.documents.pop("inmemory://missing.mdl", None)

    assert removed.uri == first_uri
    assert missing is None
    assert revision == 3
    assert index.language.revision == revision
    _assert_document_snapshots_match(index)


def test_lsp_document_mapping_popitem_mediates_removal():
    index = LspWorkspaceIndex()
    first_uri = "inmemory://a.mdl"
    second_uri = "inmemory://b.mdl"
    index.upsert_document(first_uri, _source(first_uri, "first").text)
    index.upsert_document(second_uri, _source(second_uri, "second").text)

    removed_uri, removed = index.documents.popitem()

    assert removed_uri in {first_uri, second_uri}
    assert removed.uri == removed_uri
    assert index.language.revision == 3
    _assert_document_snapshots_match(index)


def test_lsp_document_mapping_clear_mediates_each_removal_and_rebuilds():
    index = LspWorkspaceIndex()
    first_uri = "inmemory://a.mdl"
    second_uri = "inmemory://b.mdl"
    index.upsert_document(first_uri, _source(first_uri, "first").text)
    index.upsert_document(second_uri, _source(second_uri, "second").text)

    index.documents.clear()

    assert index.language.revision == 4
    assert index.workspace is None
    _assert_document_snapshots_match(index)


def test_lsp_document_mapping_in_place_union_mediates_change_and_no_op():
    index = LspWorkspaceIndex()
    uri = "inmemory://a.mdl"
    source = _source(uri, "first")

    index.documents |= {uri: source}
    revision = index.language.revision
    index.documents |= {uri: source}

    assert revision == 1
    assert index.language.revision == revision
    assert index.language.current_document(uri).version == 1
    _assert_document_snapshots_match(index)
