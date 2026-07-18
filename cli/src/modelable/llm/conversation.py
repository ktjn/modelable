from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from modelable.compiler.workspace import load_workspace
from modelable.diagnostics.model import Diagnostic, render_diagnostic
from modelable.llm.context import build_workspace_summary
from modelable.llm.conversation_plan import (
    ChangeSetPlan,
    ClarificationPlan,
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


@dataclass(frozen=True)
class ConversationPreviewFile:
    path: Path
    existed_before: bool
    before_text: str
    after_text: str


@dataclass(frozen=True)
class ConversationReply:
    kind: Literal[
        "answer",
        "clarification",
        "preview",
        "applied",
        "discarded",
        "unsupported",
        "error",
    ]
    text: str
    change_set_id: str | None = None
    focused_ref: str | None = None
    changed: tuple[ChangedDefinition, ...] = ()
    affected: tuple[AffectedDefinition, ...] = ()
    compatibility: tuple[CompatibilityFinding, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    preview_files: tuple[ConversationPreviewFile, ...] = ()
    written_paths: tuple[Path, ...] = ()


class ConversationSession:
    def __init__(
        self,
        *,
        path: Path,
        provider: LLMProvider | None,
        focused_ref: str | None = None,
        repair_attempts: int = 1,
    ) -> None:
        self.path = path
        self.provider = provider
        self.focused_ref = focused_ref
        self.history: list[tuple[str, str]] = []
        self.pending: PendingChangeSet | None = None
        self.workspace = load_workspace(path)
        self.planner = ConversationPlanner(provider, repair_attempts=repair_attempts)
        self.editor: WorkspaceEditor | None = None
        self._reload_services()

    def turn(self, message: str) -> ConversationReply:
        normalized = message.strip()
        lowered = normalized.lower()
        if lowered in {"apply", "apply it", "confirm"} or normalized == "/apply":
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
                pending_plan=self.pending.plan if self.pending is not None else None,
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
            return self._preview(plan)
        return ConversationReply(kind="error", text="The request produced an unknown conversation plan.")

    def _preview(self, plan: ChangeSetPlan) -> ConversationReply:
        replaced_id = self.pending.change_set_id if self.pending is not None else None
        try:
            if self.editor is None:
                self.editor = WorkspaceEditor(self.path, workspace=self.workspace)
            pending = self.editor.preview(plan)
        except WorkspaceEditError as error:
            return ConversationReply(kind="error", text=f"Could not preview workspace changes: {error}")
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
            focused_ref=pending.focus_ref,
            changed=tuple(pending.changed),
            affected=tuple(pending.affected),
            compatibility=tuple(pending.compatibility),
            diagnostics=tuple(pending.diagnostics),
            preview_files=preview_files,
        )

    def _apply_pending(self) -> ConversationReply:
        if self.pending is None:
            return ConversationReply(kind="error", text="There is no pending change set to apply.")
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
            focused_ref=applied.focus_ref,
            changed=tuple(applied.changed),
            compatibility=tuple(applied.compatibility),
            written_paths=applied.written_paths,
        )

    def _discard_pending(self) -> ConversationReply:
        if self.pending is None:
            return ConversationReply(kind="error", text="There is no pending change set to discard.")
        change_set_id = self.pending.change_set_id
        self.pending = None
        return ConversationReply(
            kind="discarded",
            text=f"Discarded pending change set {change_set_id}.",
            change_set_id=change_set_id,
        )

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
