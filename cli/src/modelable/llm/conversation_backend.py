from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    from modelable.diagnostics.model import Diagnostic
    from modelable.llm.conversation_plan import ChangeSetPlan, CompilePlan, QueryPlan
    from modelable.llm.workspace_editor import (
        AffectedDefinition,
        ChangedDefinition,
        CompatibilityFinding,
    )
    from modelable.operations.compilation import CompilationFilePreview, RegistryIdChange

type ReplyKind = Literal[
    "answer",
    "clarification",
    "preview",
    "applied",
    "discarded",
    "unsupported",
    "error",
]


class ConversationCleanupError(RuntimeError):
    def __init__(self, errors: tuple[str, ...]) -> None:
        self.errors = errors
        super().__init__("Conversation cleanup failed:\n" + "\n".join(f"- {error}" for error in errors))


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
    assumptions: tuple[str, ...] = ()
    changed: tuple[ChangedDefinition, ...] = ()
    affected: tuple[AffectedDefinition, ...] = ()
    compatibility: tuple[CompatibilityFinding, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    preview_files: tuple[ConversationPreviewFile, ...] = ()
    written_paths: tuple[Path, ...] = ()
    compilation_files: tuple[CompilationFilePreview, ...] = ()
    registry_id_changes: tuple[RegistryIdChange, ...] = ()
    audit_path: Path | None = None


class ConversationBackend(Protocol):
    def workspace_summary(self, focused_ref: str | None = None) -> str: ...

    def execute_query(self, plan: QueryPlan) -> ConversationReply: ...

    def preview_source_change(
        self,
        plan: ChangeSetPlan,
        replaced_action_id: str | None,
    ) -> ConversationReply: ...

    def preview_compilation(
        self,
        plan: CompilePlan,
        replaced_action_id: str | None,
    ) -> ConversationReply: ...

    def apply(self, action_id: str) -> ConversationReply: ...

    def discard(self, action_id: str) -> ConversationReply: ...

    def reset(self) -> None: ...
