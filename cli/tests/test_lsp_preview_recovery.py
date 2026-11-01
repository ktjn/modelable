import hashlib
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from lsprotocol import types
from pygls.exceptions import JsonRpcInternalError
from pytest_lsp.client import make_test_lsp_client
from test_compilation_failure_catalog import assert_no_publication
from test_compilation_failure_catalog import catalog_workspace as catalog_workspace
from test_lsp_compilation_recovery import assert_published, change_payload

from modelable.lsp.conversation_protocol import APPLY_METHOD, CLOSE_METHOD, TURN_METHOD


@pytest_asyncio.fixture
async def preview_rpc(catalog_workspace, request):
    root, stages, source_request, _service = catalog_workspace
    client = make_test_lsp_client()
    helper = Path(__file__).parent / "support" / "lsp_preview_recovery_server.py"
    await client.start_io(sys.executable, str(helper), str(stages), request.param)
    try:
        initialized = await client.initialize_session(
            types.InitializeParams(
                capabilities=types.ClientCapabilities(),
                root_uri=root.as_uri(),
                workspace_folders=[types.WorkspaceFolder(uri=root.as_uri(), name=root.name)],
            )
        )
        yield client, root, stages, source_request, initialized
    finally:
        await client.shutdown_session()


def payload(root, create=False, target="rust"):
    return {
        "protocolVersion": 2,
        "sessionId": "preview-recovery",
        "createSession": create,
        "workspaceUri": root.as_uri(),
        "message": "/compile " + target,
        "dirtyDocumentUris": [],
    }


async def close_and_reject_old_session(client, root):
    assert (
        await client.protocol.send_request_async(CLOSE_METHOD, {"protocolVersion": 2, "sessionId": "preview-recovery"})
        is None
    )
    with pytest.raises(JsonRpcInternalError, match="unknown or expired"):
        await client.protocol.send_request_async(TURN_METHOD, payload(root))


@pytest.mark.parametrize("preview_rpc", ["none", "sqlite-once"], indirect=True)
async def test_first_turn_dependency_error_retains_session_and_allows_retry(preview_rpc, request):
    client, root, stages, source_request, _initialized = preview_rpc
    ledger = source_request.registry_ids_path
    original = source_request.source.read_bytes()
    if request.node.callspec.params["preview_rpc"] == "none":
        ledger.write_bytes(b'{"broken":')
    failed = await client.protocol.send_request_async(TURN_METHOD, payload(root, True))
    assert failed.kind == "error"
    assert failed.sessionId == "preview-recovery"
    assert failed.changeSetId is None
    assert "Could not preview compilation" in failed.text
    assert source_request.source.read_bytes() == original
    assert list(stages.iterdir()) == []
    assert_no_publication(root)
    if ledger.exists():
        assert ledger.read_bytes() == b'{"broken":'
        ledger.write_bytes(b"{}")
    fresh = await client.protocol.send_request_async(TURN_METHOD, payload(root))
    assert fresh.kind == "preview"
    applied = await client.protocol.send_request_async(APPLY_METHOD, change_payload(fresh))
    assert_published(fresh, applied)
    assert list(stages.iterdir()) == []
    await close_and_reject_old_session(client, root)


@pytest.mark.parametrize("preview_rpc", ["none", "sqlite-second", "compilation-second"], indirect=True)
@pytest.mark.parametrize("finish", ["apply", "close"])
async def test_failed_replacement_serializes_live_pending_id_and_retains_bytes(preview_rpc, request, finish):
    client, root, stages, source_request, _initialized = preview_rpc
    ledger = source_request.registry_ids_path
    ledger.write_bytes(b"{}")
    first = await client.protocol.send_request_async(TURN_METHOD, payload(root, True))
    assert first.kind == "preview"
    stage = next(stages.iterdir())
    before = {p.relative_to(stage): hashlib.sha256(p.read_bytes()).hexdigest() for p in stage.rglob("*") if p.is_file()}
    if request.node.callspec.params["preview_rpc"] == "none":
        ledger.write_bytes(b'{"broken":')
    failed = await client.protocol.send_request_async(TURN_METHOD, payload(root, target="go"))
    assert failed.kind == "error"
    assert failed.sessionId == first.sessionId
    assert failed.changeSetId == first.changeSetId
    assert failed.operationKind == "compile"
    assert {
        p.relative_to(stage): hashlib.sha256(p.read_bytes()).hexdigest() for p in stage.rglob("*") if p.is_file()
    } == before
    assert len(list(stages.iterdir())) == 1
    assert_no_publication(root)
    ledger.write_bytes(b"{}")
    if finish == "apply":
        applied = await client.protocol.send_request_async(APPLY_METHOD, change_payload(failed))
        assert_published(first, applied)
    await close_and_reject_old_session(client, root)
    assert list(stages.iterdir()) == []


@pytest.mark.parametrize("preview_rpc", ["programming-once"], indirect=True)
async def test_programming_fault_stays_a_protocol_fault(preview_rpc):
    client, root, stages, _request, _initialized = preview_rpc
    with pytest.raises(JsonRpcInternalError, match="ProgrammingError") as raised:
        await client.protocol.send_request_async(TURN_METHOD, payload(root, True))
    assert raised.value.code == -32603
    assert list(stages.iterdir()) == []
    assert_no_publication(root)
    await close_and_reject_old_session(client, root)


@pytest.mark.parametrize("preview_rpc", ["none"], indirect=True)
async def test_real_initialize_advertises_conversation_protocol(preview_rpc):
    _client, _root, _stages, _request, initialized = preview_rpc
    assert initialized.capabilities.experimental == {"modelableConversation": {"protocolVersion": 2}}


@pytest.mark.parametrize("preview_rpc", ["none"], indirect=True)
async def test_artifact_references_do_not_break_go_preview_serialization(preview_rpc):
    client, root, stages, source_request, _initialized = preview_rpc
    source_request.source.write_text(
        'domain customer {\n  owner: "team"\n  entity Customer @ 1 (additive) {\n    @key customerId: uuid\n  }\n}\n',
        encoding="utf-8",
    )
    reply = await client.protocol.send_request_async(TURN_METHOD, payload(root, True, target="go"))
    assert reply.kind == "preview"
    artifact = next(item for item in reply.affectedDefinitions if item.ref == "go.mod")
    assert artifact.location is None
    model = next(item for item in reply.affectedDefinitions if item.ref == "customer.Customer@1")
    assert model.location.uri.endswith("customer.mdl")
    assert len(list(stages.iterdir())) == 1
    assert_no_publication(root)
    await close_and_reject_old_session(client, root)
    assert list(stages.iterdir()) == []


@pytest.mark.parametrize("ref", ["go.mod", "customer", "customer.Customer@invalid"])
def test_nonmodel_reference_has_no_optional_model_location(catalog_workspace, ref):
    from modelable.compiler.workspace import load_workspace
    from modelable.lsp.definition import definition_location_for_ref

    root, _stages, _request, _service = catalog_workspace
    assert definition_location_for_ref(load_workspace(root), ref) is None


@pytest.mark.parametrize("kind", [RuntimeError, ValueError])
def test_valid_reference_lookup_fault_is_not_swallowed(catalog_workspace, monkeypatch, kind):
    from unittest.mock import Mock

    from modelable.compiler.workspace import load_workspace
    from modelable.lsp.definition import definition_location_for_ref

    root, _stages, _request, _service = catalog_workspace
    error = kind("unexpected location lookup fault")
    monkeypatch.setattr("modelable.language.definition._definition_for_qualified_ref", Mock(side_effect=error))
    with pytest.raises(kind) as raised:
        definition_location_for_ref(load_workspace(root), "customer.Customer@1")
    assert raised.value is error
