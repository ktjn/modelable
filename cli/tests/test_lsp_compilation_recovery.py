from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from lsprotocol import types
from pygls.exceptions import JsonRpcInternalError
from pytest_lsp.client import make_test_lsp_client

from modelable.lsp.conversation_protocol import APPLY_METHOD, CLOSE_METHOD, DISCARD_METHOD, TURN_METHOD
from modelable.lsp.workspace import uri_to_path


@pytest_asyncio.fixture
async def compilation_rpc(tmp_path, request):
    root = tmp_path / "workspace"
    root.mkdir()
    source = root / "customer.mdl"
    source.write_text(
        'domain customer { owner: "team" entity Customer @ 1 (additive) { @key customerId: uuid } }',
        encoding="utf-8",
    )
    stages = tmp_path / "stages"
    stages.mkdir()
    helper = Path(__file__).parent / "support" / "lsp_compilation_fault_server.py"
    client = make_test_lsp_client()
    await client.start_io(sys.executable, str(helper), str(stages), getattr(request, "param", "none"))
    try:
        await client.initialize_session(
            types.InitializeParams(
                capabilities=types.ClientCapabilities(),
                root_uri=root.as_uri(),
                workspace_folders=[types.WorkspaceFolder(uri=root.as_uri(), name=root.name)],
            )
        )
        yield client, root, source, stages
    finally:
        await client.shutdown_session()


async def preview_compilation(client, root, *, create_session=True):
    reply = await client.protocol.send_request_async(
        TURN_METHOD,
        {
            "protocolVersion": 2,
            "sessionId": "recovery-session",
            "createSession": create_session,
            "workspaceUri": root.as_uri(),
            "message": "/compile rust",
            "dirtyDocumentUris": [],
        },
    )
    assert reply.kind == "preview"
    assert reply.operationKind == "compile"
    assert reply.compilationFiles
    return reply


def change_payload(preview):
    return {
        "protocolVersion": 2,
        "sessionId": preview.sessionId,
        "changeSetId": preview.changeSetId,
        "dirtyDocumentUris": [],
    }


def assert_published(preview, applied):
    assert applied.kind == "applied"
    assert applied.changeSetId == preview.changeSetId
    assert set(applied.writtenPaths) == {item.uri for item in preview.compilationFiles} | {preview.auditUri}
    assert applied.auditUri == preview.auditUri
    assert uri_to_path(applied.auditUri).is_file()
    for item in preview.compilationFiles:
        assert hashlib.sha256(uri_to_path(item.uri).read_bytes()).hexdigest() == item.afterHash


@pytest.mark.parametrize("compilation_rpc", ["cleanup"], indirect=True)
async def test_committed_cleanup_failure_is_applied_over_json_rpc_and_cannot_be_reapplied(compilation_rpc):
    client, root, _source, stages = compilation_rpc
    preview = await preview_compilation(client, root)
    assert not uri_to_path(preview.auditUri).exists()
    assert len(list(stages.iterdir())) == 1

    applied = await client.protocol.send_request_async(APPLY_METHOD, change_payload(preview))

    assert_published(preview, applied)
    assert "committed" in applied.text.lower()
    assert "Post-commit cleanup was incomplete" in applied.text
    assert "staging cleanup failure" in applied.text
    assert len(list(stages.iterdir())) == 1
    committed = {uri: uri_to_path(uri).read_bytes() for uri in applied.writtenPaths}
    with pytest.raises(JsonRpcInternalError, match="not the current pending action") as raised:
        await client.protocol.send_request_async(APPLY_METHOD, change_payload(preview))
    assert raised.value.code == -32603
    assert {uri: uri_to_path(uri).read_bytes() for uri in applied.writtenPaths} == committed
    assert (
        await client.protocol.send_request_async(CLOSE_METHOD, {"protocolVersion": 2, "sessionId": preview.sessionId})
        is None
    )
    # A committed cleanup warning does not promise automatic disposal of the remaining stage.
    assert len(list(stages.iterdir())) == 1


@pytest.mark.parametrize("guard", ["version", "session", "action", "dirty-output"])
async def test_apply_guard_fault_keeps_pending_stage_and_allows_corrected_retry(compilation_rpc, guard):
    client, root, _source, stages = compilation_rpc
    preview = await preview_compilation(client, root)
    payload = change_payload(preview)
    if guard == "version":
        payload["protocolVersion"] = 1
        message = "Unsupported Modelable conversation protocol version"
    elif guard == "session":
        payload["sessionId"] = "missing-session"
        message = "unknown or expired"
    elif guard == "action":
        payload["changeSetId"] = "wrong-action"
        message = "not the current pending action"
    else:
        payload["dirtyDocumentUris"] = [preview.compilationFiles[0].uri]
        message = "Save generated files"
    stage = next(stages.iterdir())
    staged = {path.relative_to(stage): path.read_bytes() for path in stage.rglob("*") if path.is_file()}

    with pytest.raises(JsonRpcInternalError, match=message) as raised:
        await client.protocol.send_request_async(APPLY_METHOD, payload)

    assert raised.value.code == -32603
    assert {path.relative_to(stage): path.read_bytes() for path in stage.rglob("*") if path.is_file()} == staged
    assert all(not uri_to_path(item.uri).exists() for item in preview.compilationFiles)
    assert not uri_to_path(preview.auditUri).exists()
    applied = await client.protocol.send_request_async(APPLY_METHOD, change_payload(preview))
    assert_published(preview, applied)
    assert list(stages.iterdir()) == []


async def test_stale_apply_is_domain_error_then_old_action_is_not_retryable_over_json_rpc(compilation_rpc):
    client, root, source, stages = compilation_rpc
    preview = await preview_compilation(client, root)
    source.write_text(source.read_text(encoding="utf-8") + "\n// changed after preview\n", encoding="utf-8")

    failed = await client.protocol.send_request_async(APPLY_METHOD, change_payload(preview))

    assert failed.kind == "error"
    assert failed.changeSetId == preview.changeSetId
    assert "changed" in failed.text.lower()
    assert failed.writtenPaths == []
    assert list(stages.iterdir()) == []
    assert not uri_to_path(preview.auditUri).exists()
    assert all(not uri_to_path(item.uri).exists() for item in preview.compilationFiles)
    for method in [APPLY_METHOD, DISCARD_METHOD]:
        with pytest.raises(JsonRpcInternalError, match="not the current pending action") as raised:
            await client.protocol.send_request_async(method, change_payload(preview))
        assert raised.value.code == -32603
    fresh = await preview_compilation(client, root, create_session=False)
    assert fresh.changeSetId != preview.changeSetId
    applied = await client.protocol.send_request_async(APPLY_METHOD, change_payload(fresh))
    assert_published(fresh, applied)
    assert list(stages.iterdir()) == []
