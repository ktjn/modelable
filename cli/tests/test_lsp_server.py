from lsprotocol import types

from modelable.lsp.server import initialize, server


def test_lsp_server_is_configured():
    assert server.name == "modelable-lsp"
    assert server.version == "0.1.0"
    assert hasattr(server, "index")


def test_lsp_server_advertises_completion():
    result = initialize(server, types.InitializeParams(capabilities=types.ClientCapabilities()))

    assert result.capabilities.completion_provider is not None
    assert result.capabilities.completion_provider.trigger_characters == ["@", "."]


def test_lsp_server_advertises_references():
    result = initialize(server, types.InitializeParams(capabilities=types.ClientCapabilities()))

    assert result.capabilities.references_provider is True


def test_lsp_server_advertises_document_symbols():
    result = initialize(server, types.InitializeParams(capabilities=types.ClientCapabilities()))

    assert result.capabilities.document_symbol_provider is True


def test_lsp_server_advertises_workspace_symbols():
    result = initialize(server, types.InitializeParams(capabilities=types.ClientCapabilities()))

    assert result.capabilities.workspace_symbol_provider is not None


def test_lsp_server_advertises_formatting():
    result = initialize(server, types.InitializeParams(capabilities=types.ClientCapabilities()))

    assert result.capabilities.document_formatting_provider is True


def test_lsp_server_advertises_rename():
    result = initialize(server, types.InitializeParams(capabilities=types.ClientCapabilities()))

    assert result.capabilities.rename_provider is not None
    assert result.capabilities.rename_provider.prepare_provider is True
