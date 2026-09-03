from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import wasmtime
from jsonschema import Draft202012Validator

from modelable.extension_host import (
    ExtensionHostError,
    WasmExtensionHost,
    WasmExtensionLimits,
    serialize_extension_result,
    validate_extension_request,
    validate_extension_result,
)
from modelable.extensions import ExtensionDescriptor, ExtensionTrustPolicy, pin_extension_descriptor

_FIXTURE = Path(__file__).parent / "fixtures" / "wasm-extension" / "reference.wat"
_PLAN = {
    "$schema": "modelable.plan/v1",
    "domain": "customer",
    "projection": "CustomerView",
    "version": 1,
    "auto_generated": False,
    "requires_revalidation": False,
    "revalidation_reasons": [],
    "governance_findings": [],
    "source": {
        "model": "customer.Customer",
        "version": {"kind": "exact", "version": 1},
        "resolved_version": None,
        "alias": "c",
        "change_kind": "additive",
        "resolved": None,
    },
    "joins": [],
    "where": None,
    "group_by": [],
    "fields": [],
    "planner_metadata": {"modelable_schema": "1.0"},
}


def _descriptor() -> ExtensionDescriptor:
    return ExtensionDescriptor(
        protocol="modelable.extension/v1",
        id="example.reference",
        version="1.0.0",
        accepted_plan_versions=("modelable.plan/v1",),
        capabilities=(),
        configuration_schema=None,
        output_kinds=("artifact",),
        compatibility_support=False,
    )


def _module(tmp_path: Path, *, source: str = _FIXTURE.read_text(encoding="utf-8")) -> Path:
    response_start = source.index('(data (i32.const 16) "') + len('(data (i32.const 16) "')
    response_end = source.index('")', response_start)
    escaped = source[response_start:response_end]
    response = bytes(escaped, "utf-8").decode("unicode_escape")
    source = source.replace("RESULT_LEN", str(len(response.encode("utf-8"))))
    module_path = tmp_path / "reference.wasm"
    module_path.write_bytes(wasmtime.wat2wasm(source))
    return module_path


def _compile_wat(tmp_path: Path, source: str) -> Path:
    module_path = tmp_path / "module.wasm"
    module_path.write_bytes(wasmtime.wat2wasm(source))
    return module_path


def _trusted_host(tmp_path: Path) -> tuple[WasmExtensionHost, ExtensionDescriptor, object, Path]:
    module_path = _module(tmp_path)
    pin = pin_extension_descriptor(_descriptor(), hashlib.sha256(module_path.read_bytes()).hexdigest())
    policy = ExtensionTrustPolicy(allowed_wasm_pins=(pin,))
    return WasmExtensionHost(policy=policy), _descriptor(), pin, module_path


def test_reference_wasm_extension_consumes_plan_and_returns_deterministic_artifact(tmp_path: Path) -> None:
    host, descriptor, pin, module_path = _trusted_host(tmp_path)

    result = host.execute(module_path, descriptor=descriptor, pin=pin, plan=_PLAN, configuration={})

    assert result["status"] == "ok"
    assert result["artifacts"] == [
        {
            "path": "reference.txt",
            "media_type": "text/plain",
            "content": "reference extension",
        }
    ]
    assert validate_extension_result(result) == result


def test_wasm_host_passes_sorted_virtual_files_without_ambient_filesystem(tmp_path: Path) -> None:
    host, descriptor, pin, module_path = _trusted_host(tmp_path)

    result = host.execute(
        module_path,
        descriptor=descriptor,
        pin=pin,
        plan=_PLAN,
        configuration={},
        virtual_files={"z/input.txt": "z", "a/input.txt": "a"},
    )

    assert result["status"] == "ok"
    with pytest.raises(ExtensionHostError, match="relative"):
        host.execute(
            module_path,
            descriptor=descriptor,
            pin=pin,
            plan=_PLAN,
            configuration={},
            virtual_files={"../escape": "forbidden"},
        )


def test_wasm_host_requires_explicit_trust_and_exact_hash(tmp_path: Path) -> None:
    module_path = _module(tmp_path)
    descriptor = _descriptor()
    pin = pin_extension_descriptor(descriptor, hashlib.sha256(module_path.read_bytes()).hexdigest())
    host = WasmExtensionHost()

    with pytest.raises(ExtensionHostError, match="explicitly trusted"):
        host.execute(module_path, descriptor=descriptor, pin=pin, plan=_PLAN, configuration={})

    wrong_hash_pin = pin_extension_descriptor(descriptor, "a" * 64)
    trusted_host = WasmExtensionHost(policy=ExtensionTrustPolicy(allowed_wasm_pins=(wrong_hash_pin,)))
    with pytest.raises(ExtensionHostError, match="hash does not match"):
        trusted_host.execute(module_path, descriptor=descriptor, pin=wrong_hash_pin, plan=_PLAN, configuration={})


def test_wasm_host_rejects_imports_and_excessive_output(tmp_path: Path) -> None:
    imported = _compile_wat(tmp_path, '(module (import "host" "forbidden" (func)))')
    descriptor = _descriptor()
    pin = pin_extension_descriptor(descriptor, hashlib.sha256(imported.read_bytes()).hexdigest())
    host = WasmExtensionHost(policy=ExtensionTrustPolicy(allowed_wasm_pins=(pin,)))

    with pytest.raises(ExtensionHostError, match="imports"):
        host.execute(imported, descriptor=descriptor, pin=pin, plan=_PLAN, configuration={})

    reference = _module(tmp_path)
    reference_pin = pin_extension_descriptor(descriptor, hashlib.sha256(reference.read_bytes()).hexdigest())
    output_host = WasmExtensionHost(policy=ExtensionTrustPolicy(allowed_wasm_pins=(reference_pin,)))
    with pytest.raises(ExtensionHostError, match="output limit"):
        output_host.execute(
            reference,
            descriptor=descriptor,
            pin=reference_pin,
            plan=_PLAN,
            configuration={},
            limits=WasmExtensionLimits(max_output_bytes=1),
        )


def test_extension_host_protocol_schema_and_structured_result_validation() -> None:
    schema_path = Path(__file__).parents[1] / "src" / "modelable" / "data" / "modelable.extension-host.v1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    request = {
        "$schema": "modelable.extension-host/v1",
        "kind": "extension_request",
        "extension": {"id": "example.reference", "version": "1.0.0", "implementation_hash": "a" * 64},
        "plan": _PLAN,
        "configuration": {},
    }
    validator.validate(request)
    validate_extension_request(request)
    failed = {
        "$schema": "modelable.extension-host/v1",
        "kind": "extension_result",
        "status": "failed",
        "artifacts": [],
        "diagnostics": [{"severity": "error", "code": "E1", "message": "failed"}],
        "compatibility_findings": [],
        "error": {"code": "EXECUTION_FAILED", "message": "failed"},
    }
    validator.validate(failed)
    validate_extension_result(failed)
    assert serialize_extension_result(failed).endswith("\n")
    with pytest.raises(ExtensionHostError, match="diagnostic"):
        validate_extension_result(
            {
                "$schema": "modelable.extension-host/v1",
                "kind": "extension_result",
                "status": "ok",
                "artifacts": [],
                "diagnostics": [{"severity": "error", "code": "E1"}],
                "compatibility_findings": [],
            }
        )


def test_wasm_host_enforces_fuel_and_memory_limits(tmp_path: Path) -> None:
    infinite = _compile_wat(
        tmp_path,
        """
(module
  (memory (export "memory") 1)
  (func (export "alloc") (param i32) (result i32) i32.const 0)
  (func (export "run") (param i32 i32) (result i32) (loop $forever br $forever) i32.const 0)
  (global (export "result_len") i32 (i32.const 0)))
""",
    )
    descriptor = _descriptor()
    pin = pin_extension_descriptor(descriptor, hashlib.sha256(infinite.read_bytes()).hexdigest())
    host = WasmExtensionHost(policy=ExtensionTrustPolicy(allowed_wasm_pins=(pin,)))
    with pytest.raises(ExtensionHostError, match="execution failed"):
        host.execute(
            infinite,
            descriptor=descriptor,
            pin=pin,
            plan=_PLAN,
            configuration={},
            limits=WasmExtensionLimits(fuel=100),
        )

    oversized = _compile_wat(
        tmp_path,
        """
(module
  (memory (export "memory") 2)
  (func (export "alloc") (param i32) (result i32) i32.const 0)
  (func (export "run") (param i32 i32) (result i32) i32.const 0)
  (global (export "result_len") i32 (i32.const 0)))
""",
    )
    oversized_pin = pin_extension_descriptor(descriptor, hashlib.sha256(oversized.read_bytes()).hexdigest())
    oversized_host = WasmExtensionHost(policy=ExtensionTrustPolicy(allowed_wasm_pins=(oversized_pin,)))
    with pytest.raises(ExtensionHostError, match="memory limit"):
        oversized_host.execute(
            oversized,
            descriptor=descriptor,
            pin=oversized_pin,
            plan=_PLAN,
            configuration={},
            limits=WasmExtensionLimits(max_memory_pages=1),
        )
