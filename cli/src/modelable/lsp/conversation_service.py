from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from inspect import signature
from pathlib import Path
from typing import cast
from urllib.parse import urljoin

from modelable.compiler.workspace import load_workspace
from modelable.llm.chat import documentation_conversation_reply
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
from modelable.operations.compilation import PendingCompilation
from modelable.rag import DocumentationRetriever
from modelable.rag.bundled_index import bundled_documentation_index_path
from modelable.rag.intent import classify_retrieval_intent

SessionFactory = Callable[..., ConversationSession]


class ConversationSessionError(ValueError):
    pass


@dataclass
class _SessionEntry:
    workspace_uri: str
    root: Path
    session: ConversationSession
    touched_at: float
    documentation_index_uri: str | None = None
    documentation_retriever: DocumentationRetriever | None = None
    automatic_documentation: bool = False


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
        self.session_factory = cast(SessionFactory, session_factory or self._build_session)
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
        is_new_session = entry is None
        if entry is None:
            if not params.create_session:
                raise ConversationSessionError(
                    f"Conversation session {params.session_id} is unknown or expired; start a new session."
                )
            self._evict_if_full()
            focused_ref = self._focused_ref(params, index)
            documentation_index_uri, documentation_retriever = self._create_documentation_retriever(
                root,
                params.documentation_index_uri,
            )
            entry = _SessionEntry(
                workspace_uri=params.workspace_uri,
                root=root,
                session=self._new_session(root, focused_ref, params.session_id),
                touched_at=now,
                documentation_index_uri=documentation_index_uri,
                documentation_retriever=documentation_retriever,
                automatic_documentation=(
                    params.automatic_documentation
                    if params.automatic_documentation is not None
                    else documentation_retriever is not None
                ),
            )
            self._sessions[params.session_id] = entry
        else:
            if params.create_session:
                raise ConversationSessionError(f"Conversation session {params.session_id} already exists.")
            if entry.root != root:
                raise ConversationSessionError(
                    f"Conversation session {params.session_id} belongs to a different workspace."
                )
            self._validate_documentation_index_uri(entry, root, params.documentation_index_uri, params.session_id)
            self._validate_automatic_documentation(entry, params.automatic_documentation, params.session_id)
            focused_ref = self._focused_ref(params, index)
            if focused_ref is not None:
                entry.session.focused_ref = focused_ref

        retrieval_decision = classify_retrieval_intent(
            params.message,
            automatic_enabled=entry.automatic_documentation,
        )
        documentation_reply = documentation_conversation_reply(
            params.message,
            retriever=entry.documentation_retriever,
            provider=getattr(entry.session, "provider", None),
            automatic_enabled=entry.automatic_documentation,
            decision=retrieval_decision,
        )
        reply = documentation_reply if documentation_reply is not None else entry.session.turn(params.message)
        entry.touched_at = now
        notice = entry.session.no_provider_notice
        if is_new_session and notice is not None and documentation_reply is None:
            reply = replace(reply, text=f"{notice}\n\n{reply.text}")
        return self._serialize(reply, params.session_id, entry)

    def close(self, session_id: str) -> None:
        self._prune_expired(self.clock())
        self._close_session(session_id)

    def apply(self, params: ConversationChangeSetParams) -> dict[str, object]:
        now = self.clock()
        entry = self._require_session(params.session_id, now)
        self._require_pending(entry, params.change_set_id)
        if entry.session.pending_operation_kind == "compile":
            self._require_compilation_destinations_saved(entry, params.dirty_document_uris)
        else:
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

    def _build_session(
        self,
        root: Path,
        focused_ref: str | None,
        session_id: str,
    ) -> ConversationSession:
        workspace = load_workspace(root)
        try:
            config = resolve_llm_config(workspace=workspace.mdl.workspace)
            provider = build_provider(
                config.provider,
                model=config.model,
                base_url=config.base_url,
            )
        except (TypeError, ValueError) as error:
            raise ConversationSessionError(f"Invalid Modelable LLM provider configuration: {error}") from error
        return ConversationSession(
            path=root,
            provider=provider,
            focused_ref=focused_ref,
            repair_attempts=config.repair_attempts,
            session_id=session_id,
            provider_name=config.provider,
            model_name=config.model,
            confirmation_surface="vscode-chat",
        )

    def _new_session(
        self,
        root: Path,
        focused_ref: str | None,
        session_id: str,
    ) -> ConversationSession:
        try:
            signature(self.session_factory).bind(root, focused_ref, session_id)
        except TypeError, ValueError:
            return self.session_factory(root, focused_ref)
        return self.session_factory(root, focused_ref, session_id)

    def _create_documentation_retriever(
        self,
        root: Path,
        documentation_index_uri: str | None,
    ) -> tuple[str | None, DocumentationRetriever | None]:
        if documentation_index_uri is None:
            try:
                resolved = bundled_documentation_index_path()
                return resolved.as_uri(), DocumentationRetriever(resolved)
            except RuntimeError:
                return None, None
        resolved = self._resolve_documentation_index_path(root, documentation_index_uri)
        try:
            manifest = json.loads(resolved.read_bytes())
            self._validate_documentation_shard_paths(root, resolved, manifest)
            retriever = DocumentationRetriever(resolved)
        except ConversationSessionError:
            raise
        except Exception as error:
            raise ConversationSessionError(
                f"Could not load the documentation index from {resolved}: {error}"
            ) from error
        return resolved.as_uri(), retriever

    def _validate_documentation_shard_paths(
        self,
        root: Path,
        manifest_path: Path,
        manifest: object,
    ) -> None:
        for context, reference in self._documentation_shard_references(manifest):
            if not isinstance(reference, str) or not reference:
                raise ValueError(f"{context} must be a non-empty string")
            shard_uri = urljoin(manifest_path.as_uri(), reference)
            shard_path = uri_to_path(shard_uri)
            if shard_path is None:
                raise ConversationSessionError(f"Documentation index {context} must resolve to a local file.")
            if not shard_path.resolve().is_relative_to(root.resolve()):
                raise ConversationSessionError(f"Documentation index {context} must stay inside the workspace root.")

    @staticmethod
    def _documentation_shard_references(manifest: object) -> list[tuple[str, object]]:
        if not isinstance(manifest, dict):
            raise ValueError("manifest must be a JSON object")
        shards = manifest.get("shards")
        if not isinstance(shards, dict):
            raise ValueError("shards must be a JSON object")

        references: list[tuple[str, object]] = []
        for section in ("terms", "docs"):
            entries = shards.get(section)
            if not isinstance(entries, list):
                raise ValueError(f"shards.{section} must be a JSON array")
            references.extend(LspConversationService._shard_array_references(entries, f"shards.{section}"))

        facets = shards.get("facets")
        if facets is not None:
            if not isinstance(facets, list):
                raise ValueError("shards.facets must be a JSON array")
            references.extend(LspConversationService._shard_array_references(facets, "shards.facets"))

        for section in ("pins", "synonyms"):
            entries = manifest.get(section)
            if entries is None:
                continue
            if not isinstance(entries, dict):
                raise ValueError(f"{section} must be a JSON object")
            references.extend((f"{section}.{language}", reference) for language, reference in entries.items())

        fuzzy = manifest.get("fuzzy")
        if fuzzy is not None:
            if not isinstance(fuzzy, dict):
                raise ValueError("fuzzy must be a JSON object")
            for language, descriptor in fuzzy.items():
                if not isinstance(descriptor, dict):
                    raise ValueError(f"fuzzy.{language} must be a JSON object")
                references.append((f"fuzzy.{language}.file", descriptor.get("file")))

        vectors = manifest.get("vectors")
        if vectors is not None:
            if not isinstance(vectors, dict):
                raise ValueError("vectors must be a JSON object")
            vector_shards = vectors.get("shards")
            if not isinstance(vector_shards, dict):
                raise ValueError("vectors.shards must be a JSON object")
            references.extend(
                (f"vectors.shards.{language}", reference) for language, reference in vector_shards.items()
            )

        return references

    @staticmethod
    def _shard_array_references(entries: list[object], context: str) -> list[tuple[str, object]]:
        references: list[tuple[str, object]] = []
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise ValueError(f"{context}[{index}] must be a JSON object")
            references.append((f"{context}[{index}].file", entry.get("file")))
        return references

    def _validate_documentation_index_uri(
        self,
        entry: _SessionEntry,
        root: Path,
        documentation_index_uri: str | None,
        session_id: str,
    ) -> None:
        if documentation_index_uri is None:
            return
        resolved_uri = self._resolve_documentation_index_path(root, documentation_index_uri).as_uri()
        if entry.documentation_index_uri != resolved_uri:
            raise ConversationSessionError(
                f"Conversation session {session_id} is already bound to documentation index "
                f"{entry.documentation_index_uri or 'none'} and cannot switch to {resolved_uri}."
            )

    def _validate_automatic_documentation(
        self,
        entry: _SessionEntry,
        automatic_documentation: bool | None,
        session_id: str,
    ) -> None:
        if automatic_documentation is None or automatic_documentation == entry.automatic_documentation:
            return
        raise ConversationSessionError(
            f"Conversation session {session_id} is already bound to automaticDocumentation="
            f"{str(entry.automatic_documentation).lower()}."
        )

    def _resolve_documentation_index_path(self, root: Path, documentation_index_uri: str) -> Path:
        documentation_index_path = uri_to_path(documentation_index_uri)
        if documentation_index_path is None:
            raise ConversationSessionError("The documentation index must use a file URI.")
        resolved = documentation_index_path.resolve()
        if not resolved.is_relative_to(root.resolve()):
            raise ConversationSessionError("The documentation index must stay inside the workspace root.")
        return resolved

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

    def _require_compilation_destinations_saved(
        self,
        entry: _SessionEntry,
        dirty_document_uris: tuple[str, ...],
    ) -> None:
        pending = entry.session.pending
        if not isinstance(pending, PendingCompilation):
            return
        destinations = {item.destination.resolve() for item in pending.files}
        destinations.add(pending.audit_path.resolve())
        dirty_destinations = {
            path.resolve()
            for uri in dirty_document_uris
            if (path := uri_to_path(uri)) is not None and path.resolve() in destinations
        }
        if dirty_destinations:
            paths = ", ".join(str(path) for path in sorted(dirty_destinations))
            raise ConversationSessionError(f"Save generated files before applying the compilation: {paths}")

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
        if reply.focused_ref is None and entry.session.focused_ref is not None:
            reply = replace(reply, focused_ref=entry.session.focused_ref)
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
        if entry.session.pending_action_id != change_set_id:
            raise ConversationSessionError(
                f"Pending action {change_set_id} is not the current pending action for this session."
            )

    def _prune_expired(self, now: float) -> None:
        expired = [
            session_id for session_id, entry in self._sessions.items() if now - entry.touched_at > self.idle_seconds
        ]
        for session_id in expired:
            self._close_session(session_id)

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
        self._close_session(session_id)

    def _close_session(self, session_id: str) -> None:
        entry = self._sessions.get(session_id)
        if entry is None:
            return
        try:
            entry.session.close()
        except Exception as error:
            raise ConversationSessionError(f"Could not close conversation session {session_id}: {error}") from error
        del self._sessions[session_id]
