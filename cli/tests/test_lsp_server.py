from modelable.lsp.server import server


def test_lsp_server_is_configured():
    assert server.name == "modelable-lsp"
    assert server.version == "0.1.0"
    assert hasattr(server, "index")

