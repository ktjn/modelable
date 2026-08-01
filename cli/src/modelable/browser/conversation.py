from __future__ import annotations

import hashlib
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Literal, cast
from urllib.parse import quote, unquote, urlparse

from modelable.browser.api import BrowserCompiler
from modelable.browser.dto import BrowserSource
from modelable.browser.errors import BrowserLanguageError
from modelable.browser.rag import BrowserDocumentationRetriever, BrowserRetrievalError
from modelable.compiler.workspace import Workspace, WorkspaceDocumentSource, load_workspace_from_sources
from modelable.llm.context import build_workspace_summary
from modelable.llm.conversation_backend import (
    ConversationPreviewFile,
    ConversationReply,
)
from modelable.llm.conversation_engine import ConversationEngine
from modelable.llm.conversation_plan import ChangeSetPlan, CompilePlan, QueryPlan
from modelable.llm.conversation_planner import (
    PendingPlanRequest,
    PlanningRequestError,
    ResumableConversationPlanner,
)
from modelable.llm.provider_types import LLMRequest
from modelable.llm.workspace_editor import PendingChangeSet, WorkspaceEditError, WorkspaceEditor
from modelable.llm.workspace_query import WorkspaceQueryService
from modelable.rag.generation import RAG_SYSTEM_PROMPT, build_evidence_prompt
from modelable.rag.retriever import RetrievedChunk

if TYPE_CHECKING:
    from modelable.operations.compilation import CompilationFilePreview

_MAX_SESSIONS = 32
_SESSION_TTL_SECONDS = 30 * 60


@dataclass(frozen=True)
class BrowserConversationReply:
    reply: ConversationReply
    workspace_revision: int
    sources: tuple[BrowserSource, ...] = ()


@dataclass(frozen=True)
class _BrowserCompilationFile:
    category: str
    destination: Path
    staged_path: Path
    status: str
    media_type: str
    ref: str | None
    before_hash: str | None
    after_hash: str
    before_size: int
    after_size: int
    before_text: str | None
    after_text: str | None
    diff_text: str | None
    resolved_parent: Path


@dataclass
class _Session:
    engine: ConversationEngine
    backend: BrowserConversationBackend
    workspace_revision: int
    last_used: float
    documentation_index_url: str | None = None
    documentation_asset_root: str | None = None
    documentation_retriever: BrowserDocumentationRetriever | None = None
    pending_documentation: tuple[str, tuple[RetrievedChunk, ...]] | None = None


class BrowserConversationBackend:
    def __init__(self, compiler: BrowserCompiler) -> None:
        self.compiler = compiler
        self._pending_change: PendingChangeSet | None = None
        self._pending_compilation: tuple[str, tuple[CompilationFilePreview, ...]] | None = None
        self._path_to_uri: dict[Path, str] = {}
        self._workspace = self._load_workspace()
        self.documentation_retriever: BrowserDocumentationRetriever | None = None

    @property
    def pending_action_id(self) -> str | None:
        if self._pending_change is not None:
            return self._pending_change.change_set_id
        if self._pending_compilation is not None:
            return self._pending_compilation[0]
        return None

    def workspace_summary(self, focused_ref: str | None = None) -> str:
        return build_workspace_summary(self._workspace, focused_ref=focused_ref)

    def execute_query(self, plan: QueryPlan) -> ConversationReply:
        return ConversationReply(
            kind="answer",
            text=WorkspaceQueryService(self._workspace).execute(plan).text,
        )

    def preview_source_change(
        self,
        plan: ChangeSetPlan,
        replaced_action_id: str | None,
        *,
        session_editable_refs: frozenset[str] = frozenset(),
    ) -> ConversationReply:
        self._assert_replaced(replaced_action_id)
        try:
            pending = WorkspaceEditor(Path("."), workspace=self._workspace).preview(
                plan, session_editable_refs=session_editable_refs
            )
        except WorkspaceEditError as error:
            return ConversationReply(kind="error", text=f"Could not preview workspace changes: {error}")
        self._pending_change = pending
        self._pending_compilation = None
        current = {source.path: source.text for source in self._workspace.sources if source.path is not None}
        return ConversationReply(
            kind="preview",
            text=f"Previewed {plan.summary}\n\nApply or discard change set {pending.change_set_id}.",
            change_set_id=pending.change_set_id,
            operation_kind="source_change",
            focused_ref=pending.focus_ref,
            assumptions=tuple(pending.assumptions),
            changed=tuple(pending.changed),
            affected=tuple(pending.affected),
            compatibility=tuple(pending.compatibility),
            diagnostics=tuple(pending.diagnostics),
            preview_files=tuple(
                ConversationPreviewFile(
                    path=path,
                    existed_before=path in current,
                    before_text=current.get(path, ""),
                    after_text=text,
                )
                for path, text in sorted(pending.candidate_sources.items())
            ),
        )

    def preview_compilation(
        self,
        plan: CompilePlan,
        replaced_action_id: str | None,
    ) -> ConversationReply:
        self._assert_replaced(replaced_action_id)
        if plan.domains or plan.output is not None or plan.descriptor_set:
            return ConversationReply(
                kind="error",
                text=(
                    "Browser compilation does not support domain filters, output paths, "
                    "or descriptor sets; use an unfiltered browser compile or the CLI."
                ),
            )
        target = {
            "json-schema": "jsonSchema",
            "sql": "sql-postgres",
        }.get(plan.target, plan.target)
        try:
            result = self.compiler.compile(self.compiler.sources, target)
        except (BrowserLanguageError, ValueError) as error:
            return ConversationReply(
                kind="error",
                text=f"Browser compilation does not support {plan.target}: {error}",
            )
        if any(item.severity == "error" for item in result.diagnostics):
            return ConversationReply(kind="error", text="Could not preview compilation.")
        files = tuple(
            _compilation_preview(artifact.path, artifact.media_type, artifact.content) for artifact in result.artifacts
        )
        action_id = _artifact_action_id(files)
        self._pending_change = None
        self._pending_compilation = (action_id, files)
        return ConversationReply(
            kind="preview",
            text=f"Previewed {len(files)} compilation artifact(s) for {plan.target}.",
            change_set_id=action_id,
            operation_kind="compile",
            compilation_files=files,
        )

    def apply(self, action_id: str) -> ConversationReply:
        if action_id != self.pending_action_id:
            return ConversationReply(kind="error", text=f"Pending action does not match {action_id}.")
        if self._pending_compilation is not None:
            _, files = self._pending_compilation
            self._pending_compilation = None
            return ConversationReply(
                kind="applied",
                text=f"Applied compilation {action_id}.",
                change_set_id=action_id,
                operation_kind="compile",
                compilation_files=files,
            )
        pending = self._pending_change
        if pending is None:
            return ConversationReply(kind="error", text="There is no pending action to apply.")
        current_hashes = {
            source.path: source.content_hash for source in self._workspace.sources if source.path is not None
        }
        if current_hashes != pending.source_fingerprints:
            return ConversationReply(
                kind="error",
                text=f"Could not apply change set {action_id}: the workspace changed after preview.",
                change_set_id=action_id,
                operation_kind="source_change",
            )
        candidates = pending.candidate_sources
        updated = tuple(
            BrowserSource(
                uri=source.uri,
                text=candidates.get(_logical_path(source.uri), source.text),
                version=source.version + (1 if _logical_path(source.uri) in candidates else 0),
            )
            for source in self.compiler.sources
        )
        existing_paths = {_logical_path(source.uri) for source in self.compiler.sources}
        updated += tuple(
            BrowserSource(
                uri=_document_uri(path),
                text=text,
                version=1,
            )
            for path, text in sorted(candidates.items())
            if path not in existing_paths
        )
        revision = self.compiler.language.revision + 1
        self.compiler.open_workspace(revision, updated)
        self._pending_change = None
        self._workspace = self._load_workspace()
        return ConversationReply(
            kind="applied",
            text=f"Applied change set {action_id}.",
            change_set_id=action_id,
            operation_kind="source_change",
            focused_ref=pending.focus_ref,
            changed=tuple(pending.changed),
            compatibility=tuple(pending.compatibility),
            written_paths=tuple(sorted(candidates)),
        )

    def discard(self, action_id: str) -> ConversationReply:
        if action_id != self.pending_action_id:
            return ConversationReply(kind="error", text=f"Pending action does not match {action_id}.")
        operation_kind: Literal["source_change", "compile"] = (
            "compile" if self._pending_compilation is not None else "source_change"
        )
        self._pending_change = None
        self._pending_compilation = None
        return ConversationReply(
            kind="discarded",
            text=f"Discarded pending action {action_id}.",
            change_set_id=action_id,
            operation_kind=operation_kind,
        )

    def reset(self) -> None:
        self._pending_change = None
        self._pending_compilation = None
        self._workspace = self._load_workspace()

    def _load_workspace(self) -> Workspace:
        sources: list[WorkspaceDocumentSource] = []
        self._path_to_uri.clear()
        for source in self.compiler.sources:
            path = _logical_path(source.uri)
            self._path_to_uri[path] = source.uri
            sources.append(WorkspaceDocumentSource(path=path, uri=source.uri, text=source.text))
        return load_workspace_from_sources(sources)

    def _assert_replaced(self, action_id: str | None) -> None:
        if action_id != self.pending_action_id:
            raise ValueError(
                f"Replaced action ID {action_id!r} does not match backend action {self.pending_action_id!r}"
            )


class BrowserConversationService:
    def __init__(
        self,
        compiler: BrowserCompiler,
        *,
        id_factory: Callable[[], str] | None = None,
        clock: Callable[[], float] = time.monotonic,
        max_sessions: int = _MAX_SESSIONS,
        session_ttl_seconds: float = _SESSION_TTL_SECONDS,
        documentation_index_url: str | None = None,
        documentation_asset_root: str | None = None,
    ) -> None:
        self.compiler = compiler
        self.id_factory = id_factory
        self.clock = clock
        self.max_sessions = max_sessions
        self.session_ttl_seconds = session_ttl_seconds
        self.documentation_index_url = documentation_index_url
        self.documentation_asset_root = documentation_asset_root
        self._sessions: OrderedDict[str, _Session] = OrderedDict()

    def turn(
        self,
        *,
        session_id: str,
        workspace_revision: int,
        message: str,
        active_document_uri: str | None = None,
        line: int | None = None,
        character: int | None = None,
        documentation_index_url: str | None = None,
        documentation_asset_root: str | None = None,
    ) -> PendingPlanRequest | BrowserConversationReply:
        session = self._session(session_id, workspace_revision)
        if documentation_index_url is not None or documentation_asset_root is not None:
            self._configure_documentation(session, documentation_index_url, documentation_asset_root)
        if message.strip().lower().startswith("/docs"):
            return self._documentation_turn(session, message)
        session.engine.focused_ref = self._focused_ref(active_document_uri, line, character)
        outcome = session.engine.begin_turn(message)
        if isinstance(outcome, PendingPlanRequest):
            return outcome
        return self._result(outcome)

    def resume(
        self,
        *,
        session_id: str,
        request_id: str,
        workspace_revision: int,
        content: str,
    ) -> PendingPlanRequest | BrowserConversationReply:
        session = self._session(session_id, workspace_revision, create=False)
        pending_documentation = session.pending_documentation
        if pending_documentation is not None and pending_documentation[0] == request_id:
            session.pending_documentation = None
            citations = pending_documentation[1]
            source_lines = "\n".join(
                f"- [S{index}] {citation.external_id} ({citation.url})"
                for index, citation in enumerate(citations, start=1)
            )
            return self._result(ConversationReply(kind="answer", text=f"{content.strip()}\n\nSources:\n{source_lines}"))
        outcome = session.engine.resume_turn(request_id, content)
        if isinstance(outcome, PendingPlanRequest):
            return outcome
        return self._result(outcome)

    def apply(
        self,
        *,
        session_id: str,
        action_id: str,
        workspace_revision: int,
    ) -> BrowserConversationReply:
        session = self._session(session_id, workspace_revision, create=False)
        try:
            reply = session.engine.apply(action_id)
        except ValueError as error:
            reply = ConversationReply(kind="error", text=str(error))
        return self._result(reply)

    def fail(
        self,
        *,
        session_id: str,
        request_id: str,
        workspace_revision: int,
        error: str,
    ) -> BrowserConversationReply:
        session = self._session(session_id, workspace_revision, create=False)
        if session.pending_documentation is not None and session.pending_documentation[0] == request_id:
            session.pending_documentation = None
            return self._result(ConversationReply(kind="answer", text=f"The documentation answer failed: {error}"))
        return self._result(session.engine.fail_turn(request_id, RuntimeError(error)))

    def discard(
        self,
        *,
        session_id: str,
        action_id: str,
        workspace_revision: int,
    ) -> BrowserConversationReply:
        session = self._session(session_id, workspace_revision, create=False)
        try:
            reply = session.engine.discard(action_id)
        except ValueError as error:
            reply = ConversationReply(kind="error", text=str(error))
        return self._result(reply)

    def reset(self, *, session_id: str) -> None:
        try:
            session = self._sessions.pop(session_id)
        except KeyError:
            session = None
        if session is not None:
            session.engine.reset()

    def _result(self, reply: ConversationReply) -> BrowserConversationReply:
        return BrowserConversationReply(
            reply=reply,
            workspace_revision=self.compiler.language.revision,
            sources=self.compiler.sources if reply.kind == "applied" else (),
        )

    def _session(self, session_id: str, revision: int, *, create: bool = True) -> _Session:
        if revision != self.compiler.language.revision:
            raise BrowserLanguageError("STALE_WORKSPACE")
        now = self.clock()
        for key, expired_session in tuple(self._sessions.items()):
            if now - expired_session.last_used >= self.session_ttl_seconds:
                expired_session.engine.reset()
                del self._sessions[key]
        session: _Session | None
        try:
            session = self._sessions.pop(session_id)
        except KeyError:
            session = None
        if session is None:
            if not create:
                raise PlanningRequestError(f"Unknown conversation session: {session_id}")
            backend = BrowserConversationBackend(self.compiler)
            session = _Session(
                engine=ConversationEngine(
                    backend=backend,
                    planner=ResumableConversationPlanner(id_factory=self.id_factory),
                ),
                backend=backend,
                workspace_revision=revision,
                last_used=now,
            )
        elif session.workspace_revision != revision:
            session.engine.reset()
            backend = BrowserConversationBackend(self.compiler)
            session = _Session(
                engine=ConversationEngine(
                    backend=backend,
                    planner=ResumableConversationPlanner(id_factory=self.id_factory),
                ),
                backend=backend,
                workspace_revision=revision,
                last_used=now,
            )
        session.last_used = now
        self._sessions[session_id] = session
        while len(self._sessions) > self.max_sessions:
            _, expired = self._sessions.popitem(last=False)
            expired.engine.reset()
        return session

    def _configure_documentation(
        self,
        session: _Session,
        index_url: str | None,
        asset_root: str | None,
    ) -> None:
        if index_url is None or asset_root is None:
            raise PlanningRequestError("documentation index URL and asset root must be supplied together")
        if session.documentation_index_url is None:
            session.documentation_index_url = index_url
            session.documentation_asset_root = asset_root
            return
        if (session.documentation_index_url, session.documentation_asset_root) != (index_url, asset_root):
            raise PlanningRequestError("documentation index configuration cannot change during a session")

    def _documentation_turn(self, session: _Session, message: str) -> PendingPlanRequest | BrowserConversationReply:
        _, _, question = message.partition(" ")
        question = question.strip()
        if not question:
            return self._result(ConversationReply(kind="answer", text="Provide a question after /docs."))
        if session.documentation_index_url is None or session.documentation_asset_root is None:
            return self._result(
                ConversationReply(kind="answer", text="The /docs command requires a bundled documentation index.")
            )
        try:
            if session.documentation_retriever is None:
                session.documentation_retriever = BrowserDocumentationRetriever(
                    session.documentation_index_url,
                    session.documentation_asset_root,
                )
            chunks = tuple(session.documentation_retriever.search(question))
            prompt, selected = build_evidence_prompt(question, chunks, max_context_words=3000, max_chunks_per_source=2)
        except (BrowserRetrievalError, ValueError) as error:
            return self._result(ConversationReply(kind="answer", text=f"Documentation retrieval failed: {error}"))
        if not selected:
            return self._result(
                ConversationReply(kind="answer", text="I don't have enough documentation evidence to answer that.")
            )
        request_id = self.id_factory() if self.id_factory is not None else str(uuid.uuid4())
        session.pending_documentation = (request_id, tuple(selected))
        return PendingPlanRequest(
            request_id=request_id,
            request=LLMRequest(system=RAG_SYSTEM_PROMPT, user=prompt, temperature=0.2),
            attempt=0,
        )

    def _focused_ref(self, uri: str | None, line: int | None, character: int | None) -> str | None:
        del character
        if uri is None or line is None:
            return None
        document = self.compiler.language.current_document(uri)
        workspace = self.compiler.language.semantic_workspace()
        if document is None or workspace is None:
            return None
        active_domain: str | None = None
        active_name: str | None = None
        active_version: int | None = None
        import re

        for text in document.text.splitlines()[: line + 1]:
            domain = re.match(r'^\s*domain\s+(?:"([^"]+)"|([A-Za-z_][A-Za-z0-9_]*))', text)
            if domain:
                active_domain = domain.group(1) or domain.group(2)
            declaration = re.match(
                r"^\s*(?:entity|aggregate|event|value|projection)\s+([A-Za-z_][A-Za-z0-9_]*)\s*@\s*(\d+)",
                text,
            )
            if declaration:
                active_name = declaration.group(1)
                active_version = int(declaration.group(2))
        if active_domain and active_name and active_version is not None:
            return f"{active_domain}.{active_name}@{active_version}"
        return None


def _logical_path(uri: str) -> Path:
    parsed = urlparse(uri)
    raw = unquote(parsed.path).replace("\\", "/")
    parts = PurePosixPath(raw).parts
    relative_parts = tuple(part for part in parts if part != "/")
    if (
        not relative_parts
        or any(part in {"", ".", ".."} for part in relative_parts)
        or not relative_parts[-1].endswith(".mdl")
    ):
        raise ValueError(f"Browser source URI has no safe relative document path: {uri}")
    return Path(*relative_parts)


def _document_uri(path: Path) -> str:
    return "file:///" + "/".join(quote(part, safe="") for part in path.parts)


def _compilation_preview(path: str, media_type: str, content: str) -> CompilationFilePreview:
    logical = Path(path)
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return cast(
        "CompilationFilePreview",
        _BrowserCompilationFile(
            category="artifact",
            destination=logical,
            staged_path=logical,
            status="created",
            media_type=media_type,
            ref=None,
            before_hash=None,
            after_hash=digest,
            before_size=0,
            after_size=len(content.encode("utf-8")),
            before_text=None,
            after_text=content,
            diff_text=None,
            resolved_parent=Path("."),
        ),
    )


def _artifact_action_id(files: tuple[CompilationFilePreview, ...]) -> str:
    payload = "\n".join(f"{item.destination.as_posix()}:{item.after_hash}" for item in files)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
