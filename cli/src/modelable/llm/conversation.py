from __future__ import annotations

import re
import unicodedata
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from modelable.compiler.workspace import Workspace
from modelable.diagnostics.model import render_diagnostic
from modelable.llm.conversation_backend import (
    ConversationCleanupError as ConversationCleanupError,
)
from modelable.llm.conversation_backend import (
    ConversationPreviewFile as ConversationPreviewFile,
)
from modelable.llm.conversation_backend import (
    ConversationReply as ConversationReply,
)
from modelable.llm.conversation_backend import (
    ReplyKind as ReplyKind,
)
from modelable.llm.conversation_engine import ConversationEngine
from modelable.llm.conversation_plan import CompilePlan, Operation
from modelable.llm.conversation_planner import (
    PendingPlanRequest,
    ResumableConversationPlanner,
)
from modelable.llm.provider_types import LLMProvider
from modelable.llm.workspace_editor import (
    AppliedChangeSet,
    PendingChangeSet,
    WorkspaceEditor,
)
from modelable.llm.workspace_query import QueryResult, WorkspaceQueryService

if TYPE_CHECKING:
    from modelable.operations.compilation import (
        AppliedCompilation,
        CompilationService,
        PendingCompilation,
    )
    from modelable.operations.file_transaction import FileTransactionCommittedError


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
        confirmation_surface: Literal["cli-chat", "vscode-chat"] = "cli-chat",
    ) -> None:
        from modelable.llm.filesystem_conversation import FilesystemConversationBackend

        self.path = path
        self.provider = provider
        self.session_id = session_id or str(uuid.uuid4())
        self.provider_name = provider_name
        self.model_name = model_name
        self.confirmation_surface = confirmation_surface
        self.backend = FilesystemConversationBackend(
            path=path,
            compilation_service=compilation_service,
            session_id=self.session_id,
            provider_name=provider_name,
            model_name=model_name,
            confirmation_surface=confirmation_surface,
        )
        self.engine = ConversationEngine(
            backend=self.backend,
            planner=ResumableConversationPlanner(repair_attempts=repair_attempts),
            focused_ref=focused_ref,
            completion_enabled=provider is not None,
        )

    @property
    def pending(self) -> PendingChangeSet | PendingCompilation | None:
        return self.backend.pending

    @property
    def pending_action_id(self) -> str | None:
        return self.engine.pending_action_id

    @property
    def pending_operation_kind(self) -> Literal["source_change", "compile"] | None:
        return cast(
            Literal["source_change", "compile"] | None,
            self.engine.pending_operation_kind,
        )

    @property
    def pending_cleanup_ids(self) -> tuple[str, ...]:
        return self.backend.pending_cleanup_ids

    @property
    def focused_ref(self) -> str | None:
        return self.engine.focused_ref

    @focused_ref.setter
    def focused_ref(self, value: str | None) -> None:
        self.engine.focused_ref = value

    @property
    def history(self) -> list[tuple[str, str]]:
        return self.engine.history

    @property
    def workspace(self) -> Workspace:
        return self.backend.workspace

    @property
    def editor(self) -> WorkspaceEditor | None:
        return self.backend.editor

    @property
    def query_service(self) -> WorkspaceQueryService:
        return self.backend.query_service

    @property
    def compilation_service(self) -> CompilationService:
        return self.backend.compilation_service

    def turn(self, message: str) -> ConversationReply:
        try:
            normalized = message.strip()
            lowered = normalized.lower()
            if (
                self.backend.pending is None
                and self.backend.cleanup_action_id is not None
                and (lowered in {"discard", "discard it", "cancel"} or normalized == "/discard")
            ):
                reply = self.backend.discard(self.backend.cleanup_action_id)
                return self.engine.record_completed_reply(message, reply)
            outcome = self.engine.begin_turn(message)
            while isinstance(outcome, PendingPlanRequest):
                if self.provider is None:
                    outcome = self.engine.fail_turn(
                        outcome.request_id,
                        RuntimeError("Pending planning requires a provider"),
                    )
                    break
                try:
                    response = self.provider.complete(outcome.request)
                except Exception as error:
                    outcome = self.engine.fail_turn(outcome.request_id, error)
                    break
                outcome = self.engine.resume_turn(outcome.request_id, response.content)
            self.engine.synchronize_pending_action(
                self.backend.pending_action_id,
                self.backend.pending_operation_kind,
            )
            return outcome
        except BaseException as error:
            self.backend.cleanup_after_exception(error)
            raise

    def close(self) -> None:
        self.backend.close()


def render_query_result(result: QueryResult) -> str:
    return result.text


def render_pending_change_set(pending: PendingChangeSet) -> str:
    assumptions = [f"- {_escape_inline(assumption)}" for assumption in pending.assumptions] or ["- none"]
    operations = [
        f"- {_escape_inline(operation.kind)}: {_escape_inline(_operation_target(operation))}"
        for operation in pending.plan.operations
    ] or ["- none"]
    changed = [
        f"- {_escape_inline(item.ref)}: {_escape_inline(item.reason)}"
        for item in sorted(pending.changed, key=lambda item: item.ref)
    ] or ["- none"]
    affected = [
        f"- {_escape_inline(item.ref)} [{_escape_inline(item.status)}]: {_escape_inline(item.reason)}"
        for item in sorted(pending.affected, key=lambda item: item.ref)
    ] or ["- none"]
    findings = [
        f"- {_escape_inline(item.ref)} [{_escape_inline(item.status)}]: {_escape_inline(item.message)}"
        for item in sorted(pending.compatibility, key=lambda item: item.ref)
    ]
    findings.extend(
        f"- {_escape_inline(render_diagnostic(diagnostic))}"
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
    diff_text = _code_block(pending.diff_text, "diff") if pending.diff_text else "- none"
    return "\n\n".join(
        [
            "Summary\n" + _code_block(pending.plan.summary),
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
    paths = [f"- {_escape_inline(path)}" for path in sorted(applied.written_paths)] or ["- none"]
    changed = [
        f"- {_escape_inline(item.ref)}: {_escape_inline(item.reason)}"
        for item in sorted(applied.changed, key=lambda item: item.ref)
    ] or ["- none"]
    compatibility = [
        f"- {_escape_inline(item.ref)} [{_escape_inline(item.status)}]: {_escape_inline(item.message)}"
        for item in sorted(applied.compatibility, key=lambda item: item.ref)
    ] or ["- none"]
    focus = _escape_inline(applied.focus_ref or "none")
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
    from modelable.operations.compilation import default_output_dir, is_text_media_type

    domains = ", ".join(_escape_inline(domain) for domain in plan.domains) if plan.domains else "all"
    output = _escape_inline(plan.output or default_output_dir(plan.target).as_posix())
    affected = [
        f"- {_escape_inline(item.ref)} [{_escape_inline(item.status)}]: {_escape_inline(item.reason)}"
        for item in sorted(pending.affected_definitions, key=lambda item: item.ref)
    ] or ["- none"]
    sections = [
        "Summary\n" + _code_block(plan.summary),
        (
            "Normalized plan\n"
            f"- target: {_escape_inline(plan.target)}\n"
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
        files = [
            f"- {_escape_inline(item.destination)} [{_escape_inline(item.category)}]"
            for item in pending.files
            if item.status == status
        ] or ["- none"]
        sections.append(title + "\n" + "\n".join(files))
    registry_ids = [f"- {_escape_inline(item.ref)}: {item.registry_id}" for item in pending.registry_id_changes] or [
        "- none"
    ]
    sections.append("Registry-ID additions\n" + "\n".join(registry_ids))
    text_diffs = [
        f"{_escape_inline(item.destination)}\n{_code_block(item.diff_text, 'diff')}"
        for item in pending.files
        if item.diff_text is not None
    ] or ["- none"]
    sections.append("Text diffs\n" + "\n".join(text_diffs))
    binaries = [
        (
            f"- {_escape_inline(item.destination)}: {item.before_size} bytes "
            f"({_escape_inline(item.before_hash or 'none')}) -> {item.after_size} bytes "
            f"({_escape_inline(item.after_hash)})"
        )
        for item in pending.files
        if not is_text_media_type(item.media_type)
    ] or ["- none"]
    sections.append("Binary files\n" + "\n".join(binaries))
    warnings = [_code_block(warning) for warning in pending.warnings] or ["- none"]
    sections.append("Warnings\n" + "\n".join(warnings))
    sections.append(
        "Only the exact case-sensitive /apply command applies this compilation. "
        "Use /discard to cancel it or another request to replace it."
    )
    return "\n\n".join(sections)


def render_applied_compilation(applied: AppliedCompilation) -> str:
    hashes = {item.destination: item.after_hash for item in applied.files}
    paths = [
        f"- {_escape_inline(path)}: {_escape_inline(hashes.get(path, 'audit record'))}"
        for path in applied.written_paths
    ] or ["- none"]
    affected = [
        f"- {_escape_inline(item.ref)} [{_escape_inline(item.status)}]: {_escape_inline(item.reason)}"
        for item in sorted(applied.affected_definitions, key=lambda item: item.ref)
    ] or ["- none"]
    return "\n\n".join(
        [
            f"Applied compilation {applied.action_id}.",
            "Written paths and hashes\n" + "\n".join(paths),
            "Affected definitions\n" + "\n".join(affected),
            f"Audit record\n{_escape_inline(applied.audit_path)}",
        ]
    )


def render_committed_compilation_cleanup_error(
    pending: PendingCompilation,
    error: FileTransactionCommittedError,
    audit_path: Path,
) -> str:
    hashes = {item.destination: item.after_hash for item in pending.files}
    paths = [
        f"- {_escape_inline(path)}: {_escape_inline(hashes.get(path, 'audit record'))}" for path in error.written_paths
    ]
    cleanup = [f"- {_escape_inline(item)}" for item in error.cleanup_errors] or ["- unknown cleanup failure"]
    return "\n\n".join(
        [
            f"Applied compilation {pending.action_id}; the transaction committed.",
            "Written paths and hashes\n" + "\n".join(paths),
            f"Audit record\n{_escape_inline(audit_path)}",
            "Post-commit cleanup was incomplete\n" + "\n".join(cleanup),
        ]
    )


_ANSI_ESCAPE_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\)?)")
_MARKDOWN_META = frozenset(r"\`*_[]<>#|")


def _neutralize(value: object) -> str:
    text = _ANSI_ESCAPE_RE.sub("", str(value)).replace("\r\n", "\n").replace("\r", "\n")
    return "".join(
        character
        if character in "\n\t" or unicodedata.category(character) not in {"Cc", "Cf"}
        else "\N{REPLACEMENT CHARACTER}"
        for character in text
    )


def _escape_inline(value: object) -> str:
    text = _neutralize(value).replace("\n", " ").replace("\t", " ")
    return "".join(f"\\{character}" if character in _MARKDOWN_META else character for character in text)


def _code_block(value: object, language: str = "text") -> str:
    text = _neutralize(value)
    longest = max((len(match.group(0)) for match in re.finditer(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}{language}\n{text}\n{fence}"


def _render_cleanup_failure(summary: str, errors: tuple[str, ...]) -> str:
    return "\n\n".join(
        [
            _escape_inline(summary),
            "Cleanup errors\n" + "\n".join(f"- {_escape_inline(error)}" for error in errors),
            "Use /discard to retry cleanup or close the session.",
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
