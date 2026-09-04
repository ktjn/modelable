from __future__ import annotations

import hashlib
import json
from pathlib import Path

import wasmtime
from click.testing import CliRunner

from modelable.cli import cli
from modelable.extensions import ExtensionDescriptor, pin_extension_descriptor

_WAT = Path(__file__).parent / "fixtures" / "wasm-extension" / "reference.wat"
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


def _write_inputs(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    wat = _WAT.read_text(encoding="utf-8")
    response_start = wat.index('(data (i32.const 16) "') + len('(data (i32.const 16) "')
    response_end = wat.index('")', response_start)
    response = bytes(wat[response_start:response_end], "utf-8").decode("unicode_escape")
    module = tmp_path / "reference.wasm"
    module.write_bytes(wasmtime.wat2wasm(wat.replace("RESULT_LEN", str(len(response.encode("utf-8"))))))

    descriptor = ExtensionDescriptor(
        protocol="modelable.extension/v1",
        id="example.reference",
        version="1.0.0",
        accepted_plan_versions=("modelable.plan/v1",),
        capabilities=(),
        configuration_schema=None,
        output_kinds=("artifact",),
        compatibility_support=False,
    )
    pin = pin_extension_descriptor(descriptor, hashlib.sha256(module.read_bytes()).hexdigest())
    descriptor_path = tmp_path / "descriptor.json"
    descriptor_path.write_text(json.dumps(descriptor.as_dict()), encoding="utf-8")
    pin_path = tmp_path / "pin.json"
    pin_path.write_text(json.dumps(pin.as_dict()), encoding="utf-8")
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(_PLAN), encoding="utf-8")
    return module, descriptor_path, pin_path, plan_path


def test_extension_run_requires_explicit_trust_and_returns_result(tmp_path: Path) -> None:
    module, descriptor, pin, plan = _write_inputs(tmp_path)
    virtual_input = tmp_path / "input.txt"
    virtual_input.write_text("declared input", encoding="utf-8")
    runner = CliRunner()

    refused = runner.invoke(
        cli,
        ["extension", "run", str(module), "--descriptor", str(descriptor), "--pin", str(pin), "--plan", str(plan)],
    )
    assert refused.exit_code != 0
    assert "explicitly trusted" in refused.output

    accepted = runner.invoke(
        cli,
        [
            "extension",
            "run",
            str(module),
            "--descriptor",
            str(descriptor),
            "--pin",
            str(pin),
            "--plan",
            str(plan),
            "--trust",
            "--virtual-file",
            f"inputs/input.txt={virtual_input}",
        ],
    )
    assert accepted.exit_code == 0, accepted.output
    assert json.loads(accepted.output)["status"] == "ok"
