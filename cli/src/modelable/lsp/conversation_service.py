from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from modelable.compiler.workspace import load_workspace
from modelable.llm.config import resolve_llm_config
from modelable.llm.conversation import ConversationReply, ConversationSession
from modelable.llm.providers import build_provider
from modelable.lsp.conversation_protocol import (
    ConversationChangeSetParams,
    ConversationTurnParams,
    serialize_conversation_reply,
)
from modelable.lsp.definition import definition_location_for_ref
from modelable.lsp.document_symbols import find_focused_ref
from modelable.lsp.workspace import LspWorkspaceIndex, find_workspace_root, uri_to_path

SessionFactory = Callable[[Path, str | None], ConversationSession]


class ConversationSessionError(ValueError):
    pass


@dataclass
class _SessionEntry:
    workspace_uri: str
    root: Path
    session: ConversationSession
    touched_at: float


class LspConversationService:
    def __init__(
        self,
        *,
        max_sessions: int = 32,
        idle_seconds: float = 30 * 60,
        clock: Callable[[], float] = time.monotonic,
        session_factory: SessionFactory | None = None,
    ) -> None:
        self.max_sessions = max_sessions
        self.idle_seconds = idle_seconds
        self.clock = clock
        self.session_factory = session_factory or self._build_session
        self._sessions: dict[str, _SessionEntry] = {}

    def turn(
        self,
        params: ConversationTurnParams,
        *,
        index: LspWorkspaceIndex | None = None,
    ) -> dict[str, object]:
        now = self.clock()
        self._prune_expired(now)
        root = self._resolve_root(params)
        self._require_saved(root, params.dirty_document_uris)

        entry = self._sessions.get(params.session_id)
        if entry is None:
            if not params.create_session:
                raise ConversationSessionError(
                    f"Conversation session {params.session_id} is unknown or expired; start a new session."
                )
            self._evict_if_full()
            focused_ref = self._focused_ref(params, index)
            entry = _SessionEntry(
                workspace_uri=params.workspace_uri,
                root=root,
                session=self.session_factory(root, focused_ref),
                touched_at=now,
            )
            self._sessions[params.session_id] = entry
        else:
            if params.create_session:
                raise ConversationSessionError(f"Conversation session {params.session_id} already exists.")
            if entry.root != root:
                raise ConversationSessionError(
                    f"Conversation session {params.session_id} belongs to a different workspace."
                )
            focused_ref = self._focused_ref(params, index)
            if focused_ref is not None:
                entry.session.focused_ref = focused_ref

        reply = entry.session.turn(params.message)
        entry.touched_at = now
        return self._serialize(reply, params.session_id, entry)

    def close(self, session_id: str) -> None:
        self._prune_expired(self.clock())
        self._sessions.pop(session_id, None)

    def apply(self, params: ConversationChangeSetParams) -> dict[str, object]:
        now = self.clock()
        entry = self._require_session(params.session_id, now)
        self._require_pending(entry, params.change_set_id)
        self._require_saved(entry.root, params.dirty_document_uris)
        reply = entry.session.turn("/apply")
        entry.touched_at = now
        return self._serialize(reply, params.session_id, entry)

    def discard(self, params: ConversationChangeSetParams) -> dict[str, object]:
        now = self.clock()
        entry = self._require_session(params.session_id, now)
        self._require_pending(entry, params.change_set_id)
        self._require_saved(entry.root, params.dirty_document_uris)
        reply = entry.session.turn("/discard")
        entry.touched_at = now
        return self._serialize(reply, params.session_id, entry)

    def _build_session(self, root: Path, focused_ref: str | None) -> ConversationSession:
        workspace = load_workspace(root)
        config = resolve_llm_config(workspace=workspace.mdl.workspace)
        provider = build_provider(
            config.provider,
            model=config.model,
            base_url=config.base_url,
        )
        return ConversationSession(
            path=root,
            provider=provider,
            focused_ref=focused_ref,
            repair_attempts=config.repair_attempts,
        )

    def _resolve_root(self, params: ConversationTurnParams) -> Path:
        workspace_path = uri_to_path(params.workspace_uri)
        if workspace_path is None:
            raise ConversationSessionError("The conversation workspace must use a file URI.")
        workspace_root = workspace_path.resolve()
        if params.active_document_uri is None:
            return workspace_root
        active_path = uri_to_path(params.active_document_uri)
        if active_path is None:
            return workspace_root
        return (find_workspace_root(active_path) or workspace_root).resolve()

    def _require_saved(self, root: Path, dirty_document_uris: tuple[str, ...]) -> None:
        dirty_paths = []
        for uri in dirty_document_uris:
            path = uri_to_path(uri)
            if path is not None and path.suffix == ".mdl" and path.resolve().is_relative_to(root):
                dirty_paths.append(path)
        if dirty_paths:
            paths = ", ".join(str(path) for path in sorted(dirty_paths))
            raise ConversationSessionError(f"Save these files before continuing the conversation: {paths}")

    def _focused_ref(
        self,
        params: ConversationTurnParams,
        index: LspWorkspaceIndex | None,
    ) -> str | None:
        if params.active_document_uri is None or params.position is None or index is None:
            return None
        return find_focused_ref(
            index,
            params.active_document_uri,
            params.position.line,
            params.position.character,
        )

    def _serialize(
        self,
        reply: ConversationReply,
        session_id: str,
        entry: _SessionEntry,
    ) -> dict[str, object]:
        refs = {item.ref for item in reply.changed}
        refs.update(item.ref for item in reply.affected)
        locations = {
            ref: location
            for ref in refs
            if (location := definition_location_for_ref(entry.session.workspace, ref)) is not None
        }
        return serialize_conversation_reply(
            reply,
            session_id=session_id,
            workspace_uri=entry.workspace_uri,
            definition_locations=locations,
        )

    def _require_session(self, session_id: str, now: float) -> _SessionEntry:
        self._prune_expired(now)
        entry = self._sessions.get(session_id)
        if entry is None:
            raise ConversationSessionError(
                f"Conversation session {session_id} is unknown or expired; start a new session."
            )
        return entry

    def _require_pending(self, entry: _SessionEntry, change_set_id: str) -> None:
        pending = entry.session.pending
        if pending is None or pending.change_set_id != change_set_id:
            raise ConversationSessionError(
                f"Change set {change_set_id} is not the current pending change set for this session."
            )

    def _prune_expired(self, now: float) -> None:
        expired = [
            session_id for session_id, entry in self._sessions.items() if now - entry.touched_at > self.idle_seconds
        ]
        for session_id in expired:
            del self._sessions[session_id]

    def _evict_if_full(self) -> None:
        if len(self._sessions) < self.max_sessions:
            return
        session_id = min(
            self._sessions,
            key=lambda candidate: (
                self._sessions[candidate].touched_at,
                candidate,
            ),
        )
        del self._sessions[session_id]
