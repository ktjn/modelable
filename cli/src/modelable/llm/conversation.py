from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, TypeIs

from modelable.compiler.workspace import load_workspace
from modelable.diagnostics.model import Diagnostic, render_diagnostic
from modelable.llm.context import build_workspace_summary
from modelable.llm.conversation_plan import (
    ChangeSetPlan,
    ClarificationPlan,
    CompilePlan,
    Operation,
    QueryPlan,
    UnsupportedPlan,
)
from modelable.llm.conversation_planner import ConversationPlanner, PlannerContext
from modelable.llm.providers import LLMProvider
from modelable.llm.workspace_editor import (
    AffectedDefinition,
    AppliedChangeSet,
    ChangedDefinition,
    CompatibilityFinding,
    PendingChangeSet,
    WorkspaceEditError,
    WorkspaceEditor,
)
from modelable.llm.workspace_query import QueryResult, WorkspaceQueryService

if TYPE_CHECKING:
    from modelable.operations.compilation import (
        AppliedCompilation,
        CompilationFilePreview,
        CompilationService,
        PendingCompilation,
        RegistryIdChange,
    )
    from modelable.operations.file_transaction import FileTransactionCommittedError

type ReplyKind = Literal[
    "answer",
    "clarification",
    "preview",
    "applied",
    "discarded",
    "unsupported",
    "error",
]
type PendingAction = PendingChangeSet | PendingCompilation


@dataclass(frozen=True)
class ConversationPreviewFile:
    path: Path
    existed_before: bool
    before_text: str
    after_text: str


@dataclass(frozen=True)
class ConversationReply:
    kind: ReplyKind
    text: str
    change_set_id: str | None = None
    operation_kind: Literal["source_change", "compile"] | None = None
    focused_ref: str | None = None
    changed: tuple[ChangedDefinition, ...] = ()
    affected: tuple[AffectedDefinition, ...] = ()
    compatibility: tuple[CompatibilityFinding, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    preview_files: tuple[ConversationPreviewFile, ...] = ()
    written_paths: tuple[Path, ...] = ()
    compilation_files: tuple[CompilationFilePreview, ...] = ()
    registry_id_changes: tuple[RegistryIdChange, ...] = ()
    audit_path: Path | None = None


class ConversationSession:
    def __init__(
        self,
        *,
        path: Path,
        provider: LLMProvider | None,
        focused_ref: str | None = None,
        repair_attempts: int = 1,
        compilation_service: CompilationService | None = None,
        session_id: str | None = None,
        provider_name: str | None = None,
        model_name: str | None = None,
    ) -> None:
        if compilation_service is None:
            from modelable.operations.compilation import CompilationService

            compilation_service = CompilationService()
        self.path = path
        self.provider = provider
        self.focused_ref = focused_ref
        self.history: list[tuple[str, str]] = []
        self._pending: PendingAction | None = None
        self.compilation_service = compilation_service
        self.session_id = session_id or str(uuid.uuid4())
        self.provider_name = provider_name
        self.model_name = model_name
        self.workspace = load_workspace(path)
        self.planner = ConversationPlanner(provider, repair_attempts=repair_attempts)
        self.editor: WorkspaceEditor | None = None
        self._reload_services()

    @property
    def pending(self) -> Any:
        """Return the pending action through the legacy public session surface."""
        return self._pending

    @pending.setter
    def pending(self, value: PendingAction | None) -> None:
        self._pending = value

    def turn(self, message: str) -> ConversationReply:
        normalized = message.strip()
        lowered = normalized.lower()
        if normalized == "/apply":
            reply = self._apply_pending()
        elif lowered in {"apply", "apply it", "confirm"}:
            if _is_pending_compilation(self.pending):
                reply = ConversationReply(
                    kind="error",
                    text=(
                        "Compilation requires the literal /apply command. "
                        "Use /discard to cancel or another request to replace the preview."
                    ),
                    change_set_id=self.pending.action_id,
                    operation_kind="compile",
                )
            else:
                reply = self._apply_pending()
        elif lowered in {"discard", "discard it", "cancel"} or normalized == "/discard":
            reply = self._discard_pending()
        else:
            reply = self._plan_and_execute(normalized)
        self.history.append(("user", message))
        self.history.append(("assistant", reply.text))
        return reply

    def _plan_and_execute(self, message: str) -> ConversationReply:
        plan = self.planner.plan(
            message,
            PlannerContext(
                workspace_summary=build_workspace_summary(self.workspace),
                focused_ref=self.focused_ref,
                history=tuple(self.history),
                pending_plan=self.pending.plan if isinstance(self.pending, PendingChangeSet) else None,
            ),
        )
        if isinstance(plan, QueryPlan):
            return ConversationReply(
                kind="answer",
                text=render_query_result(self.query_service.execute(plan)),
            )
        if isinstance(plan, ClarificationPlan):
            return ConversationReply(
                kind="clarification",
                text=f"{plan.question}\n\nReason: {plan.reason}",
            )
        if isinstance(plan, UnsupportedPlan):
            roadmap = f"\n\nRoadmap area: {plan.roadmap_area}" if plan.roadmap_area else ""
            return ConversationReply(
                kind="unsupported",
                text=f"{plan.reason}{roadmap}",
            )
        if isinstance(plan, ChangeSetPlan):
            return self._preview_source_change(plan)
        if isinstance(plan, CompilePlan):
            return self._preview_compilation(plan)
        return ConversationReply(kind="error", text="The request produced an unknown conversation plan.")

    def _preview_source_change(self, plan: ChangeSetPlan) -> ConversationReply:
        replaced = self.pending
        replaced_id = _pending_id(replaced)
        try:
            if self.editor is None:
                self.editor = WorkspaceEditor(self.path, workspace=self.workspace)
            pending = self.editor.preview(plan)
        except WorkspaceEditError as error:
            return ConversationReply(kind="error", text=f"Could not preview workspace changes: {error}")
        self._dispose_pending(replaced)
        self.pending = pending
        replacement = (
            f"Replaced pending change set {replaced_id} with {pending.change_set_id}.\n\n"
            if replaced_id is not None
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

    def _preview_compilation(self, plan: CompilePlan) -> ConversationReply:
        from modelable.operations.compilation import (
            CompilationError,
            CompilationPolicy,
            CompilationRequest,
        )

        replaced = self.pending
        replaced_id = _pending_id(replaced)
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
            return ConversationReply(kind="error", text=f"Could not preview compilation: {error}")
        self._dispose_pending(replaced)
        self.pending = pending
        replacement = (
            f"Replaced pending action {replaced_id} with compilation {pending.action_id}.\n\n"
            if replaced_id is not None
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
        )

    def _apply_pending(self) -> ConversationReply:
        if self.pending is None:
            return ConversationReply(kind="error", text="There is no pending change set to apply.")
        if _is_pending_compilation(self.pending):
            return self._apply_pending_compilation(self.pending)
        if self.editor is None:
            return ConversationReply(
                kind="error",
                text=f"Could not apply change set {self.pending.change_set_id}: the preview editor is unavailable.",
                change_set_id=self.pending.change_set_id,
            )
        try:
            applied = self.editor.apply(self.pending)
        except WorkspaceEditError as error:
            return ConversationReply(
                kind="error",
                text=f"Could not apply change set {self.pending.change_set_id}: {error}",
                change_set_id=self.pending.change_set_id,
            )
        self.workspace = applied.workspace
        self.focused_ref = applied.focus_ref
        self.pending = None
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

    def _apply_pending_compilation(self, pending: PendingCompilation) -> ConversationReply:
        from modelable.operations.compilation import CompilationConfirmation
        from modelable.operations.file_transaction import FileTransactionCommittedError

        confirmation = CompilationConfirmation(
            session_id=self.session_id,
            action_id=pending.action_id,
            manifest_fingerprint=pending.manifest_fingerprint,
            surface="cli-chat",
            provider=self.provider_name,
            model=self.model_name,
        )
        try:
            applied = self.compilation_service.apply(pending, confirmation=confirmation)
        except FileTransactionCommittedError as error:
            self.pending = None
            audit_path = pending.workspace_root / ".modelable" / "audit" / "compilations" / f"{pending.action_id}.json"
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
                self.pending = None
            return ConversationReply(
                kind="error",
                text=f"Could not apply compilation {pending.action_id}: {error}",
                change_set_id=pending.action_id,
                operation_kind="compile",
            )
        self.pending = None
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

    def _discard_pending(self) -> ConversationReply:
        if self.pending is None:
            return ConversationReply(kind="error", text="There is no pending change set to discard.")
        change_set_id = _pending_id(self.pending)
        operation_kind: Literal["source_change", "compile"] = (
            "compile" if _is_pending_compilation(self.pending) else "source_change"
        )
        self._dispose_pending(self.pending)
        self.pending = None
        return ConversationReply(
            kind="discarded",
            text=f"Discarded pending action {change_set_id}.",
            change_set_id=change_set_id,
            operation_kind=operation_kind,
        )

    def close(self) -> None:
        self._dispose_pending(self.pending)
        self.pending = None

    def _dispose_pending(self, pending: PendingAction | None) -> None:
        if _is_pending_compilation(pending):
            self.compilation_service.discard(pending)

    def _reload_services(self) -> None:
        self.query_service = WorkspaceQueryService(self.workspace)
        self.editor = None


def render_query_result(result: QueryResult) -> str:
    return result.text


def render_pending_change_set(pending: PendingChangeSet) -> str:
    assumptions = [f"- {assumption}" for assumption in pending.assumptions] or ["- none"]
    operations = [f"- {operation.kind}: {_operation_target(operation)}" for operation in pending.plan.operations] or [
        "- none"
    ]
    changed = [f"- {item.ref}: {item.reason}" for item in sorted(pending.changed, key=lambda item: item.ref)] or [
        "- none"
    ]
    affected = [
        f"- {item.ref} [{item.status}]: {item.reason}" for item in sorted(pending.affected, key=lambda item: item.ref)
    ] or ["- none"]
    findings = [
        f"- {item.ref} [{item.status}]: {item.message}"
        for item in sorted(pending.compatibility, key=lambda item: item.ref)
    ]
    findings.extend(
        f"- {render_diagnostic(diagnostic)}"
        for diagnostic in sorted(
            pending.diagnostics,
            key=lambda diagnostic: (
                diagnostic.path,
                diagnostic.line or 0,
                diagnostic.column or 0,
                diagnostic.code,
            ),
        )
    )
    if not findings:
        findings.append("- none")
    diff_text = pending.diff_text or "- none"
    return "\n\n".join(
        [
            "Summary\n" + pending.plan.summary,
            "Assumptions\n" + "\n".join(assumptions),
            "Proposed definitions and operations\n" + "\n".join(operations),
            "Changed definitions\n" + "\n".join(changed),
            "Affected definitions\n" + "\n".join(affected),
            "Compatibility and validation\n" + "\n".join(findings),
            "Unified diff\n" + diff_text,
            (
                f"Apply change set {pending.change_set_id} with /apply or refine it with another request. "
                "Use /discard to cancel."
            ),
        ]
    )


def render_applied_change_set(applied: AppliedChangeSet) -> str:
    paths = [f"- {path}" for path in sorted(applied.written_paths)] or ["- none"]
    changed = [f"- {item.ref}: {item.reason}" for item in sorted(applied.changed, key=lambda item: item.ref)] or [
        "- none"
    ]
    compatibility = [
        f"- {item.ref} [{item.status}]: {item.message}"
        for item in sorted(applied.compatibility, key=lambda item: item.ref)
    ] or ["- none"]
    focus = applied.focus_ref or "none"
    return "\n\n".join(
        [
            f"Applied change set {applied.change_set_id}.",
            "Written paths\n" + "\n".join(paths),
            "Changed definitions\n" + "\n".join(changed),
            "Compatibility and validation\n" + "\n".join(compatibility),
            f"Focused reference\n{focus}",
        ]
    )


def render_pending_compilation(pending: PendingCompilation, plan: CompilePlan) -> str:
    domains = ", ".join(plan.domains) if plan.domains else "all"
    output = plan.output or "default"
    affected = [
        f"- {item.ref} [{item.status}]: {item.reason}"
        for item in sorted(pending.affected_definitions, key=lambda item: item.ref)
    ] or ["- none"]
    sections = [
        "Summary\n" + plan.summary,
        (
            "Normalized plan\n"
            f"- target: {plan.target}\n"
            f"- domains: {domains}\n"
            f"- output: {output}\n"
            f"- descriptor set: {'yes' if plan.descriptor_set else 'no'}"
        ),
        "Source definitions\n- unchanged",
        "Affected definitions\n" + "\n".join(affected),
    ]
    for status, title in (
        ("created", "Created files"),
        ("changed", "Changed files"),
        ("unchanged", "Unchanged files"),
    ):
        files = [f"- {item.destination} [{item.category}]" for item in pending.files if item.status == status] or [
            "- none"
        ]
        sections.append(title + "\n" + "\n".join(files))
    registry_ids = [f"- {item.ref}: {item.registry_id}" for item in pending.registry_id_changes] or ["- none"]
    sections.append("Registry-ID additions\n" + "\n".join(registry_ids))
    text_diffs = [
        f"--- {item.destination}\n{item.diff_text}" for item in pending.files if item.diff_text is not None
    ] or ["- none"]
    sections.append("Text diffs\n" + "\n".join(text_diffs))
    binaries = [
        (
            f"- {item.destination}: {item.before_size} bytes "
            f"({item.before_hash or 'none'}) -> {item.after_size} bytes ({item.after_hash})"
        )
        for item in pending.files
        if item.after_text is None
    ] or ["- none"]
    sections.append("Binary files\n" + "\n".join(binaries))
    warnings = [f"- {warning}" for warning in pending.warnings] or ["- none"]
    sections.append("Warnings\n" + "\n".join(warnings))
    sections.append(
        "Only the literal /apply command applies this compilation. "
        "Use /discard to cancel it or another request to replace it."
    )
    return "\n\n".join(sections)


def render_applied_compilation(applied: AppliedCompilation) -> str:
    hashes = {item.destination: item.after_hash for item in applied.files}
    paths = [f"- {path}: {hashes.get(path, 'audit record')}" for path in applied.written_paths] or ["- none"]
    affected = [
        f"- {item.ref} [{item.status}]: {item.reason}"
        for item in sorted(applied.affected_definitions, key=lambda item: item.ref)
    ] or ["- none"]
    return "\n\n".join(
        [
            f"Applied compilation {applied.action_id}.",
            "Written paths and hashes\n" + "\n".join(paths),
            "Affected definitions\n" + "\n".join(affected),
            f"Audit record\n{applied.audit_path}",
        ]
    )


def render_committed_compilation_cleanup_error(
    pending: PendingCompilation,
    error: FileTransactionCommittedError,
    audit_path: Path,
) -> str:
    hashes = {item.destination: item.after_hash for item in pending.files}
    paths = [f"- {path}: {hashes.get(path, 'audit record')}" for path in error.written_paths]
    cleanup = [f"- {item}" for item in error.cleanup_errors] or ["- unknown cleanup failure"]
    return "\n\n".join(
        [
            f"Applied compilation {pending.action_id}; the transaction committed.",
            "Written paths and hashes\n" + "\n".join(paths),
            f"Audit record\n{audit_path}",
            "Post-commit cleanup was incomplete\n" + "\n".join(cleanup),
        ]
    )


def _pending_id(pending: PendingAction | None) -> str | None:
    if _is_pending_compilation(pending):
        return pending.action_id
    if isinstance(pending, PendingChangeSet):
        return pending.change_set_id
    return None


def _is_pending_compilation(pending: object) -> TypeIs[PendingCompilation]:
    from modelable.operations.compilation import PendingCompilation

    return isinstance(pending, PendingCompilation)


def _operation_target(operation: Operation) -> str:
    domain = getattr(operation, "domain", None)
    name = getattr(operation, "name", None)
    target = getattr(operation, "target", None)
    source = getattr(operation, "source", None)
    if domain and name:
        return f"{domain}.{name}@{getattr(operation, 'version', 1)}"
    if target:
        return str(target)
    if isinstance(source, str):
        return source
    return "workspace"
