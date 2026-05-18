from modelable.lsp.formatting import build_document_formatting
from modelable.lsp.workspace import LspWorkspaceIndex


MESSY_TEXT = """
domain customer {
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
        "  entity Customer @ 1 (additive) {\n"
        "    @key customerId: uuid\n"
        "    email?: string\n"
        "  }\n"
        "}"
    )
