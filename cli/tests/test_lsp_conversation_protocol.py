from __future__ import annotations

import pytest
from lsprotocol import types
from pydantic import ValidationError

from modelable.diagnostics.model import Diagnostic
from modelable.llm.conversation import ConversationPreviewFile, ConversationReply
from modelable.llm.workspace_editor import (
    AffectedDefinition,
    ChangedDefinition,
    CompatibilityFinding,
)
from modelable.lsp import conversation_protocol
from modelable.lsp.conversation_protocol import (
    PROTOCOL_VERSION,
    ConversationChangeSetParams,
    ConversationCloseParams,
    ConversationTurnParams,
)
from modelable.operations.compilation import CompilationFilePreview, RegistryIdChange


def test_turn_params_require_explicit_session_creation() -> None:
    params = ConversationTurnParams.model_validate(
        {
            "protocolVersion": 2,
            "sessionId": "session-1",
            "createSession": True,
            "workspaceUri": "file:///workspace",
            "message": "describe the customer model",
            "dirtyDocumentUris": [],
        }
    )

    assert params.protocol_version == PROTOCOL_VERSION
    assert params.session_id == "session-1"
    assert params.create_session is True
    assert params.dirty_document_uris == ()


@pytest.mark.parametrize(
    "overrides",
    [
        {"protocolVersion": 1},
        {"rawPatch": "delete everything"},
        {"sessionId": ""},
    ],
)
def test_turn_params_reject_unknown_fields_versions_and_empty_sessions(
    overrides: dict[str, object],
) -> None:
    payload: dict[str, object] = {
        "protocolVersion": 2,
        "sessionId": "session-1",
        "createSession": True,
        "workspaceUri": "file:///workspace",
        "message": "describe the customer model",
        "dirtyDocumentUris": [],
    }
    payload.update(overrides)

    with pytest.raises(ValidationError):
        ConversationTurnParams.model_validate(payload)


def test_change_and_close_params_are_closed() -> None:
    change = ConversationChangeSetParams.model_validate(
        {
            "protocolVersion": 2,
            "sessionId": "session-1",
            "changeSetId": "change-1",
            "dirtyDocumentUris": [],
        }
    )
    close = ConversationCloseParams.model_validate(
        {
            "protocolVersion": 2,
            "sessionId": "session-1",
        }
    )

    assert change.change_set_id == "change-1"
    assert change.dirty_document_uris == ()
    assert close.session_id == "session-1"


def test_serialize_conversation_reply_uses_json_primitives(tmp_path) -> None:
    source = tmp_path / "customer.mdl"
    reply = ConversationReply(
        kind="preview",
        text="Preview customer.Customer@1",
        change_set_id="change-1",
        focused_ref="customer.Customer@1",
        changed=(ChangedDefinition(ref="customer.Customer@1", reason="created"),),
        affected=(
            AffectedDefinition(
                ref="billing.CustomerView@1",
                status="compatible",
                reason="depends on customer.Customer@1",
            ),
        ),
        compatibility=(
            CompatibilityFinding(
                ref="customer.Customer@1",
                status="compatible",
                message="additive",
            ),
        ),
        diagnostics=(
            Diagnostic(
                code="SEM001",
                message="example warning",
                severity="warning",
                path=source.as_uri(),
                line=2,
                column=3,
            ),
        ),
        preview_files=(
            ConversationPreviewFile(
                path=source,
                existed_before=True,
                before_text="before",
                after_text="after",
            ),
        ),
    )
    location = types.Location(
        uri=source.as_uri(),
        range=types.Range(
            start=types.Position(line=1, character=2),
            end=types.Position(line=1, character=10),
        ),
    )

    payload = conversation_protocol.serialize_conversation_reply(
        reply,
        session_id="session-1",
        workspace_uri=tmp_path.as_uri(),
        definition_locations={"customer.Customer@1": location},
    )

    assert payload["protocolVersion"] == 2
    assert payload["kind"] == "preview"
    assert payload["sessionId"] == "session-1"
    assert payload["changeSetId"] == "change-1"
    assert payload["changedDefinitions"] == [
        {
            "ref": "customer.Customer@1",
            "reason": "created",
            "location": {
                "uri": source.as_uri(),
                "range": {
                    "start": {"line": 1, "character": 2},
                    "end": {"line": 1, "character": 10},
                },
            },
        }
    ]
    assert payload["affectedDefinitions"][0]["location"] is None
    assert payload["diagnostics"][0]["code"] == "SEM001"
    assert payload["previewFiles"] == [
        {
            "uri": source.resolve().as_uri(),
            "existedBefore": True,
            "beforeText": "before",
            "afterText": "after",
        }
    ]
    assert payload["operationKind"] is None
    assert payload["compilationFiles"] == []
    assert payload["registryIdChanges"] == []
    assert payload["auditUri"] is None


def test_serialize_compile_preview_protocol_v2(tmp_path) -> None:
    text_destination = tmp_path / "generated" / "customer.rs"
    binary_destination = tmp_path / ".modelable" / "registry.db"
    staging = tmp_path / "stage"
    text_staged = staging / "customer.rs"
    binary_staged = staging / "registry.db"
    reply = ConversationReply(
        kind="preview",
        text="Compilation preview",
        change_set_id="compile-1",
        operation_kind="compile",
        compilation_files=(
            CompilationFilePreview(
                category="artifact",
                destination=text_destination,
                staged_path=text_staged,
                status="changed",
                media_type="text/x-rust",
                ref="customer.Customer@1",
                before_hash="before-hash",
                after_hash="after-hash",
                before_size=6,
                after_size=5,
                before_text="before",
                after_text="after",
                diff_text="--- before\n+++ after\n",
                resolved_parent=text_destination.parent,
            ),
            CompilationFilePreview(
                category="registry",
                destination=binary_destination,
                staged_path=binary_staged,
                status="created",
                media_type="application/vnd.sqlite3",
                ref=None,
                before_hash=None,
                after_hash="binary-hash",
                before_size=0,
                after_size=4096,
                before_text=None,
                after_text=None,
                diff_text=None,
                resolved_parent=binary_destination.parent,
            ),
        ),
        registry_id_changes=(RegistryIdChange(ref="customer.SchemaId", registry_id=1),),
    )

    payload = conversation_protocol.serialize_conversation_reply(
        reply,
        session_id="session-1",
        workspace_uri=tmp_path.as_uri(),
    )

    assert payload["protocolVersion"] == 2
    assert payload["operationKind"] == "compile"
    assert payload["changeSetId"] == "compile-1"
    assert payload["compilationFiles"] == [
        {
            "category": "artifact",
            "uri": text_destination.resolve().as_uri(),
            "status": "changed",
            "mediaType": "text/x-rust",
            "ref": "customer.Customer@1",
            "beforeHash": "before-hash",
            "afterHash": "after-hash",
            "beforeSize": 6,
            "afterSize": 5,
            "beforeText": "before",
            "afterText": "after",
            "diffText": "--- before\n+++ after\n",
        },
        {
            "category": "registry",
            "uri": binary_destination.resolve().as_uri(),
            "status": "created",
            "mediaType": "application/vnd.sqlite3",
            "ref": None,
            "beforeHash": None,
            "afterHash": "binary-hash",
            "beforeSize": 0,
            "afterSize": 4096,
            "beforeText": None,
            "afterText": None,
            "diffText": None,
        },
    ]
    assert payload["registryIdChanges"] == [{"ref": "customer.SchemaId", "registryId": 1}]
    assert payload["auditUri"] is None


def test_serialize_compile_applied_reply_includes_audit_uri(tmp_path) -> None:
    audit = tmp_path / ".modelable" / "audit" / "compilations" / "compile-1.json"
    reply = ConversationReply(
        kind="applied",
        text="Applied compilation",
        change_set_id="compile-1",
        operation_kind="compile",
        audit_path=audit,
    )

    payload = conversation_protocol.serialize_conversation_reply(
        reply,
        session_id="session-1",
        workspace_uri=tmp_path.as_uri(),
    )

    assert payload["auditUri"] == audit.resolve().as_uri()
