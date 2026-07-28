from __future__ import annotations

from pathlib import Path
from typing import Literal, TypeIs

from modelable.compiler.workspace import load_workspace
from modelable.llm.context import build_workspace_summary
from modelable.llm.conversation_backend import (
    ConversationCleanupError,
    ConversationPreviewFile,
    ConversationReply,
)
from modelable.llm.conversation_plan import ChangeSetPlan, CompilePlan, QueryPlan
from modelable.llm.workspace_editor import (
    PendingChangeSet,
    WorkspaceEditError,
    WorkspaceEditor,
)
from modelable.llm.workspace_query import WorkspaceQueryService
from modelable.operations.compilation import (
    CompilationService,
    PendingCompilation,
)

type PendingAction = PendingChangeSet | PendingCompilation


class FilesystemConversationBackend:
    def __init__(
        self,
        *,
        path: Path,
        compilation_service: CompilationService | None = None,
        session_id: str,
        provider_name: str | None = None,
        model_name: str | None = None,
        confirmation_surface: Literal["cli-chat", "vscode-chat"] = "cli-chat",
    ) -> None:
        self.path = path
        self.compilation_service = compilation_service or CompilationService()
        self.session_id = session_id
        self.provider_name = provider_name
        self.model_name = model_name
        self.confirmation_surface = confirmation_surface
        self.workspace = load_workspace(path)
        self._pending: PendingAction | None = None
        self._cleanup_backlog: dict[str, PendingCompilation] = {}
        self.editor: WorkspaceEditor | None = None
        self._reload_services()

    @property
    def pending(self) -> PendingAction | None:
        return self._pending

    @property
    def pending_action_id(self) -> str | None:
        return _pending_id(self._pending)

    @property
    def pending_operation_kind(self) -> Literal["source_change", "compile"] | None:
        if _is_pending_compilation(self._pending):
            return "compile"
        if isinstance(self._pending, PendingChangeSet):
            return "source_change"
        return None

    @property
    def pending_cleanup_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._cleanup_backlog))

    @property
    def cleanup_action_id(self) -> str | None:
        cleanup_ids = sorted(self._cleanup_backlog)
        return cleanup_ids[0] if cleanup_ids else None

    def workspace_summary(self, focused_ref: str | None = None) -> str:
        return build_workspace_summary(self.workspace, focused_ref=focused_ref)

    def execute_query(self, plan: QueryPlan) -> ConversationReply:
        from modelable.llm.conversation import render_query_result

        return ConversationReply(
            kind="answer",
            text=render_query_result(self.query_service.execute(plan)),
        )

    def preview_source_change(
        self,
        plan: ChangeSetPlan,
        replaced_action_id: str | None,
    ) -> ConversationReply:
        from modelable.llm.conversation import (
            _render_cleanup_failure,
            render_pending_change_set,
        )

        replaced = self._pending
        actual_replaced_id = _pending_id(replaced)
        if replaced_action_id != actual_replaced_id:
            raise ValueError(
                f"Replaced action ID {replaced_action_id!r} does not match backend action {actual_replaced_id!r}"
            )
        try:
            if self.editor is None:
                self.editor = WorkspaceEditor(self.path, workspace=self.workspace)
            pending = self.editor.preview(plan)
        except WorkspaceEditError as error:
            return ConversationReply(kind="error", text=f"Could not preview workspace changes: {error}")
        cleanup_errors = self._dispose_actions((replaced,))
        if cleanup_errors:
            return ConversationReply(
                kind="error",
                text=_render_cleanup_failure("Could not replace the pending action.", cleanup_errors),
                change_set_id=actual_replaced_id,
            )
        self._pending = pending
        replacement = (
            f"Replaced pending change set {actual_replaced_id} with {pending.change_set_id}.\n\n"
            if actual_replaced_id is not None
            else ""
        )
        current_sources = {source.path: source.text for source in self.workspace.sources if source.path is not None}
        preview_files = tuple(
            ConversationPreviewFile(
                path=path,
                existed_before=path in current_sources,
                before_text=current_sources.get(path, ""),
                after_text=after_text,
            )
            for path, after_text in sorted(pending.candidate_sources.items())
        )
        return ConversationReply(
            kind="preview",
            text=replacement + render_pending_change_set(pending),
            change_set_id=pending.change_set_id,
            operation_kind="source_change",
            focused_ref=pending.focus_ref,
            changed=tuple(pending.changed),
            affected=tuple(pending.affected),
            compatibility=tuple(pending.compatibility),
            diagnostics=tuple(pending.diagnostics),
            preview_files=preview_files,
        )

    def preview_compilation(
        self,
        plan: CompilePlan,
        replaced_action_id: str | None,
    ) -> ConversationReply:
        from modelable.llm.conversation import (
            _escape_inline,
            _render_cleanup_failure,
            render_pending_compilation,
        )
        from modelable.operations.compilation import (
            CompilationError,
            CompilationPolicy,
            CompilationRequest,
        )

        replaced = self._pending
        actual_replaced_id = _pending_id(replaced)
        if replaced_action_id != actual_replaced_id:
            raise ValueError(
                f"Replaced action ID {replaced_action_id!r} does not match backend action {actual_replaced_id!r}"
            )
        try:
            pending = self.compilation_service.preview(
                CompilationRequest(
                    source=self.path,
                    target=plan.target,
                    out_dir=Path(plan.output) if plan.output is not None else None,
                    domains=tuple(plan.domains),
                    descriptor_set=plan.descriptor_set,
                ),
                policy=CompilationPolicy.conversation(),
            )
        except CompilationError as error:
            return ConversationReply(
                kind="error",
                text=f"Could not preview compilation: {_escape_inline(error)}",
            )
        cleanup_errors = self._dispose_actions((replaced,))
        if cleanup_errors:
            cleanup_errors += self._dispose_actions((pending,))
            self._pending = None
            return ConversationReply(
                kind="error",
                text=_render_cleanup_failure(
                    "Could not replace the pending action; all staged actions remain tracked for cleanup.",
                    cleanup_errors,
                ),
                operation_kind="compile",
            )
        self._pending = pending
        replacement = (
            f"Replaced pending action {actual_replaced_id} with compilation {pending.action_id}.\n\n"
            if actual_replaced_id is not None
            else ""
        )
        return ConversationReply(
            kind="preview",
            text=replacement + render_pending_compilation(pending, plan),
            change_set_id=pending.action_id,
            operation_kind="compile",
            affected=pending.affected_definitions,
            compilation_files=pending.files,
            registry_id_changes=pending.registry_id_changes,
            audit_path=pending.audit_path,
        )

    def apply(self, action_id: str) -> ConversationReply:
        if action_id != _pending_id(self._pending):
            return ConversationReply(
                kind="error",
                text=f"Pending action does not match {action_id}.",
                change_set_id=action_id,
            )
        if _is_pending_compilation(self._pending):
            return self._apply_pending_compilation(self._pending)
        if not isinstance(self._pending, PendingChangeSet):
            return ConversationReply(kind="error", text="There is no pending action to apply.")
        if self.editor is None:
            return ConversationReply(
                kind="error",
                text=f"Could not apply change set {self._pending.change_set_id}: the preview editor is unavailable.",
                change_set_id=self._pending.change_set_id,
            )
        try:
            applied = self.editor.apply(self._pending)
        except WorkspaceEditError as error:
            return ConversationReply(
                kind="error",
                text=f"Could not apply change set {self._pending.change_set_id}: {error}",
                change_set_id=self._pending.change_set_id,
            )
        from modelable.llm.conversation import render_applied_change_set

        self.workspace = applied.workspace
        self._pending = None
        self._reload_services()
        return ConversationReply(
            kind="applied",
            text=render_applied_change_set(applied),
            change_set_id=applied.change_set_id,
            operation_kind="source_change",
            focused_ref=applied.focus_ref,
            changed=tuple(applied.changed),
            compatibility=tuple(applied.compatibility),
            written_paths=applied.written_paths,
        )

    def discard(self, action_id: str) -> ConversationReply:
        from modelable.llm.conversation import _render_cleanup_failure

        known_ids = {_pending_id(self._pending), *self._cleanup_backlog}
        if action_id not in known_ids:
            return ConversationReply(
                kind="error",
                text=f"Pending action does not match {action_id}.",
                change_set_id=action_id,
            )
        cleanup_only = self._pending is None
        cleanup_ids = tuple(sorted(self._cleanup_backlog))
        operation_kind: Literal["source_change", "compile"] = (
            "compile" if cleanup_only or _is_pending_compilation(self._pending) else "source_change"
        )
        cleanup_errors = self._dispose_actions((self._pending, *self._cleanup_backlog.values()))
        if cleanup_errors:
            return ConversationReply(
                kind="error",
                text=_render_cleanup_failure(
                    (
                        "Could not fully discard staged compilation cleanup; cleanup will be retried."
                        if cleanup_only
                        else "Could not fully discard the pending action; cleanup will be retried."
                    ),
                    cleanup_errors,
                ),
                change_set_id=action_id,
                operation_kind=operation_kind,
            )
        self._pending = None
        return ConversationReply(
            kind="discarded",
            text=(
                f"Discarded staged compilation cleanup {', '.join(cleanup_ids)}."
                if cleanup_only
                else f"Discarded pending action {action_id}."
            ),
            change_set_id=action_id,
            operation_kind=operation_kind,
        )

    def reset(self) -> None:
        self.close()
        self.workspace = load_workspace(self.path)
        self._reload_services()

    def close(self) -> None:
        cleanup_errors = self._dispose_actions((self._pending, *self._cleanup_backlog.values()))
        if cleanup_errors:
            raise ConversationCleanupError(cleanup_errors)
        self._pending = None

    def cleanup_after_exception(self, error: BaseException) -> None:
        try:
            self.close()
        except Exception as cleanup_error:
            error.add_note(str(cleanup_error))

    def _apply_pending_compilation(self, pending: PendingCompilation) -> ConversationReply:
        from modelable.llm.conversation import (
            _escape_inline,
            render_applied_compilation,
            render_committed_compilation_cleanup_error,
        )
        from modelable.operations.compilation import CompilationConfirmation
        from modelable.operations.file_transaction import FileTransactionCommittedError

        confirmation = CompilationConfirmation(
            session_id=self.session_id,
            action_id=pending.action_id,
            manifest_fingerprint=pending.manifest_fingerprint,
            surface=self.confirmation_surface,
            provider=self.provider_name,
            model=self.model_name,
        )
        try:
            applied = self.compilation_service.apply(pending, confirmation=confirmation)
        except FileTransactionCommittedError as error:
            self._cleanup_backlog.pop(pending.action_id, None)
            self._pending = None
            audit_path = pending.audit_path
            return ConversationReply(
                kind="applied",
                text=render_committed_compilation_cleanup_error(pending, error, audit_path),
                change_set_id=pending.action_id,
                operation_kind="compile",
                affected=pending.affected_definitions,
                written_paths=error.written_paths,
                compilation_files=pending.files,
                registry_id_changes=pending.registry_id_changes,
                audit_path=audit_path,
            )
        except Exception as error:
            if not pending.staging_dir.exists():
                self._cleanup_backlog.pop(pending.action_id, None)
                self._pending = None
            else:
                self._cleanup_backlog[pending.action_id] = pending
            return ConversationReply(
                kind="error",
                text=f"Could not apply compilation {_escape_inline(pending.action_id)}: {_escape_inline(error)}",
                change_set_id=pending.action_id,
                operation_kind="compile",
            )
        self._cleanup_backlog.pop(pending.action_id, None)
        self._pending = None
        return ConversationReply(
            kind="applied",
            text=render_applied_compilation(applied),
            change_set_id=applied.action_id,
            operation_kind="compile",
            affected=applied.affected_definitions,
            written_paths=applied.written_paths,
            compilation_files=applied.files,
            registry_id_changes=pending.registry_id_changes,
            audit_path=applied.audit_path,
        )

    def _dispose_actions(self, actions: tuple[PendingAction | None, ...]) -> tuple[str, ...]:
        errors: list[str] = []
        seen: set[str] = set()
        for action in actions:
            if not _is_pending_compilation(action) or action.action_id in seen:
                continue
            seen.add(action.action_id)
            try:
                self.compilation_service.discard(action)
            except Exception as error:
                self._cleanup_backlog[action.action_id] = action
                errors.append(f"{action.action_id}: {error}")
            else:
                self._cleanup_backlog.pop(action.action_id, None)
        return tuple(errors)

    def _reload_services(self) -> None:
        self.query_service = WorkspaceQueryService(self.workspace)
        self.editor = None


def _pending_id(pending: PendingAction | None) -> str | None:
    if isinstance(pending, PendingChangeSet):
        return pending.change_set_id
    if _is_pending_compilation(pending):
        return pending.action_id
    return None


def _is_pending_compilation(pending: object) -> TypeIs[PendingCompilation]:
    return isinstance(pending, PendingCompilation)
