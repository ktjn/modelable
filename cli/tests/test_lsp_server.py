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
