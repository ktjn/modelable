from __future__ import annotations

from pathlib import Path

import pytest
from helpers import SERVER_CMD
from lsprotocol import types
from pygls.exceptions import JsonRpcInternalError
from pytest_lsp.client import make_test_lsp_client

from modelable.lsp.conversation_protocol import APPLY_METHOD, CLOSE_METHOD, TURN_METHOD


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
