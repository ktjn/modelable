from __future__ import annotations

import re
from dataclasses import dataclass

from modelable.llm.conversation_plan import (
    ChangeSetPlan,
    ClarificationPlan,
    ConversationPlan,
    QueryKind,
    QueryPlan,
    UnsupportedPlan,
    conversation_plan_json_schema,
    parse_conversation_plan,
)
from modelable.llm.providers import LLMProvider, LLMRequest

SYSTEM_PROMPT = """You plan grounded requests against a Modelable workspace.
Return JSON only matching the supplied closed schema. Return exactly one of the four plan kinds:
- QueryPlan with kind "query" for deterministic workspace facts.
- ChangeSetPlan with kind "change_set" for typed workspace edits.
- ClarificationPlan with kind "clarification" when required intent is ambiguous.
- UnsupportedPlan with kind "unsupported" when the request is outside planning.

Ask for clarification instead of assuming ambiguous ownership, identity fields,
whether an address is inline or a reusable address model, or a projection source.
For changes to an existing contract, default to append-version operations and target
the appended version; do not rewrite a published version in place.
Compile, sync, publish, deployment, filesystem, shell command, and other external
operations are unsupported. Return UnsupportedPlan with roadmap_area "operations".
Never emit raw patches, filesystem paths, shell commands, validation overrides,
compile/sync/publish actions, or any external action escape hatch.
Do not include markdown fences, prose, or commentary outside the JSON object.
"""


@dataclass(frozen=True)
class PlannerContext:
    workspace_summary: str
    focused_ref: str | None
    history: tuple[tuple[str, str], ...]
    pending_plan: ChangeSetPlan | None


def build_conversation_request(*, message: str, context: PlannerContext) -> LLMRequest:
    return _request(message=message, context=context, validation_error=None)


class ConversationPlanner:
    def __init__(self, provider: LLMProvider | None, *, repair_attempts: int = 1) -> None:
        self.provider = provider
        self.repair_attempts = repair_attempts

    def plan(self, message: str, context: PlannerContext) -> ConversationPlan:
        if self.provider is None:
            return self._offline_plan(message, context)
        request = build_conversation_request(message=message, context=context)
        response = self.provider.complete(request)
        try:
            return parse_conversation_plan(response.content)
        except Exception as error:
            return self._repair(message, context, error)

    def _repair(
        self,
        message: str,
        context: PlannerContext,
        error: Exception,
    ) -> ConversationPlan:
        if self.provider is None:
            raise RuntimeError("Conversation plan repair requires an LLM provider")
        validation_error = str(error)
        for _ in range(self.repair_attempts):
            response = self.provider.complete(
                _request(
                    message=message,
                    context=context,
                    validation_error=validation_error,
                )
            )
            try:
                return parse_conversation_plan(response.content)
            except Exception as repair_error:
                validation_error = str(repair_error)
        return UnsupportedPlan(
            request=message,
            reason=f"The configured provider did not return a valid typed plan: {validation_error}",
        )

    def _offline_plan(self, message: str, context: PlannerContext) -> ConversationPlan:
        stripped = message.strip()
        if stripped.startswith("/"):
            command, _, arguments = stripped.partition(" ")
            command = command.lower()
            arguments = arguments.strip()
            if command == "/context":
                return QueryPlan(query_kind="summary", refs=[], question=message)
            if command == "/describe":
                ref = arguments or context.focused_ref
                return QueryPlan(query_kind="summary", refs=[ref] if ref else [], question=message)
            if command == "/ask":
                if not arguments:
                    return ClarificationPlan(
                        question="What workspace question should I answer?",
                        reason="/ask requires a deterministic workspace question.",
                    )
                return self._offline_plan(arguments, context)
            if command in {"/update", "/create", "/change"}:
                return self._provider_required(message)
            return UnsupportedPlan(
                request=message,
                reason=f"Slash command {command} is not a conversational planning command.",
            )

        lower = stripped.lower()
        if any(operation in lower for operation in ("compile", "sync", "publish", "deploy", "external")):
            return UnsupportedPlan(
                request=message,
                reason="Operational and external actions are outside conversational workspace planning.",
                roadmap_area="operations",
            )
        if re.search(
            r"\b(?:add|create|change|rename|remove|delete|set|update|replace|make)\b",
            lower,
        ):
            return self._provider_required(message)

        refs = _extract_refs(stripped)
        focused_refs = refs or ([context.focused_ref] if context.focused_ref else [])
        query_kind: QueryKind | None = None
        required_refs = 1
        if "owner" in lower or "who owns" in lower:
            query_kind = "ownership"
        elif "lineage" in lower or "where did" in lower:
            query_kind = "lineage"
        elif "depend" in lower or "impact" in lower or "break" in lower:
            query_kind = "dependents"
        elif "index" in lower or "look it up" in lower:
            query_kind = "indexes"
        elif "compatib" in lower:
            query_kind = "compatibility"
            required_refs = 2
            focused_refs = refs
        elif "valid" in lower or "diagnostic" in lower:
            return QueryPlan(query_kind="validation", refs=[], question=message)
        elif any(token in lower for token in ("summary", "describe", "field", "model", "projection")):
            return QueryPlan(
                query_kind="summary",
                refs=focused_refs[:1],
                question=message,
            )

        if query_kind is not None:
            if len(focused_refs) != required_refs:
                return ClarificationPlan(
                    question=(
                        f"Which {'two model versions' if required_refs == 2 else 'model or projection'} "
                        f"should I use for this {query_kind} query?"
                    ),
                    reason=f"{query_kind} queries require exactly {required_refs} reference(s).",
                )
            return QueryPlan(
                query_kind=query_kind,
                refs=focused_refs,
                question=message,
            )
        return self._provider_required(message)

    @staticmethod
    def _provider_required(message: str) -> UnsupportedPlan:
        return UnsupportedPlan(
            request=message,
            reason=(
                "This request requires intent synthesis. Configure an LLM provider for conversational change planning."
            ),
        )


def _request(
    *,
    message: str,
    context: PlannerContext,
    validation_error: str | None,
) -> LLMRequest:
    lines = [f"Workspace summary:\n{context.workspace_summary}"]
    lines.append(f"Focused reference: {context.focused_ref or 'none'}")
    if context.history:
        lines.append("Conversation history:")
        lines.extend(f"{role}: {text}" for role, text in context.history)
    if context.pending_plan is not None:
        lines.append(f"Pending typed change set:\n{context.pending_plan.model_dump_json()}")
    lines.append(f"User request:\n{message}")
    if validation_error is not None:
        lines.append(
            "Previous response validation error:\n"
            f"{validation_error}\n"
            "Return a corrected JSON object matching the supplied schema."
        )
    return LLMRequest(
        system=SYSTEM_PROMPT,
        user="\n\n".join(lines),
        temperature=0.05 if validation_error is not None else 0.1,
        response_format="json",
        schema=conversation_plan_json_schema(),
    )


_REF_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_-]*\.[A-Za-z_][A-Za-z0-9_-]*@\d+\b")


def _extract_refs(message: str) -> list[str]:
    return _REF_RE.findall(message)
