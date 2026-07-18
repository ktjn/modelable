from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from modelable.browser.api import BrowserCompiler, BrowserInputError
from modelable.browser.dto import (
    BrowserCompileResult,
    BrowserFormatResult,
    BrowserSource,
    BrowserWorkspaceResult,
)

_METHODS = {
    "workspace.open",
    "source.format",
    "compile.jsonSchema",
}
_SOURCE_FIELDS = {"uri", "text", "version"}


def _invalid_request(message: str) -> str:
    return json.dumps(
        {
            "ok": False,
            "error": {
                "code": "INVALID_REQUEST",
                "message": message,
            },
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _require_exact_fields(value: dict[str, Any], fields: set[str]) -> None:
    if set(value) != fields:
        raise ValueError("Payload does not match method schema")


def _source(value: Any) -> BrowserSource:
    if not isinstance(value, dict):
        raise TypeError("Source must be an object")
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
        raise TypeError("Source fields have invalid types")
    return BrowserSource(uri=uri, text=text, version=version)


def _sources(value: Any) -> tuple[BrowserSource, ...]:
    if not isinstance(value, list):
        raise TypeError("Sources must be an array")
    return tuple(_source(source) for source in value)


def _dispatch(
    method: str,
    payload: dict[str, Any],
) -> BrowserWorkspaceResult | BrowserFormatResult | BrowserCompileResult:
    compiler = BrowserCompiler()
    if method == "workspace.open":
        _require_exact_fields(payload, {"sources"})
        return compiler.open_workspace(_sources(payload["sources"]))
    if method == "source.format":
        _require_exact_fields(payload, {"source"})
        return compiler.format_source(_source(payload["source"]))
    if method == "compile.jsonSchema":
        _require_exact_fields(payload, {"sources"})
        return compiler.compile_json_schema(_sources(payload["sources"]))
    raise ValueError(f"Unsupported browser compiler method: {method}")


def _serialize_result(
    result: BrowserWorkspaceResult | BrowserFormatResult | BrowserCompileResult,
) -> dict[str, Any]:
    if isinstance(result, BrowserWorkspaceResult):
        return {
            "diagnostics": [asdict(diagnostic) for diagnostic in result.diagnostics],
            "source_hashes": dict(result.source_hashes),
        }
    return asdict(result)


def dispatch_browser_request(method: str, payload_json: str) -> str:
    if method not in _METHODS:
        return _invalid_request(f"Unsupported browser compiler method: {method}")
    try:
        payload = json.loads(payload_json)
        if not isinstance(payload, dict):
            raise TypeError("Payload must be an object")
        result = _dispatch(method, payload)
    except json.JSONDecodeError:
        return _invalid_request("Payload must be valid JSON")
    except BrowserInputError:
        return _invalid_request("Invalid browser compiler input")
    except KeyError, TypeError, ValueError:
        return _invalid_request("Payload does not match method schema")

    return json.dumps(
        {"ok": True, "result": _serialize_result(result)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
