from __future__ import annotations

import difflib
import re
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
    workspace_summary: str | None = None
    history: list[tuple[str, str]] = field(default_factory=list)


CHAT_SYSTEM_PROMPT = """You are Modelable's interactive assistant.
Answer using the current workspace context only.
If the user asks for a model edit, explain that edit requests are previewed through the update pipeline and do not claim that files were written.
If the user asks for a summary, be concise and factual.
If the user asks a question you cannot answer from the context, say what is missing.
"""


def chat_reply(
    workspace: Workspace,
    message: str,
    *,
    ref: str | None = None,
    workspace_summary: str | None = None,
    provider: LLMProvider | None = None,
    history: Iterable[tuple[str, str]] | None = None,
) -> str:
    if provider is None:
        return answer_question(workspace, message)

    user = _build_user_prompt(workspace, message, ref=ref, workspace_summary=workspace_summary, history=history)
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
    elif _looks_like_update_request(stripped):
        ref = _resolve_update_ref(stripped, state.ref)
        if ref is None:
            response = "Provide a ref or set one with /ref."
        else:
            instruction = _strip_update_ref_from_message(stripped, ref=ref)
            try:
                result = update_definition(path, ref, instruction, provider=provider, write=False)
            except ValueError as exc:
                response = f"ERROR: {exc}"
            else:
                response = _render_update_preview(result)
    else:
        response = chat_reply(
            workspace,
            message,
            ref=state.ref,
            workspace_summary=state.workspace_summary,
            provider=provider,
            history=state.history,
        )
    state.history.append(("user", message))
    state.history.append(("assistant", response))
    return response


def _build_user_prompt(
    workspace: Workspace,
    message: str,
    *,
    ref: str | None = None,
    workspace_summary: str | None = None,
    history: Iterable[tuple[str, str]] | None = None,
) -> str:
    if ref is None:
        context = workspace_summary or build_workspace_summary(workspace)
    else:
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
            return chat_reply(
                workspace,
                question,
                ref=state.ref,
                workspace_summary=state.workspace_summary,
                provider=provider,
                history=state.history,
            )
        return answer_question(workspace, question)
    if command == "update":
        ref = args[0] if args else state.ref
        if ref is None:
            return "Provide a ref or set one with /ref."
        instruction = " ".join(args[1:]).strip() if len(args) > 1 else ""
        if not instruction:
            return "Provide an edit instruction after /update."
        try:
            result = update_definition(path, ref, instruction, provider=provider, write=False)
        except ValueError as exc:
            return f"ERROR: {exc}"
        return _render_update_preview(result)
    if command in {"exit", "quit"}:
        return "/exit"
    return f"Unknown command: {command}. Try /help."


def _chat_help() -> str:
    return (
        "Commands: /help, /ref <ref>, /context, /describe [ref], /recommend <ref> [consumer], "
        "/ask <question>, /update <ref> <instruction> (preview only), /exit"
    )


def _render_update_preview(result) -> str:
    return _render_update_result(result, written=False)


def _render_update_result(result, *, written: bool = True) -> str:
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
    if written:
        rendered = f"Wrote changes to {result.path}\n{rendered}"
    return rendered


def _looks_like_update_request(message: str) -> bool:
    lowered = message.lower().strip()
    if lowered.endswith("?") and lowered.startswith(("how do i ", "how to ", "what is ", "why does ", "why is ")):
        return False
    if lowered.startswith(("please ", "please,", "could you ", "can you ", "would you ", "kindly ")):
        return True
    if re.match(r"^(make|rename|add|remove|delete|change|set|update|replace)\b", lowered):
        return True
    return any(f" {verb} " in lowered for verb in ("make", "rename", "add", "remove", "delete", "change", "set", "update", "replace"))


def _resolve_update_ref(message: str, fallback_ref: str | None) -> str | None:
    explicit_ref = _find_model_ref_in_message(message)
    if explicit_ref is not None:
        return explicit_ref
    return fallback_ref


def _find_model_ref_in_message(message: str) -> str | None:
    match = re.search(r"\b([A-Za-z_][A-Za-z0-9_-]*\.[A-Za-z_][A-Za-z0-9_-]*@\d+)\b", message)
    if match is None:
        return None
    candidate = match.group(1)
    try:
        parse_model_ref(candidate)
    except ValueError:
        return None
    return candidate


def _strip_update_ref_from_message(message: str, *, ref: str) -> str:
    cleaned = re.sub(rf"\b{re.escape(ref)}\b", "", message, count=1).strip()
    return cleaned.lstrip(" ,:;-")
