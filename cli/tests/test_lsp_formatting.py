from modelable.lsp.formatting import build_document_formatting
from modelable.lsp.workspace import LspWorkspaceIndex

MESSY_TEXT = """
domain customer {
  owner: "test-team"
entity Customer @ 1 (additive) {
@key customerId: uuid
email?: string
}
}
""".strip(
    "\n"
)


def test_document_formatting_reindents_nested_blocks():
    index = LspWorkspaceIndex()
    index.upsert_document("inmemory://workspace.mdl", MESSY_TEXT)

    edits = build_document_formatting(index, "inmemory://workspace.mdl", tab_size=2, insert_spaces=True)

    assert edits is not None
    assert len(edits) == 1
    assert edits[0].new_text == (
        "domain customer {\n"
        '  owner: "test-team"\n'
        "  entity Customer @ 1 (additive) {\n"
        "    @key customerId: uuid\n"
        "    email?: string\n"
        "  }\n"
        "}"
    )


def test_document_formatting_returns_none_for_unknown_uri():
    index = LspWorkspaceIndex()

    edits = build_document_formatting(index, "inmemory://unknown.mdl", tab_size=2, insert_spaces=True)

    assert edits is None


def test_document_formatting_returns_empty_for_already_formatted_text():
    already_formatted = (
        "domain customer {\n"
        "  entity Customer @ 1 (additive) {\n"
        "    @key customerId: uuid\n"
        "  }\n"
        "}"
    )
    index = LspWorkspaceIndex()
    index.upsert_document("inmemory://workspace.mdl", already_formatted)

    edits = build_document_formatting(index, "inmemory://workspace.mdl", tab_size=2, insert_spaces=True)

    assert edits == []


def test_document_formatting_uses_tab_indentation():
    index = LspWorkspaceIndex()
    index.upsert_document("inmemory://workspace.mdl", MESSY_TEXT)

    edits = build_document_formatting(index, "inmemory://workspace.mdl", tab_size=4, insert_spaces=False)

    assert edits is not None
    assert len(edits) == 1
    assert edits[0].new_text == (
        "domain customer {\n"
        '\towner: "test-team"\n'
        "\tentity Customer @ 1 (additive) {\n"
        "\t\t@key customerId: uuid\n"
        "\t\temail?: string\n"
        "\t}\n"
        "}"
    )
