from __future__ import annotations

from modelable.browser.dto import (
    BrowserAiExplainResult,
    BrowserAiGenerateResult,
    BrowserAiPendingResult,
    BrowserDiagnostic,
    BrowserLlmRequest,
)
from modelable.browser.errors import BrowserLanguageError
from modelable.diagnostics.model import Diagnostic
from modelable.language.workspace import LanguageWorkspace
from modelable.llm.context import build_workspace_summary
from modelable.validation.semantic import validate_diagnostics


_GENERATE_ENTITY_SYSTEM = """\
You are a domain modeling assistant. You write valid Modelable .mdl source.
Given a natural-language description of a business entity, produce a complete
.mdl entity definition. Include a primary key field using uuid type with @key,
and add fields that match the description. Use snake_case for field names.
Output ONLY the .mdl source with no explanation or markdown fences."""

_SUGGEST_PROJECTION_SYSTEM = """\
You are a domain modeling assistant. You write valid Modelable .mdl source.
Given a source model definition and a consumer domain name, produce a
projection that exposes the source model's fields relevant to the consumer.
Exclude PII and server-only fields. Output ONLY the .mdl source with no
explanation or markdown fences."""

_EXPLAIN_SYSTEM = """\
You are a domain modeling assistant. Given a Modelable workspace summary and
an optional model reference or diagnostic, provide a clear, concise explanation
in plain English. Focus on what the element does, why it exists, and how it
relates to other definitions in the workspace."""


def build_generate_entity_request(
    language: LanguageWorkspace,
    description: str,
    domain_name: str | None,
    model_name: str | None,
) -> BrowserAiPendingResult:
    semantic = language.semantic_workspace()
    if semantic is None:
        raise BrowserLanguageError("LANGUAGE_UNAVAILABLE")

    workspace_summary = build_workspace_summary(semantic)
    parts = [f"Workspace context:\n{workspace_summary}\n"]
    parts.append(f"Description: {description}")
    if domain_name:
        parts.append(f"Domain: {domain_name}")
    if model_name:
        parts.append(f"Entity name: {model_name}")

    return BrowserAiPendingResult(
        llm_request=BrowserLlmRequest(
            system=_GENERATE_ENTITY_SYSTEM,
            user="\n".join(parts),
            temperature=0.2,
            response_format="text",
        ),
    )


def build_suggest_projection_request(
    language: LanguageWorkspace,
    source_ref: str,
    consumer_domain: str,
) -> BrowserAiPendingResult:
    semantic = language.semantic_workspace()
    if semantic is None:
        raise BrowserLanguageError("LANGUAGE_UNAVAILABLE")

    from modelable.llm.context import build_model_summary

    workspace_summary = build_workspace_summary(semantic)
    model_summary = build_model_summary(semantic, source_ref)

    user_prompt = (
        f"Workspace context:\n{workspace_summary}\n\n"
        f"Source model:\n{model_summary}\n\n"
        f"Consumer domain: {consumer_domain}\n"
        f"Create a projection of this model for the {consumer_domain} domain."
    )

    return BrowserAiPendingResult(
        llm_request=BrowserLlmRequest(
            system=_SUGGEST_PROJECTION_SYSTEM,
            user=user_prompt,
            temperature=0.2,
            response_format="text",
        ),
    )


def build_explain_request(
    language: LanguageWorkspace,
    ref: str | None,
    diagnostic_index: int | None,
) -> BrowserAiPendingResult:
    semantic = language.semantic_workspace()
    if semantic is None:
        raise BrowserLanguageError("LANGUAGE_UNAVAILABLE")

    workspace_summary = build_workspace_summary(semantic)
    parts = [f"Workspace context:\n{workspace_summary}\n"]

    if ref:
        from modelable.llm.context import build_model_summary

        model_summary = build_model_summary(semantic, ref)
        parts.append(f"Explain this model:\n{model_summary}")
    elif diagnostic_index is not None:
        diagnostics = list(semantic.errors)
        if 0 <= diagnostic_index < len(diagnostics):
            diag = diagnostics[diagnostic_index]
            parts.append(f"Explain this diagnostic:\n{diag.message}")
        else:
            parts.append("Explain the overall workspace structure.")
    else:
        parts.append("Explain the overall workspace structure.")

    return BrowserAiPendingResult(
        llm_request=BrowserLlmRequest(
            system=_EXPLAIN_SYSTEM,
            user="\n".join(parts),
            temperature=0.2,
            response_format="text",
        ),
    )


def _browser_diagnostic(diagnostic: Diagnostic) -> BrowserDiagnostic:
    return BrowserDiagnostic(
        code=diagnostic.code,
        severity=diagnostic.severity,
        message=diagnostic.message,
        uri=diagnostic.path,
        line=diagnostic.line,
        column=diagnostic.column,
        end_line=diagnostic.end_line,
        end_column=diagnostic.end_column,
    )


def parse_generate_result(
    llm_content: str,
) -> BrowserAiGenerateResult:
    source = _strip_code_fences(llm_content)
    diagnostics = _validate_source(source)
    return BrowserAiGenerateResult(
        source=source,
        diagnostics=diagnostics,
    )


def parse_explain_result(
    llm_content: str,
) -> BrowserAiExplainResult:
    return BrowserAiExplainResult(explanation=llm_content.strip())


def _strip_code_fences(text: str) -> str:
    lines = text.strip().splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines)


def _validate_source(source: str) -> tuple[BrowserDiagnostic, ...]:
    from modelable.compiler.workspace import WorkspaceDocumentSource, load_workspace_from_sources
    from modelable.parser.ir import ParseError
    from modelable.parser.parse import parse_text_to_ir

    uri = "ai-generated.mdl"
    try:
        parse_text_to_ir(source, path=uri)
    except ParseError as error:
        return (_browser_diagnostic(error.diagnostic(uri)),)

    try:
        workspace = load_workspace_from_sources(
            [WorkspaceDocumentSource(path=None, uri=uri, text=source)]
        )
    except ParseError as error:
        return (_browser_diagnostic(error.diagnostic(uri)),)

    return tuple(
        _browser_diagnostic(diagnostic)
        for diagnostic in validate_diagnostics(workspace.mdl, path=uri)
    )
