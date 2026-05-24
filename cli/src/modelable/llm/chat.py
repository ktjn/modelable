from __future__ import annotations

import difflib
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from modelable.compiler.workspace import Workspace
from modelable.llm.context import build_model_summary, build_projection_summary, build_workspace_summary, parse_model_ref
from modelable.llm.providers import LLMProvider, LLMRequest
from modelable.llm.qa import answer_question
from modelable.llm.engine import recommend_cli, update_definition


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


def chat_turn(
    workspace: Workspace,
    message: str,
    *,
    path: Path,
    state: ChatState,
    provider: LLMProvider | None = None,
) -> str:
    stripped = message.strip()
    if stripped.startswith("/"):
        response = _handle_chat_command(workspace, path, stripped, state=state, provider=provider)
    else:
        response = chat_reply(workspace, message, ref=state.ref, provider=provider, history=state.history)
    state.history.append(("user", message))
    state.history.append(("assistant", response))
    return response


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


def _handle_chat_command(
    workspace: Workspace,
    path: Path,
    command_text: str,
    *,
    state: ChatState,
    provider: LLMProvider | None,
) -> str:
    parts = shlex.split(command_text)
    if not parts:
        return "Empty command."
    command = parts[0].lstrip("/").lower()
    args = parts[1:]

    if command in {"help", "?"}:
        return _chat_help()
    if command == "ref":
        if not args:
            return state.ref or "No focus ref is set."
        state.ref = args[0]
        return f"Focused on {state.ref}."
    if command == "context":
        return _build_context_summary(workspace, ref=state.ref)
    if command == "describe":
        ref = args[0] if args else state.ref
        if ref:
            return _build_context_summary(workspace, ref=ref)
        return build_workspace_summary(workspace)
    if command == "recommend":
        ref = args[0] if args else state.ref
        consumer = args[1] if len(args) > 1 else None
        if ref is None:
            return "Provide a ref or set one with /ref."
        return recommend_cli(path, ref=ref, consumer=consumer)
    if command == "ask":
        question = " ".join(args).strip()
        if not question:
            return "Provide a question after /ask."
        if provider is not None:
            return chat_reply(workspace, question, ref=state.ref, provider=provider, history=state.history)
        return answer_question(workspace, question)
    if command == "update":
        ref = args[0] if args else state.ref
        if ref is None:
            return "Provide a ref or set one with /ref."
        instruction = " ".join(args[1:]).strip() if len(args) > 1 else ""
        if not instruction:
            return "Provide an edit instruction after /update."
        result = update_definition(path, ref, instruction, provider=provider, write=False)
        return _render_update_preview(result)
    if command in {"exit", "quit"}:
        return "/exit"
    return f"Unknown command: {command}. Try /help."


def _chat_help() -> str:
    return (
        "Commands: /help, /ref <ref>, /context, /describe [ref], /recommend <ref> [consumer], "
        "/ask <question>, /update <ref> <instruction>, /exit"
    )


def _render_update_preview(result) -> str:
    diff = difflib.unified_diff(
        result.original_content.splitlines(),
        result.content.splitlines(),
        fromfile=str(result.path),
        tofile=f"{result.path} (preview)",
        lineterm="",
    )
    rendered = "\n".join(diff)
    if not rendered:
        rendered = result.content
    if result.warnings:
        rendered += "\n" + "\n".join(f"WARN: {warning}" for warning in result.warnings)
    return rendered
