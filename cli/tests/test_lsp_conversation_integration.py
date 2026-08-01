from __future__ import annotations

import contextlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
from helpers import SERVER_CMD
from lsprotocol import types
from pygls.exceptions import JsonRpcInternalError
from pytest_lsp.client import make_test_lsp_client

from modelable.lsp.conversation_protocol import APPLY_METHOD, CLOSE_METHOD, TURN_METHOD
from modelable.rag.index import build_documentation_index
from modelable.rag.model import DocumentationChunk


def _make_documentation_index(root: Path) -> Path:
    index = root / "search-index"
    build_documentation_index(
        [
            DocumentationChunk(
                external_id="guide.md#install",
                source_path="guide.md",
                url="https://example.test/guide/#install",
                language="en",
                title="Guide",
                heading="Install",
                heading_path=["Guide", "Install"],
                content="Install with uv.",
                chunk_index=0,
            )
        ],
        index,
    )
    return index / "manifest.json"


@contextlib.contextmanager
def _fake_ollama_server(*, response_text: str):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            if self.path != "/api/chat":
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(length)
            payload = json.dumps({"message": {"content": response_text}}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: object) -> None:
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


async def test_conversation_focus_and_close_over_real_json_rpc(tmp_path: Path) -> None:
    source = tmp_path / "customer.mdl"
    source.write_text(
        "domain customer {\n"
        '  owner: "customer-team"\n'
        "  entity Customer @ 1 (additive) {\n"
        "    @key customerId: uuid\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    client = make_test_lsp_client()
    await client.start_io(*SERVER_CMD)
    await client.initialize_session(
        types.InitializeParams(
            capabilities=types.ClientCapabilities(),
            root_uri=tmp_path.as_uri(),
            workspace_folders=[types.WorkspaceFolder(uri=tmp_path.as_uri(), name=tmp_path.name)],
        )
    )
    payload = {
        "protocolVersion": 2,
        "sessionId": "integration-session",
        "createSession": True,
        "workspaceUri": tmp_path.as_uri(),
        "message": "is the workspace valid?",
        "activeDocumentUri": source.as_uri(),
        "position": {"line": 3, "character": 8},
        "dirtyDocumentUris": [],
    }
    try:
        client.text_document_did_open(
            types.DidOpenTextDocumentParams(
                text_document=types.TextDocumentItem(
                    uri=source.as_uri(),
                    language_id="mdl",
                    version=1,
                    text=source.read_text(encoding="utf-8"),
                )
            )
        )
        await client.wait_for_notification(types.TEXT_DOCUMENT_PUBLISH_DIAGNOSTICS)
        reply = await client.protocol.send_request_async(TURN_METHOD, payload)

        assert reply.kind == "answer"
        assert reply.focusedRef == "customer.Customer@1"

        close_payload = {
            "protocolVersion": 2,
            "sessionId": "integration-session",
        }
        assert await client.protocol.send_request_async(CLOSE_METHOD, close_payload) is None
        assert await client.protocol.send_request_async(CLOSE_METHOD, close_payload) is None

        with pytest.raises(JsonRpcInternalError, match="expired"):
            await client.protocol.send_request_async(
                TURN_METHOD,
                {
                    **payload,
                    "createSession": False,
                },
            )
    finally:
        await client.shutdown_session()


async def test_compilation_preview_and_apply_over_real_json_rpc(tmp_path: Path) -> None:
    source = tmp_path / "customer.mdl"
    source.write_text(
        "domain customer {\n"
        '  owner: "customer-team"\n'
        "  entity Customer @ 1 (additive) {\n"
        "    @key customerId: uuid\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    client = make_test_lsp_client()
    await client.start_io(*SERVER_CMD)
    await client.initialize_session(
        types.InitializeParams(
            capabilities=types.ClientCapabilities(),
            root_uri=tmp_path.as_uri(),
            workspace_folders=[types.WorkspaceFolder(uri=tmp_path.as_uri(), name=tmp_path.name)],
        )
    )
    try:
        preview = await client.protocol.send_request_async(
            TURN_METHOD,
            {
                "protocolVersion": 2,
                "sessionId": "compile-session",
                "createSession": True,
                "workspaceUri": tmp_path.as_uri(),
                "message": "/compile rust",
                "activeDocumentUri": source.as_uri(),
                "position": {"line": 3, "character": 8},
                "dirtyDocumentUris": [],
            },
        )

        assert preview.protocolVersion == 2
        assert preview.kind == "preview"
        assert preview.operationKind == "compile"
        assert preview.changeSetId
        assert preview.compilationFiles
        assert all(item.uri.startswith(tmp_path.resolve().as_uri()) for item in preview.compilationFiles)
        assert (
            preview.auditUri
            == (tmp_path / ".modelable" / "audit" / "compilations" / f"{preview.changeSetId}.json").resolve().as_uri()
        )
        assert not (tmp_path / "dist" / "rust").exists()

        applied = await client.protocol.send_request_async(
            APPLY_METHOD,
            {
                "protocolVersion": 2,
                "sessionId": "compile-session",
                "changeSetId": preview.changeSetId,
                "dirtyDocumentUris": [],
            },
        )

        assert applied.kind == "applied"
        assert applied.operationKind == "compile"
        assert applied.auditUri.startswith((tmp_path / ".modelable" / "audit").resolve().as_uri())
        assert (tmp_path / "dist" / "rust").exists()
    finally:
        await client.shutdown_session()


async def test_docs_turn_uses_bound_documentation_index_over_real_json_rpc(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "customer.mdl"
    source.write_text(
        "domain customer {\n"
        '  owner: "customer-team"\n'
        "  entity Customer @ 1 (additive) {\n"
        "    @key customerId: uuid\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    (tmp_path / "workspace.mdl").write_text(
        'workspace default {\n  name: "example"\n  ai {\n    provider: "ollama"\n    model: "docs-test"\n  }\n}\n',
        encoding="utf-8",
    )
    docs_index = _make_documentation_index(tmp_path)
    client = make_test_lsp_client()
    with _fake_ollama_server(response_text="Use [S1] to install it.") as base_url:
        monkeypatch.setenv("OLLAMA_HOST", base_url)
        await client.start_io(*SERVER_CMD)
        await client.initialize_session(
            types.InitializeParams(
                capabilities=types.ClientCapabilities(),
                root_uri=tmp_path.as_uri(),
                workspace_folders=[types.WorkspaceFolder(uri=tmp_path.as_uri(), name=tmp_path.name)],
            )
        )
        try:
            reply = await client.protocol.send_request_async(
                TURN_METHOD,
                {
                    "protocolVersion": 2,
                    "sessionId": "docs-session",
                    "createSession": True,
                    "workspaceUri": tmp_path.as_uri(),
                    "message": "/docs install",
                    "documentationIndexUri": docs_index.as_uri(),
                    "dirtyDocumentUris": [],
                },
            )

            assert reply.kind == "answer"
            assert reply.changeSetId is None
            assert "Sources:" in reply.text
            assert "guide.md#install" in reply.text
        finally:
            await client.shutdown_session()
