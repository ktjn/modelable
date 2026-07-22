from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from modelable.browser.api import BrowserCompiler
from modelable.browser.dto import (
    BrowserAiExplainResult,
    BrowserAiGenerateResult,
    BrowserAiPendingResult,
    BrowserCompatibilityResult,
    BrowserCompileResult,
    BrowserCompletionResult,
    BrowserDefinitionResult,
    BrowserFormatResult,
    BrowserGovernanceResult,
    BrowserGraphResult,
    BrowserHoverResult,
    BrowserLanguagePosition,
    BrowserLineageResult,
    BrowserPreparedRenameResult,
    BrowserReferencesResult,
    BrowserRenameResult,
    BrowserSource,
    BrowserWorkspaceResult,
)
from modelable.browser.errors import BrowserLanguageError, BrowserRequestValidationError

_METHODS = {
    "workspace.open",
    "source.format",
    "compile.jsonSchema",
    "language.completion",
    "language.hover",
    "language.definition",
    "language.references",
    "language.prepareRename",
    "language.rename",
    "workspace.graph",
    "workspace.lineage",
    "workspace.compatibility",
    "workspace.governance",
    "ai.generate",
    "ai.explain",
}
_SOURCE_FIELDS = {"uri", "text", "version"}
_LANGUAGE_POSITION_FIELDS = {
    "workspaceRevision",
    "uri",
    "line",
    "character",
}
_GRAPH_MODES = {"domain", "entity"}
_AI_GENERATE_ACTIONS = {"generate_entity", "suggest_projection"}
_ERROR_MESSAGES = {
    "INVALID_REQUEST": "Payload does not match method schema",
    "STALE_WORKSPACE": "Requested workspace revision is not current",
    "LANGUAGE_UNAVAILABLE": "Language services are unavailable",
    "INVALID_POSITION": "Requested language position is invalid",
    "INVALID_RENAME": "Rename target is invalid or produces a conflict",
}
_compiler = BrowserCompiler()


def _error_response(code: str) -> str:
    return json.dumps(
        {
            "ok": False,
            "error": {
                "code": code,
                "message": _ERROR_MESSAGES[code],
            },
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _require_exact_fields(value: dict[str, Any], fields: set[str]) -> None:
    if set(value) != fields:
        raise BrowserRequestValidationError("Payload does not match method schema")


def _source(value: Any) -> BrowserSource:
    if not isinstance(value, dict):
        raise BrowserRequestValidationError("Source must be an object")
    _require_exact_fields(value, _SOURCE_FIELDS)
    uri = value["uri"]
    text = value["text"]
    version = value["version"]
    if (
        not isinstance(uri, str)
        or not isinstance(text, str)
        or not isinstance(version, int)
        or isinstance(version, bool)
    ):
        raise BrowserRequestValidationError("Source fields have invalid types")
    try:
        return BrowserSource(uri=uri, text=text, version=version)
    except BrowserRequestValidationError:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise BrowserRequestValidationError("Source could not be constructed") from error


def _sources(value: Any) -> tuple[BrowserSource, ...]:
    if not isinstance(value, list):
        raise BrowserRequestValidationError("Sources must be an array")
    return tuple(_source(source) for source in value)


def _integer(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise BrowserRequestValidationError("Expected an integer")
    return value


def _language_position(
    payload: dict[str, Any],
    extra_fields: set[str] | None = None,
) -> BrowserLanguagePosition:
    expected = _LANGUAGE_POSITION_FIELDS | (extra_fields or set())
    _require_exact_fields(payload, expected)
    uri = payload["uri"]
    if not isinstance(uri, str):
        raise BrowserRequestValidationError("Language URI must be a string")
    return BrowserLanguagePosition(
        workspace_revision=_integer(payload["workspaceRevision"]),
        uri=uri,
        line=_integer(payload["line"]),
        character=_integer(payload["character"]),
    )


_DispatchResult = (
    BrowserWorkspaceResult
    | BrowserFormatResult
    | BrowserCompileResult
    | BrowserCompletionResult
    | BrowserHoverResult
    | BrowserDefinitionResult
    | BrowserReferencesResult
    | BrowserPreparedRenameResult
    | BrowserRenameResult
    | BrowserGraphResult
    | BrowserLineageResult
    | BrowserCompatibilityResult
    | BrowserGovernanceResult
    | BrowserAiPendingResult
    | BrowserAiGenerateResult
    | BrowserAiExplainResult
)


def _dispatch(method: str, payload: dict[str, Any]) -> _DispatchResult:
    if method == "workspace.open":
        _require_exact_fields(payload, {"workspaceRevision", "sources"})
        return _compiler.open_workspace(
            _integer(payload["workspaceRevision"]),
            _sources(payload["sources"]),
        )
    if method == "source.format":
        _require_exact_fields(payload, {"source"})
        return _compiler.format_source(_source(payload["source"]))
    if method == "compile.jsonSchema":
        _require_exact_fields(payload, {"sources"})
        return _compiler.compile_json_schema(_sources(payload["sources"]))
    if method == "language.completion":
        return _compiler.completion(_language_position(payload))
    if method == "language.hover":
        return _compiler.hover(_language_position(payload))
    if method == "language.definition":
        return _compiler.definition(_language_position(payload))
    if method == "language.references":
        request = _language_position(payload, extra_fields={"includeDeclaration"})
        include_declaration = payload["includeDeclaration"]
        if not isinstance(include_declaration, bool):
            raise BrowserRequestValidationError("includeDeclaration must be a boolean")
        return _compiler.references(request, include_declaration)
    if method == "language.prepareRename":
        return _compiler.prepare_rename(_language_position(payload))
    if method == "language.rename":
        request = _language_position(payload, extra_fields={"newName"})
        new_name = payload["newName"]
        if not isinstance(new_name, str):
            raise BrowserRequestValidationError("newName must be a string")
        return _compiler.rename(request, new_name)
    if method == "workspace.graph":
        _require_exact_fields(payload, {"workspaceRevision", "mode"})
        mode = payload["mode"]
        if not isinstance(mode, str) or mode not in _GRAPH_MODES:
            raise BrowserRequestValidationError("mode must be 'domain' or 'entity'")
        return _compiler.graph(_integer(payload["workspaceRevision"]), mode)
    if method == "workspace.lineage":
        _require_exact_fields(payload, {"workspaceRevision"})
        return _compiler.lineage(_integer(payload["workspaceRevision"]))
    if method == "workspace.compatibility":
        _require_exact_fields(payload, {"workspaceRevision"})
        return _compiler.compatibility(_integer(payload["workspaceRevision"]))
    if method == "workspace.governance":
        _require_exact_fields(payload, {"workspaceRevision"})
        return _compiler.governance(_integer(payload["workspaceRevision"]))
    if method == "ai.generate":
        allowed = {"workspaceRevision", "action", "parameters", "llmResponseContent"}
        if set(payload) - allowed or "workspaceRevision" not in payload or "action" not in payload:
            raise BrowserRequestValidationError("Payload does not match method schema")
        action = payload["action"]
        if not isinstance(action, str) or action not in _AI_GENERATE_ACTIONS:
            raise BrowserRequestValidationError("action must be a valid generate action")
        parameters = payload.get("parameters", {})
        if not isinstance(parameters, dict):
            raise BrowserRequestValidationError("parameters must be an object")
        llm_response = payload.get("llmResponseContent")
        if llm_response is not None and not isinstance(llm_response, str):
            raise BrowserRequestValidationError("llmResponseContent must be a string or null")
        return _compiler.ai_generate(
            _integer(payload["workspaceRevision"]),
            action,
            parameters,
            llm_response,
        )
    if method == "ai.explain":
        allowed = {"workspaceRevision", "parameters", "llmResponseContent"}
        if set(payload) - allowed or "workspaceRevision" not in payload:
            raise BrowserRequestValidationError("Payload does not match method schema")
        parameters = payload.get("parameters", {})
        if not isinstance(parameters, dict):
            raise BrowserRequestValidationError("parameters must be an object")
        llm_response = payload.get("llmResponseContent")
        if llm_response is not None and not isinstance(llm_response, str):
            raise BrowserRequestValidationError("llmResponseContent must be a string or null")
        return _compiler.ai_explain(
            _integer(payload["workspaceRevision"]),
            parameters,
            llm_response,
        )
    raise AssertionError(f"Unsupported validated browser compiler method: {method}")


def _serialize_result(result: _DispatchResult) -> dict[str, Any]:
    if isinstance(result, BrowserWorkspaceResult):
        return {
            "workspace_revision": result.workspace_revision,
            "diagnostics": [asdict(diagnostic) for diagnostic in result.diagnostics],
            "source_hashes": dict(result.source_hashes),
        }
    if isinstance(result, BrowserAiPendingResult):
        return {
            "status": "pending_llm",
            "llm_request": asdict(result.llm_request),
        }
    return asdict(result)


def dispatch_browser_request(method: str, payload_json: str) -> str:
    if method not in _METHODS:
        return _error_response("INVALID_REQUEST")
    try:
        payload = json.loads(payload_json)
        if not isinstance(payload, dict):
            raise BrowserRequestValidationError("Payload must be an object")
        result = _dispatch(method, payload)
    except json.JSONDecodeError:
        return _error_response("INVALID_REQUEST")
    except BrowserRequestValidationError:
        return _error_response("INVALID_REQUEST")
    except BrowserLanguageError as error:
        return _error_response(error.code)

    return json.dumps(
        {"ok": True, "result": _serialize_result(result)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _reset_compiler_for_tests() -> None:
    """Reset module state for deterministic in-process tests."""
    global _compiler
    _compiler = BrowserCompiler()
