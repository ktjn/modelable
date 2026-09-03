"""Least-capability native host for ``modelable.extension-host/v1`` modules."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, cast

import wasmtime

from modelable.extensions import (
    ExtensionDescriptor,
    ExtensionDescriptorError,
    ExtensionPin,
    ExtensionTrustPolicy,
    authorize_extension,
    validate_extension_plan_version,
)
from modelable.planner.protocol import PLAN_V1_SCHEMA, validate_plan

EXTENSION_HOST_SCHEMA = "modelable.extension-host/v1"
_MAX_CURSOR_JSON_BYTES = 16 * 1024


class ExtensionHostError(ValueError):
    """Raised when an extension cannot be admitted or returns an invalid result."""


@dataclass(frozen=True)
class WasmExtensionLimits:
    """Deterministic resource limits for one extension invocation."""

    fuel: int = 1_000_000
    max_memory_pages: int = 256
    max_output_bytes: int = 2 * 1024 * 1024

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0
            for value in (self.fuel, self.max_memory_pages, self.max_output_bytes)
        ):
            raise ExtensionHostError("WASM resource limits must be positive integers")


class WasmExtensionHost:
    """Execute a pinned, no-import WASM extension through a JSON memory ABI.

    Modules export ``memory``, ``alloc(i32) -> i32``, ``run(i32, i32) -> i32``,
    and mutable global ``result_len``. The host writes one request JSON value,
    invokes ``run``, and reads exactly ``result_len`` bytes from its returned
    pointer. No WASM imports are admitted, so filesystem/network/process access
    is unavailable through this ABI.
    """

    def __init__(self, *, policy: ExtensionTrustPolicy | None = None) -> None:
        self.policy = policy or ExtensionTrustPolicy()

    def execute(
        self,
        module_path: Path,
        *,
        descriptor: ExtensionDescriptor,
        pin: ExtensionPin,
        plan: object,
        configuration: Mapping[str, Any],
        virtual_files: Mapping[str, str] | None = None,
        limits: WasmExtensionLimits | None = None,
    ) -> dict[str, Any]:
        limits = limits or WasmExtensionLimits()
        try:
            validated_plan = validate_plan(plan)
        except ValueError as error:
            raise ExtensionHostError(f"extension plan is invalid: {error}") from error
        if validated_plan["$schema"] != PLAN_V1_SCHEMA:
            raise ExtensionHostError("WASM extensions require modelable.plan/v1 input")
        if not isinstance(configuration, Mapping):
            raise ExtensionHostError("extension configuration must be an object")
        files = _normalize_virtual_files(virtual_files or {})
        try:
            configuration_json = json.dumps(
                dict(configuration), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
            )
        except (TypeError, ValueError) as error:
            raise ExtensionHostError(f"extension configuration is not deterministic JSON: {error}") from error

        try:
            module_bytes = module_path.read_bytes()
        except OSError as error:
            raise ExtensionHostError(f"could not read WASM module: {error}") from error
        actual_hash = hashlib.sha256(module_bytes).hexdigest()
        if actual_hash != pin.implementation_hash:
            raise ExtensionHostError("WASM implementation hash does not match provenance pin")
        try:
            authorize_extension(
                descriptor,
                execution_kind="wasm",
                pin=pin,
                policy=self.policy,
            )
            validate_extension_plan_version(descriptor, PLAN_V1_SCHEMA)
        except ExtensionDescriptorError as error:
            raise ExtensionHostError(str(error)) from error

        request = {
            "$schema": EXTENSION_HOST_SCHEMA,
            "kind": "extension_request",
            "extension": {
                "id": descriptor.id,
                "version": descriptor.version,
                "implementation_hash": pin.implementation_hash,
            },
            "plan": validated_plan,
            "configuration": json.loads(configuration_json),
        }
        if files:
            request["virtual_files"] = [{"path": path, "content": content} for path, content in files.items()]
        validate_extension_request(request)
        request_bytes = json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        try:
            config = wasmtime.Config()
            config.consume_fuel = True
            engine = wasmtime.Engine(config)
            module = wasmtime.Module(engine, module_bytes)
        except Exception as error:
            raise ExtensionHostError(f"invalid WASM module: {error}") from error
        if module.imports:
            raise ExtensionHostError("WASM module imports are not allowed by the extension host")

        store = wasmtime.Store(engine)
        store.set_fuel(limits.fuel)
        store.set_limits(
            memory_size=limits.max_memory_pages * 64 * 1024,
            instances=1,
            memories=1,
            tables=1,
            table_elements=10_000,
        )
        try:
            instance = wasmtime.Instance(store, module, [])
            exports = instance.exports(store)
            memory = _export(exports, "memory")
            alloc = _export(exports, "alloc")
            run = _export(exports, "run")
            result_len_global = _export(exports, "result_len")
            if not isinstance(memory, wasmtime.Memory):
                raise ExtensionHostError("WASM module must export memory")
            if not isinstance(alloc, wasmtime.Func) or not isinstance(run, wasmtime.Func):
                raise ExtensionHostError("WASM module must export alloc and run functions")
            if not isinstance(result_len_global, wasmtime.Global):
                raise ExtensionHostError("WASM module must export result_len global")
            if memory.size(store) > limits.max_memory_pages:
                raise ExtensionHostError("WASM module exceeds memory limit")
            request_ptr = alloc(store, len(request_bytes))
            if not isinstance(request_ptr, int) or request_ptr < 0:
                raise ExtensionHostError("WASM alloc returned an invalid pointer")
            memory.write(store, request_bytes, request_ptr)
            result_ptr = run(store, request_ptr, len(request_bytes))
            if not isinstance(result_ptr, int) or result_ptr < 0:
                raise ExtensionHostError("WASM run returned an invalid pointer")
            if memory.size(store) > limits.max_memory_pages:
                raise ExtensionHostError("WASM module exceeded memory limit")
            result_len = result_len_global.value(store)
            if not isinstance(result_len, int) or result_len < 0:
                raise ExtensionHostError("WASM result_len is invalid")
            if result_len > limits.max_output_bytes:
                raise ExtensionHostError("WASM output limit exceeded")
            result_bytes = bytes(memory.read(store, result_ptr, result_ptr + result_len))
        except ExtensionHostError:
            raise
        except Exception as error:
            raise ExtensionHostError(f"WASM execution failed: {error}") from error
        try:
            result = json.loads(
                result_bytes.decode("utf-8"),
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_non_finite,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ExtensionHostError) as error:
            raise ExtensionHostError(f"WASM result is not valid UTF-8 JSON: {error}") from error
        return validate_extension_result(result)


def validate_extension_result(document: object) -> dict[str, Any]:
    """Validate one structured extension-host result envelope."""
    if not isinstance(document, dict):
        raise ExtensionHostError("extension result must be an object")
    required = {"$schema", "kind", "status", "artifacts", "diagnostics", "compatibility_findings"}
    optional = {"error"}
    unknown = sorted(set(document) - required - optional)
    missing = sorted(required - set(document))
    if unknown:
        raise ExtensionHostError(f"extension result has unknown key(s): {', '.join(unknown)}")
    if missing:
        raise ExtensionHostError(f"extension result is missing key(s): {', '.join(missing)}")
    if document["$schema"] != EXTENSION_HOST_SCHEMA or document["kind"] != "extension_result":
        raise ExtensionHostError("extension result has an invalid protocol envelope")
    if document["status"] not in {"ok", "failed"}:
        raise ExtensionHostError("extension result status must be 'ok' or 'failed'")
    artifacts = document["artifacts"]
    if not isinstance(artifacts, list):
        raise ExtensionHostError("extension result artifacts must be an array")
    seen_paths: set[str] = set()
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise ExtensionHostError("extension result artifact must be an object")
        if set(artifact) != {"path", "media_type", "content"}:
            raise ExtensionHostError("extension result artifact has invalid fields")
        path = artifact["path"]
        if not isinstance(path, str) or not _safe_relative_path(path) or path in seen_paths:
            raise ExtensionHostError("extension result artifact path must be unique and relative")
        seen_paths.add(path)
        if not isinstance(artifact["media_type"], str) or not artifact["media_type"]:
            raise ExtensionHostError("extension result artifact media_type must be non-empty")
        _ensure_json_value(artifact["content"], "extension result artifact content")
    for name in ("diagnostics", "compatibility_findings"):
        values = document[name]
        if not isinstance(values, list):
            raise ExtensionHostError(f"extension result {name} must be an array")
        for value in values:
            if name == "diagnostics":
                _validate_diagnostic(value)
            elif not isinstance(value, dict):
                raise ExtensionHostError("extension result compatibility finding must be an object")
    if document["status"] == "failed":
        error = document.get("error")
        if not isinstance(error, dict) or set(error) != {"code", "message"}:
            raise ExtensionHostError("failed extension result requires structured error code and message")
        if not all(isinstance(error[key], str) and error[key] for key in ("code", "message")):
            raise ExtensionHostError("extension result error code and message must be non-empty")
    elif "error" in document:
        raise ExtensionHostError("successful extension result must not contain error")
    return cast(dict[str, Any], document)


def validate_extension_request(document: object) -> dict[str, Any]:
    """Validate one language-neutral extension-host request envelope."""
    if not isinstance(document, dict):
        raise ExtensionHostError("extension request must be an object")
    required = {"$schema", "kind", "extension", "plan", "configuration"}
    optional = {"virtual_files"}
    if set(document) - required - optional or required - set(document):
        raise ExtensionHostError("extension request has invalid fields")
    if document["$schema"] != EXTENSION_HOST_SCHEMA or document["kind"] != "extension_request":
        raise ExtensionHostError("extension request has an invalid protocol envelope")
    extension = document["extension"]
    if not isinstance(extension, dict) or set(extension) != {"id", "version", "implementation_hash"}:
        raise ExtensionHostError("extension request extension identity is invalid")
    if not all(isinstance(extension[key], str) and extension[key] for key in extension):
        raise ExtensionHostError("extension request extension identity must be non-empty strings")
    plan = validate_plan(document["plan"])
    if plan["$schema"] != PLAN_V1_SCHEMA:
        raise ExtensionHostError("extension request requires modelable.plan/v1")
    configuration = document["configuration"]
    if not isinstance(configuration, dict):
        raise ExtensionHostError("extension request configuration must be an object")
    _ensure_json_value(configuration, "extension request configuration")
    if "virtual_files" in document:
        virtual_files = document["virtual_files"]
        if not isinstance(virtual_files, list):
            raise ExtensionHostError("extension request virtual_files must be an array")
        paths: set[str] = set()
        for entry in virtual_files:
            if not isinstance(entry, dict) or set(entry) != {"path", "content"}:
                raise ExtensionHostError("extension request virtual file has invalid fields")
            path = entry["path"]
            if not isinstance(path, str) or not _safe_relative_path(path) or path in paths:
                raise ExtensionHostError("extension request virtual file path must be unique and relative")
            if not isinstance(entry["content"], str):
                raise ExtensionHostError("extension request virtual file content must be a string")
            paths.add(path)
    return cast(dict[str, Any], document)


def serialize_extension_result(document: object) -> str:
    """Serialize one validated result deterministically."""
    return (
        json.dumps(validate_extension_result(document), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    )


def _export(exports: Any, name: str) -> Any:
    try:
        return exports[name]
    except KeyError as error:
        raise ExtensionHostError(f"WASM module must export {name}") from error


def _safe_relative_path(value: str) -> bool:
    if not value or "\\" in value or value.startswith("/"):
        return False
    path = PurePosixPath(value)
    return path != PurePosixPath(".") and ".." not in path.parts


def _normalize_virtual_files(files: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(files, Mapping):
        raise ExtensionHostError("virtual_files must be an object")
    normalized: dict[str, str] = {}
    for path, content in files.items():
        if not isinstance(path, str) or not _safe_relative_path(path):
            raise ExtensionHostError("virtual file paths must be relative POSIX paths")
        if not isinstance(content, str):
            raise ExtensionHostError("virtual file content must be a string")
        if path in normalized:
            raise ExtensionHostError(f"duplicate virtual file path {path!r}")
        normalized[path] = content
    return dict(sorted(normalized.items()))


def _ensure_json_value(value: object, name: str) -> None:
    try:
        json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ExtensionHostError(f"{name} is not JSON-compatible") from error


def _validate_diagnostic(value: object) -> None:
    if not isinstance(value, dict) or set(value) != {"severity", "code", "message"}:
        raise ExtensionHostError("extension result diagnostic has invalid fields")
    if value["severity"] not in {"info", "warning", "error"}:
        raise ExtensionHostError("extension result diagnostic severity is invalid")
    if not all(isinstance(value[key], str) and value[key] for key in ("code", "message")):
        raise ExtensionHostError("extension result diagnostic code and message must be non-empty")


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ExtensionHostError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _reject_non_finite(value: str) -> object:
    raise ExtensionHostError(f"non-finite JSON number {value!r} is not allowed")
