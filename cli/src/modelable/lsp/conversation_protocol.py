from __future__ import annotations

from collections.abc import Mapping

from lsprotocol import types
from pydantic import BaseModel, ConfigDict, Field, field_validator

from modelable.diagnostics.model import Diagnostic
from modelable.llm.conversation import ConversationReply

PROTOCOL_VERSION = 1
TURN_METHOD = "modelable/conversation/turn"
APPLY_METHOD = "modelable/conversation/apply"
DISCARD_METHOD = "modelable/conversation/discard"
CLOSE_METHOD = "modelable/conversation/close"


class _ProtocolModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    protocol_version: int = Field(alias="protocolVersion", frozen=True)

    @field_validator("protocol_version")
    @classmethod
    def require_supported_version(cls, value: int) -> int:
        if value != PROTOCOL_VERSION:
            raise ValueError(f"Unsupported Modelable conversation protocol version: {value}")
        return value


class ConversationPosition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line: int = Field(ge=0)
    character: int = Field(ge=0)


class ConversationTurnParams(_ProtocolModel):
    session_id: str = Field(alias="sessionId", min_length=1)
    create_session: bool = Field(alias="createSession")
    workspace_uri: str = Field(alias="workspaceUri", min_length=1)
    message: str
    active_document_uri: str | None = Field(default=None, alias="activeDocumentUri")
    position: ConversationPosition | None = None
    dirty_document_uris: tuple[str, ...] = Field(default=(), alias="dirtyDocumentUris")


class ConversationChangeSetParams(_ProtocolModel):
    session_id: str = Field(alias="sessionId", min_length=1)
    change_set_id: str = Field(alias="changeSetId", min_length=1)
    dirty_document_uris: tuple[str, ...] = Field(default=(), alias="dirtyDocumentUris")


class ConversationCloseParams(_ProtocolModel):
    session_id: str = Field(alias="sessionId", min_length=1)


def serialize_conversation_reply(
    reply: ConversationReply,
    *,
    session_id: str,
    workspace_uri: str,
    definition_locations: Mapping[str, types.Location] | None = None,
) -> dict[str, object]:
    locations = definition_locations or {}
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "kind": reply.kind,
        "text": reply.text,
        "sessionId": session_id,
        "workspaceUri": workspace_uri,
        "changeSetId": reply.change_set_id,
        "focusedRef": reply.focused_ref,
        "changedDefinitions": [
            {
                "ref": item.ref,
                "reason": item.reason,
                "location": _serialize_location(locations.get(item.ref)),
            }
            for item in reply.changed
        ],
        "affectedDefinitions": [
            {
                "ref": item.ref,
                "status": item.status,
                "reason": item.reason,
                "location": _serialize_location(locations.get(item.ref)),
            }
            for item in reply.affected
        ],
        "compatibilityFindings": [
            {
                "ref": item.ref,
                "status": item.status,
                "message": item.message,
            }
            for item in reply.compatibility
        ],
        "diagnostics": [_serialize_diagnostic(item) for item in reply.diagnostics],
        "previewFiles": [
            {
                "uri": item.path.resolve().as_uri(),
                "existedBefore": item.existed_before,
                "beforeText": item.before_text,
                "afterText": item.after_text,
            }
            for item in reply.preview_files
        ],
        "writtenPaths": [path.resolve().as_uri() for path in reply.written_paths],
    }


def _serialize_diagnostic(diagnostic: Diagnostic) -> dict[str, object]:
    return {
        "path": diagnostic.path,
        "line": diagnostic.line,
        "column": diagnostic.column,
        "severity": diagnostic.severity,
        "code": diagnostic.code,
        "message": diagnostic.message,
    }


def _serialize_location(location: types.Location | None) -> dict[str, object] | None:
    if location is None:
        return None
    return {
        "uri": location.uri,
        "range": {
            "start": {
                "line": location.range.start.line,
                "character": location.range.start.character,
            },
            "end": {
                "line": location.range.end.line,
                "character": location.range.end.character,
            },
        },
    }
