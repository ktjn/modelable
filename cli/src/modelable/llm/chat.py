from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from modelable.compiler.workspace import Workspace
from modelable.llm.context import build_model_summary, build_projection_summary, build_workspace_summary, parse_model_ref
from modelable.llm.providers import LLMProvider, LLMRequest
from modelable.llm.qa import answer_question


@dataclass
class ChatState:
    ref: str | None = None
    history: list[tuple[str, str]] = field(default_factory=list)


CHAT_SYSTEM_PROMPT = """You are Modelable's interactive assistant.
Answer using the current workspace context only.
If the user asks for a model edit, explain the exact `modelable update` command they should run.
If the user asks for a summary, be concise and factual.
If the user asks a question you cannot answer from the context, say what is missing.
"""


def chat_reply(
    workspace: Workspace,
    message: str,
    *,
    ref: str | None = None,
    provider: LLMProvider | None = None,
    history: Iterable[tuple[str, str]] | None = None,
) -> str:
    if provider is None:
        return answer_question(workspace, message)

    user = _build_user_prompt(workspace, message, ref=ref, history=history)
    response = provider.complete(LLMRequest(system=CHAT_SYSTEM_PROMPT, user=user, temperature=0.2))
    return response.content.strip() or "No response returned."


def _build_user_prompt(
    workspace: Workspace,
    message: str,
    *,
    ref: str | None = None,
    history: Iterable[tuple[str, str]] | None = None,
) -> str:
    context = _build_context_summary(workspace, ref=ref)
    lines = [f"Workspace context:\n{context}"]
    if history:
        lines.append("Conversation:")
        for role, text in history:
            lines.append(f"{role}: {text}")
    lines.append(f"user: {message}")
    return "\n\n".join(lines)


def _build_context_summary(workspace: Workspace, *, ref: str | None) -> str:
    if ref is None:
        return build_workspace_summary(workspace)
    model_ref = parse_model_ref(ref)
    domain = next((d for d in workspace.mdl.domains if d.name == model_ref.domain), None)
    if domain is None:
        return f"Unknown domain: {model_ref.domain}"
    if model_ref.name in domain.models:
        return build_model_summary(workspace, ref)
    if model_ref.name in domain.projections:
        return build_projection_summary(workspace, ref)
    return f"Unknown model or projection: {ref}"
