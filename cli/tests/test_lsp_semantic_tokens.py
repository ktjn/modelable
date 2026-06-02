from __future__ import annotations

from types import SimpleNamespace
from importlib import import_module

from lsprotocol import types

lsp_server = import_module("modelable.lsp.server")
semantic_tokens = import_module("modelable.lsp.semantic_tokens")


SOURCE = """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    name?: string = "Alice" // comment
  }

  projection CustomerView @ 1 {
    from customer.Customer @ 1 as c
    fullName <- c.name
  }
}
""".strip(
    "\n"
)


def test_lsp_server_advertises_semantic_tokens():
    result = lsp_server.initialize(
        lsp_server.server, types.InitializeParams(capabilities=types.ClientCapabilities())
    )

    provider = result.capabilities.semantic_tokens_provider
    assert provider is not None
    assert provider.legend.token_types == [
        "namespace",
        "class",
        "property",
        "parameter",
        "variable",
        "type",
        "keyword",
        "decorator",
        "comment",
        "string",
        "number",
        "operator",
    ]


def test_semantic_tokens_highlight_model_keywords_names_and_literals():
    tokens = _decode_semantic_tokens(semantic_tokens.build_semantic_tokens(SOURCE).data)
    lines = SOURCE.splitlines()

    assert _token_type_at(tokens, _line_index(lines, "domain customer {"), lines[0].index("customer")) == "namespace"
    assert _token_type_at(tokens, _line_index(lines, "  entity Customer @ 1 (additive) {"), lines[2].index("Customer")) == "class"
    assert _token_type_at(tokens, _line_index(lines, "    @key customerId: uuid"), lines[3].index("@key")) == "decorator"
    assert _token_type_at(tokens, _line_index(lines, "    @key customerId: uuid"), lines[3].index("uuid")) == "type"
    assert _token_type_at(tokens, _line_index(lines, '    name?: string = "Alice" // comment'), lines[4].index('"Alice"')) == "string"
    assert _token_type_at(tokens, _line_index(lines, '    name?: string = "Alice" // comment'), lines[4].index("// comment")) == "comment"
    assert _token_type_at(tokens, _line_index(lines, "  projection CustomerView @ 1 {"), lines[7].index("CustomerView")) == "class"
    assert _token_type_at(tokens, _line_index(lines, "    from customer.Customer @ 1 as c"), lines[8].index("from")) == "keyword"
    assert _token_type_at(tokens, _line_index(lines, "    from customer.Customer @ 1 as c"), lines[8].index("customer")) == "namespace"
    assert _token_type_at(tokens, _line_index(lines, "    from customer.Customer @ 1 as c"), lines[8].rindex("c")) == "parameter"
    assert _token_type_at(tokens, _line_index(lines, "    fullName <- c.name"), lines[9].index("fullName")) == "property"
    assert _token_type_at(tokens, _line_index(lines, "    fullName <- c.name"), lines[9].index("c.")) == "variable"
    assert _token_type_at(tokens, _line_index(lines, "    fullName <- c.name"), lines[9].rindex("name")) == "property"


def test_semantic_tokens_full_handler_uses_open_buffer_text():
    uri = "file:///workspace/customer.mdl"
    inner_index = SimpleNamespace(
        documents={uri: SimpleNamespace(text=SOURCE)},
    )
    ls = SimpleNamespace(
        index_for=lambda _uri: inner_index,
    )

    result = lsp_server.semantic_tokens_full(
        ls, types.SemanticTokensParams(text_document=types.TextDocumentIdentifier(uri=uri))
    )

    assert result is not None
    assert result.data == semantic_tokens.build_semantic_tokens(SOURCE).data


def _decode_semantic_tokens(data: list[int]) -> list[tuple[int, int, int, str]]:
    legend = semantic_tokens.semantic_tokens_legend().token_types
    tokens: list[tuple[int, int, int, str]] = []
    line = 0
    start = 0
    for index in range(0, len(data), 5):
        delta_line, delta_start, length, token_type_index, _modifiers = data[index : index + 5]
        if delta_line == 0:
            start += delta_start
        else:
            line += delta_line
            start = delta_start
        tokens.append((line, start, length, legend[token_type_index]))
    return tokens


def _token_type_at(tokens: list[tuple[int, int, int, str]], line: int, start: int) -> str:
    match = next(token for token in tokens if token[0] == line and token[1] == start)
    return match[3]


def _line_index(lines: list[str], needle: str) -> int:
    return next(index for index, line in enumerate(lines) if line == needle)
