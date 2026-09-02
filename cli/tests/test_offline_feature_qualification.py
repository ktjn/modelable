from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from click.testing import CliRunner
from test_golden_artifacts import _assert_artifact_structurally_valid

from modelable.cli import cli
from modelable.emitters.base import EmittedArtifact
from modelable.emitters.targets import list_implemented_codegen_targets

RUST_FIXTURE = Path(__file__).parent / "fixtures" / "offline-rust-consumer"
FAST_GENERATION_BUDGET_SECONDS = 30
LANGUAGE_MATRIX_BUDGET_SECONDS = 120

PRODUCER_V1 = """
domain customer {
  owner: "customer-platform"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    displayName: string
  }
}
"""

PRODUCER_V2 = """
domain customer {
  owner: "customer-platform"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    displayName: string
  }
  entity Customer @ 2 (additive) {
    @key customerId: uuid
    displayName: string
    nickname?: string
  }
}
"""

PRODUCER_V2_BREAKING = """
domain customer {
  owner: "customer-platform"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    displayName: string
  }
  entity Customer @ 2 (breaking) {
    @key customerId: uuid
  }
}
"""

TARGET_V1 = """
domain customer {
  owner: "customer-platform"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    displayName: string
  }
  index Customer @ 1 {
    primary customerId
  }
}
"""

TARGET_V1_COMPATIBLE = """
domain customer {
  owner: "customer-platform"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    displayName: string
    nickname?: string
  }
  index Customer @ 1 {
    primary customerId
  }
}
"""

TARGET_V1_BREAKING = """
domain customer {
  owner: "customer-platform"
}
"""

CONSUMER = """
domain analytics {
  owner: "analytics-platform"
  projection CustomerSummary @ 1
    from customer.Customer @ 1 as c
  {
    customerId <- c.customerId
    name <- c.displayName
  }
}
"""

CONSUMER_V2 = """
domain analytics {
  owner: "analytics-platform"
  projection CustomerSummary @ 1
    from customer.Customer @ 2 as c
  {
    customerId <- c.customerId
    name <- c.displayName
  }
}
"""


def test_offline_feature_fixture_compiles_consumer_for_every_implemented_target(tmp_path: Path) -> None:
    producer_v1 = tmp_path / "producer-v1.mdl"
    producer_v1.write_text(PRODUCER_V1.strip() + "\n", encoding="utf-8")
    producer_v2 = tmp_path / "producer-v2.mdl"
    producer_v2.write_text(PRODUCER_V2.strip() + "\n", encoding="utf-8")
    consumer = tmp_path / "consumer.mdl"
    consumer.write_text(CONSUMER.strip() + "\n", encoding="utf-8")
    snapshot = tmp_path / ".modelable"
    runner = CliRunner()

    resolved = runner.invoke(cli, ["registry", "resolve", str(producer_v1), "--out", str(snapshot)])
    assert resolved.exit_code == 0, resolved.output

    diff = runner.invoke(
        cli,
        ["registry", "diff", str(producer_v2), "--out", str(snapshot), "--format", "json"],
    )
    assert diff.exit_code == 0, diff.output
    assert "customer.Customer@2 (model)" in json.loads(diff.output)["added"]

    for target in list_implemented_codegen_targets():
        output = tmp_path / "generated" / target.name
        compiled = runner.invoke(
            cli,
            [
                "compile",
                str(consumer),
                "--target",
                target.name,
                "--snapshot",
                str(snapshot),
                "--registry",
                str(tmp_path / ".registry.db"),
                "--out",
                str(output),
            ],
        )
        assert compiled.exit_code == 0, f"{target.name}: {compiled.output}"
        _assert_artifact_manifest(output, target.name)


def test_offline_feature_fixture_language_smoke_matrix(tmp_path: Path) -> None:
    compiler_commands = {
        "typescript": "tsc.cmd" if sys.platform == "win32" else "tsc",
        "java": "javac",
        "go": "go",
        "csharp": "dotnet",
        "rust": "cargo",
    }
    missing = [name for name, command in compiler_commands.items() if shutil.which(command) is None]
    if missing:
        pytest.skip(f"language compiler(s) unavailable: {', '.join(missing)}")

    producer = tmp_path / "producer.mdl"
    producer.write_text(PRODUCER_V1.strip() + "\n", encoding="utf-8")
    consumer = tmp_path / "consumer.mdl"
    consumer.write_text(CONSUMER.strip() + "\n", encoding="utf-8")
    snapshot = tmp_path / ".modelable"
    runner = CliRunner()

    resolved = runner.invoke(cli, ["registry", "resolve", str(producer), "--out", str(snapshot)])
    assert resolved.exit_code == 0, resolved.output

    outputs: dict[str, Path] = {}
    for target in ("python", "typescript", "java", "go", "csharp", "rust"):
        output = tmp_path / "generated" / target
        compiled = runner.invoke(
            cli,
            [
                "compile",
                str(consumer),
                "--target",
                target,
                "--snapshot",
                str(snapshot),
                "--registry",
                str(tmp_path / ".registry.db"),
                "--out",
                str(output),
            ],
        )
        assert compiled.exit_code == 0, f"{target}: {compiled.output}"
        _assert_artifact_manifest(output, target)
        outputs[target] = output

    _write_python_language_smoke(tmp_path)
    _run_language_command([sys.executable, "smoke.py"], tmp_path, "python")

    _write_typescript_language_smoke(tmp_path)
    _run_language_command([compiler_commands["typescript"], "--noEmit", "--strict", "smoke.ts"], tmp_path, "typescript")

    _write_java_language_smoke(tmp_path)
    java_files = [str(path) for root in (outputs["java"], tmp_path / "analytics") for path in root.rglob("*.java")]
    _run_language_command(["javac", "-d", "build", *java_files], tmp_path, "java compile")
    _run_language_command(["java", "-cp", "build", "analytics.Smoke"], tmp_path, "java runtime")

    _write_go_language_smoke(outputs["go"])
    _run_language_command(["go", "test", "./..."], outputs["go"], "go")

    _write_csharp_language_smoke(tmp_path)
    _run_language_command(["dotnet", "run", "--project", "Smoke.csproj"], tmp_path, "csharp")

    _write_rust_consumer(tmp_path)
    _run_language_command(["cargo", "test", "--quiet", "--locked", "--offline"], tmp_path, "rust")


def test_offline_feature_fixture_compatible_v2_regenerates_all_targets(tmp_path: Path) -> None:
    compiler_commands = {
        "typescript": "tsc.cmd" if sys.platform == "win32" else "tsc",
        "java": "javac",
        "go": "go",
        "csharp": "dotnet",
        "rust": "cargo",
    }
    missing = [name for name, command in compiler_commands.items() if shutil.which(command) is None]
    if missing:
        pytest.skip(f"language compiler(s) unavailable: {', '.join(missing)}")

    producer_v1 = tmp_path / "producer-v1.mdl"
    producer_v1.write_text(PRODUCER_V1.strip() + "\n", encoding="utf-8")
    producer_v2 = tmp_path / "producer-v2.mdl"
    producer_v2.write_text(PRODUCER_V2.strip() + "\n", encoding="utf-8")
    consumer_v1 = tmp_path / "consumer-v1.mdl"
    consumer_v1.write_text(CONSUMER.strip() + "\n", encoding="utf-8")
    consumer_v2 = tmp_path / "consumer-v2.mdl"
    consumer_v2.write_text(CONSUMER_V2.strip() + "\n", encoding="utf-8")
    snapshot = tmp_path / ".modelable"
    runner = CliRunner()

    lane_started = time.perf_counter()
    resolved = runner.invoke(cli, ["registry", "resolve", str(producer_v1), "--out", str(snapshot)])
    assert resolved.exit_code == 0, resolved.output
    baseline_outputs = _compile_feature_targets(runner, consumer_v1, snapshot, tmp_path / "baseline")
    baseline_manifest_hashes = {
        target: (output / "modelable-artifact-manifest.json").read_bytes()
        for target, output in baseline_outputs.items()
    }

    updated = runner.invoke(cli, ["registry", "update", str(producer_v2), "--out", str(snapshot), "--format", "json"])
    assert updated.exit_code == 0, updated.output
    updated_payload = json.loads(updated.output)
    assert "customer.Customer@2 (model)" in updated_payload["added"]

    candidate_outputs = _compile_feature_targets(runner, consumer_v2, snapshot, tmp_path / "generated")
    for target, output in candidate_outputs.items():
        _assert_artifact_manifest(output, target)
        assert (output / "modelable-artifact-manifest.json").read_bytes() != baseline_manifest_hashes[target]
    generation_seconds = time.perf_counter() - lane_started
    assert generation_seconds <= FAST_GENERATION_BUDGET_SECONDS, (
        f"fast PR generation lane exceeded {FAST_GENERATION_BUDGET_SECONDS}s: {generation_seconds:.2f}s"
    )

    _write_python_language_smoke(tmp_path, model_version=2)
    _write_typescript_language_smoke(tmp_path, model_version=2)
    _write_java_language_smoke(tmp_path, model_version=2)
    java_files = [
        str(path) for root in (candidate_outputs["java"], tmp_path / "analytics") for path in root.rglob("*.java")
    ]
    _write_go_language_smoke(candidate_outputs["go"], model_version=2)
    _write_csharp_language_smoke(tmp_path, model_version=2)
    _write_rust_consumer(tmp_path, model_version=2)
    matrix_started = time.perf_counter()
    _run_language_matrix(
        [
            ([sys.executable, "smoke.py"], tmp_path, "python v2"),
            ([compiler_commands["typescript"], "--noEmit", "--strict", "smoke.ts"], tmp_path, "typescript v2"),
            (["javac", "-d", "build-v2", *java_files], tmp_path, "java v2 compile"),
            (["go", "test", "./..."], candidate_outputs["go"], "go v2"),
            (["dotnet", "run", "--project", "Smoke.csproj"], tmp_path, "csharp v2"),
            (["cargo", "test", "--quiet", "--locked", "--offline"], tmp_path, "rust v2"),
        ]
    )
    _run_language_command(["java", "-cp", "build-v2", "analytics.Smoke"], tmp_path, "java v2 runtime")
    matrix_seconds = time.perf_counter() - matrix_started
    assert matrix_seconds <= LANGUAGE_MATRIX_BUDGET_SECONDS, (
        f"cached language smoke matrix exceeded {LANGUAGE_MATRIX_BUDGET_SECONDS}s: {matrix_seconds:.2f}s"
    )


def test_offline_feature_fixture_rust_consumer_runs_locked_offline(tmp_path: Path) -> None:
    producer = tmp_path / "producer.mdl"
    producer.write_text(PRODUCER_V1.strip() + "\n", encoding="utf-8")
    consumer = tmp_path / "consumer.mdl"
    consumer.write_text(CONSUMER.strip() + "\n", encoding="utf-8")
    snapshot = tmp_path / ".modelable"
    output = tmp_path / "generated" / "rust"
    runner = CliRunner()

    resolved = runner.invoke(cli, ["registry", "resolve", str(producer), "--out", str(snapshot)])
    assert resolved.exit_code == 0, resolved.output
    compiled = runner.invoke(
        cli,
        [
            "compile",
            str(consumer),
            "--target",
            "rust",
            "--snapshot",
            str(snapshot),
            "--out",
            str(output),
        ],
    )
    assert compiled.exit_code == 0, compiled.output

    _write_rust_consumer(tmp_path)
    result = subprocess.run(
        ["cargo", "test", "--quiet", "--locked", "--offline"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"cargo test failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"


def test_offline_feature_fixture_commands_use_snapshot_without_network(tmp_path: Path, monkeypatch) -> None:
    producer_v1 = tmp_path / "producer-v1.mdl"
    producer_v1.write_text(PRODUCER_V1.strip() + "\n", encoding="utf-8")
    producer_v2 = tmp_path / "producer-v2.mdl"
    producer_v2.write_text(PRODUCER_V2.strip() + "\n", encoding="utf-8")
    candidate_v2 = tmp_path / "candidate-v2.mdl"
    candidate_v2.write_text(
        PRODUCER_V2.replace(
            "  entity Customer @ 1 (additive) {\n    @key customerId: uuid\n    displayName: string\n  }\n",
            "",
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    consumer = tmp_path / "consumer.mdl"
    consumer.write_text(CONSUMER.strip() + "\n", encoding="utf-8")
    snapshot = tmp_path / ".modelable"
    runner = CliRunner()

    def forbidden_network_call(*_args, **_kwargs):
        raise AssertionError("offline feature qualification contacted the network")

    monkeypatch.setattr("urllib.request.urlopen", forbidden_network_call)
    resolved = runner.invoke(cli, ["registry", "resolve", str(producer_v1), "--out", str(snapshot)])
    assert resolved.exit_code == 0, resolved.output

    for arguments in (
        ["validate", str(producer_v1)],
        [
            "compile",
            str(consumer),
            "--target",
            "json-schema",
            "--snapshot",
            str(snapshot),
            "--out",
            str(tmp_path / "validated-artifacts"),
        ],
    ):
        result = runner.invoke(cli, arguments)
        assert result.exit_code == 0, f"{arguments}: {result.output}"

    diff = runner.invoke(
        cli,
        ["registry", "diff", str(producer_v2), "--out", str(snapshot), "--format", "json"],
    )
    assert diff.exit_code == 0, diff.output
    assert "customer.Customer@2 (model)" in json.loads(diff.output)["added"]

    impact = runner.invoke(
        cli,
        [
            "impact",
            "--from",
            "customer.Customer@1",
            "--to",
            "customer.Customer@2",
            "--path",
            str(candidate_v2),
            "--snapshot",
            str(snapshot),
            "--format",
            "json",
        ],
    )
    assert impact.exit_code == 0, impact.output
    assert json.loads(impact.output)["consequences"]

    rebuilt = runner.invoke(cli, ["registry", "rebuild-index", "--out", str(snapshot)])
    assert rebuilt.exit_code == 0, rebuilt.output
    assert (snapshot / "registry.db").exists()


def test_offline_feature_fixture_v2_transition_reports_compatibility_before_replacement(tmp_path: Path) -> None:
    producer_v1 = tmp_path / "producer-v1.mdl"
    producer_v1.write_text(PRODUCER_V1.strip() + "\n", encoding="utf-8")
    producer_v2 = tmp_path / "producer-v2.mdl"
    producer_v2.write_text(PRODUCER_V2.strip() + "\n", encoding="utf-8")
    candidate_v2 = tmp_path / "candidate-v2.mdl"
    candidate_v2.write_text(
        PRODUCER_V2.replace(
            "  entity Customer @ 1 (additive) {\n    @key customerId: uuid\n    displayName: string\n  }\n",
            "",
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    producer_v2_breaking = tmp_path / "producer-v2-breaking.mdl"
    producer_v2_breaking.write_text(PRODUCER_V2_BREAKING.strip() + "\n", encoding="utf-8")
    consumer = tmp_path / "consumer.mdl"
    consumer.write_text(CONSUMER.strip() + "\n", encoding="utf-8")
    target_v1 = tmp_path / "target-v1.mdl"
    target_v1.write_text(TARGET_V1.strip() + "\n", encoding="utf-8")
    target_v1_compatible = tmp_path / "target-v1-compatible.mdl"
    target_v1_compatible.write_text(TARGET_V1_COMPATIBLE.strip() + "\n", encoding="utf-8")
    target_v1_breaking = tmp_path / "target-v1-breaking.mdl"
    target_v1_breaking.write_text(TARGET_V1_BREAKING.strip() + "\n", encoding="utf-8")
    candidate_v2_breaking = tmp_path / "candidate-v2-breaking.mdl"
    candidate_v2_breaking.write_text(
        PRODUCER_V2_BREAKING.replace(
            "  entity Customer @ 1 (additive) {\n    @key customerId: uuid\n    displayName: string\n  }\n",
            "",
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    snapshot = tmp_path / ".modelable"
    runner = CliRunner()

    resolved = runner.invoke(cli, ["registry", "resolve", str(producer_v1), "--out", str(snapshot)])
    assert resolved.exit_code == 0, resolved.output
    original_lock = (snapshot / "registry.lock").read_bytes()

    compatible_impact = runner.invoke(
        cli,
        [
            "impact",
            "--from",
            "customer.Customer@1",
            "--to",
            "customer.Customer@2",
            "--path",
            str(candidate_v2),
            "--snapshot",
            str(snapshot),
            "--format",
            "json",
        ],
    )
    assert compatible_impact.exit_code == 0, compatible_impact.output
    compatible_payload = json.loads(compatible_impact.output)
    assert compatible_payload["status"] == "compatible"
    assert any(
        consequence["action"] == "recompile"
        and consequence["status"] == "compatible"
        and consequence["causal_path"] == ["customer.Customer@1", "customer.Customer@2"]
        for consequence in compatible_payload["consequences"]
    )

    compatible_update = runner.invoke(
        cli,
        ["registry", "update", str(producer_v2), "--out", str(snapshot), "--format", "json", "--dry-run"],
    )
    assert compatible_update.exit_code == 0, compatible_update.output
    compatible_update_payload = json.loads(compatible_update.output)
    assert "customer.Customer@2 (model)" in compatible_update_payload["added"]
    assert compatible_update_payload["policy"]["violations"] == []
    assert (snapshot / "registry.lock").read_bytes() == original_lock

    installed_compatible = runner.invoke(
        cli,
        ["registry", "update", str(producer_v2), "--out", str(snapshot), "--format", "json"],
    )
    assert installed_compatible.exit_code == 0, installed_compatible.output
    installed_payload = json.loads(installed_compatible.output)
    assert installed_payload["dry_run"] is False
    assert "customer.Customer@2 (model)" in installed_payload["added"]
    assert (snapshot / "registry.lock").read_bytes() != original_lock

    compatible_consumer = runner.invoke(
        cli,
        [
            "compile",
            str(consumer),
            "--target",
            "python",
            "--snapshot",
            str(snapshot),
            "--out",
            str(tmp_path / "compatible-consumer"),
        ],
    )
    assert compatible_consumer.exit_code == 0, compatible_consumer.output
    _assert_artifact_manifest(tmp_path / "compatible-consumer", "python")

    for target in ("protobuf", "grpc"):
        compatible_target = runner.invoke(
            cli,
            [
                "validate-compat",
                "--from",
                str(target_v1),
                "--to",
                str(target_v1_compatible),
                "--target",
                target,
                "--format",
                "json",
            ],
        )
        assert compatible_target.exit_code == 0, f"{target}: {compatible_target.output}"
        compatible_target_payload = json.loads(compatible_target.output)
        assert compatible_target_payload["status"] in {"wire_compatible", "read_compatible"}
        assert compatible_target_payload["findings"] == []

        breaking_target = runner.invoke(
            cli,
            [
                "validate-compat",
                "--from",
                str(target_v1),
                "--to",
                str(target_v1_breaking),
                "--target",
                target,
                "--format",
                "json",
            ],
        )
        assert breaking_target.exit_code == 1, f"{target}: {breaking_target.output}"
        breaking_target_payload = json.loads(breaking_target.output)
        assert breaking_target_payload["status"] == "breaking"
        assert breaking_target_payload["findings"]

    breaking_snapshot = tmp_path / ".modelable-breaking"
    resolved_breaking_baseline = runner.invoke(
        cli, ["registry", "resolve", str(producer_v1), "--out", str(breaking_snapshot)]
    )
    assert resolved_breaking_baseline.exit_code == 0, resolved_breaking_baseline.output
    breaking_lock = (breaking_snapshot / "registry.lock").read_bytes()
    (tmp_path / "modelable.toml").write_text('[registry]\nblocked_actions = ["breaking"]\n', encoding="utf-8")

    breaking_impact = runner.invoke(
        cli,
        [
            "impact",
            "--from",
            "customer.Customer@1",
            "--to",
            "customer.Customer@2",
            "--path",
            str(candidate_v2_breaking),
            "--snapshot",
            str(breaking_snapshot),
            "--format",
            "json",
        ],
    )
    assert breaking_impact.exit_code == 1, breaking_impact.output
    breaking_payload = json.loads(breaking_impact.output)
    assert breaking_payload["status"] == "breaking"
    assert any(
        consequence["action"] == "breaking"
        and consequence["status"] == "breaking"
        and consequence["causal_path"] == ["customer.Customer@1", "customer.Customer@2"]
        for consequence in breaking_payload["consequences"]
    )

    blocked_update = runner.invoke(
        cli,
        ["registry", "update", str(producer_v2_breaking), "--out", str(breaking_snapshot), "--format", "json"],
    )
    assert blocked_update.exit_code == 1, blocked_update.output
    blocked_payload = json.loads(blocked_update.output)
    assert blocked_payload["policy"]["violations"] == ["breaking"]
    assert blocked_payload["policy"]["findings"]
    assert (breaking_snapshot / "registry.lock").read_bytes() == breaking_lock


def _compile_feature_targets(runner: CliRunner, consumer: Path, snapshot: Path, output_root: Path) -> dict[str, Path]:
    outputs: dict[str, Path] = {}
    for target in list_implemented_codegen_targets():
        output = output_root / target.name
        compiled = runner.invoke(
            cli,
            [
                "compile",
                str(consumer),
                "--target",
                target.name,
                "--snapshot",
                str(snapshot),
                "--out",
                str(output),
            ],
        )
        assert compiled.exit_code == 0, f"{target.name}: {compiled.output}"
        _assert_artifact_manifest(output, target.name)
        outputs[target.name] = output
    return outputs


def _write_rust_consumer(tmp_path: Path, model_version: int = 1) -> None:
    shutil.copytree(RUST_FIXTURE, tmp_path, dirs_exist_ok=True)
    # Vendored sources are checksummed byte-for-byte by Cargo. On Windows,
    # core.autocrlf can still materialize a fixture copy with CRLF even when
    # the repository marks the vendor tree as binary. Normalize only the
    # temporary copy so locked offline tests behave like CI/Linux.
    for path in (tmp_path / "vendor").rglob("*"):
        if path.is_file():
            content = path.read_bytes()
            # Do not touch binary assets (the fixture includes Unicode
            # identifier automata); a CRLF byte pair can be valid binary data.
            if b"\x00" not in content and b"\r\n" in content:
                path.write_bytes(content.replace(b"\r\n", b"\n"))
    source = tmp_path / "src"
    source.mkdir()
    source_text = """
#[path = "../generated/rust/customer/customer_customer_v1.rs"]
mod customer;
#[path = "../generated/rust/analytics/analytics_customer_summary_v1.rs"]
mod analytics;

#[cfg(test)]
mod tests {
    use super::analytics::AnalyticsCustomerSummaryV1;
    use super::customer::CustomerCustomerV1;
    use uuid::Uuid;

    #[test]
    fn generated_contracts_compile_and_preserve_identity() {
        let id = Uuid::parse_str("123e4567-e89b-12d3-a456-426614174000").unwrap();
        let customer = CustomerCustomerV1 { customer_id: id, display_name: String::from("Alice") };
        let summary = AnalyticsCustomerSummaryV1 { customer_id: id, name: String::from("Alice") };

        assert_eq!(customer.customer_id, summary.customer_id);
        assert_eq!(CustomerCustomerV1::SCHEMA_VERSION, 1);
        assert_eq!(AnalyticsCustomerSummaryV1::SCHEMA_VERSION, 1);
        assert_eq!(CustomerCustomerV1::SCHEMA_CONTENT_SIGNATURE.len(), 32);
        assert_eq!(AnalyticsCustomerSummaryV1::SCHEMA_CONTENT_SIGNATURE.len(), 32);
    }
}
""".strip()
    source_text = source_text.replace("customer_customer_v1.rs", f"customer_customer_v{model_version}.rs").replace(
        "CustomerCustomerV1", f"CustomerCustomerV{model_version}"
    )
    source_text = source_text.replace(
        f"CustomerCustomerV{model_version}::SCHEMA_VERSION, 1",
        f"CustomerCustomerV{model_version}::SCHEMA_VERSION, {model_version}",
    )
    if model_version == 2:
        source_text = source_text.replace(
            'CustomerCustomerV2 { customer_id: id, display_name: String::from("Alice") }',
            'CustomerCustomerV2 { customer_id: id, display_name: String::from("Alice"), nickname: None }',
        )
    (source / "lib.rs").write_text(source_text + "\n", encoding="utf-8")


def _assert_artifact_manifest(output: Path, target: str) -> None:
    manifest_path = output / "modelable-artifact-manifest.json"
    assert manifest_path.is_file(), f"{target} did not write an artifact manifest"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["format"] == "modelable.artifact-manifest.v1"
    assert manifest["target"]["name"] == target
    artifacts = manifest["artifacts"]
    assert artifacts, f"{target} emitted no artifacts"

    for entry in artifacts:
        relative_path = Path(entry["path"])
        assert not relative_path.is_absolute()
        artifact_path = output / relative_path
        assert artifact_path.resolve().is_relative_to(output.resolve())
        assert artifact_path.is_file(), f"{target} manifest references missing artifact {entry['path']}"
        content = artifact_path.read_bytes()
        assert content, f"{target} emitted empty artifact {entry['path']}"
        assert entry["ref"]
        assert hashlib.sha256(content).hexdigest() == entry["sha256"]
        try:
            rendered = content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise AssertionError(f"{target} emitted non-UTF-8 artifact {entry['path']}") from error
        artifact = EmittedArtifact(
            target=target,
            ref=entry["ref"],
            artifact_id=entry["ref"],
            path=relative_path,
            content=rendered,
            content_hash=entry["sha256"],
        )
        _assert_artifact_structurally_valid(target, artifact, rendered)


def _run_language_command(command: list[str], cwd: Path, label: str) -> None:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    assert result.returncode == 0, f"{label} smoke failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"


def _run_language_matrix(commands: list[tuple[list[str], Path, str]]) -> None:
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=len(commands)) as executor:
        futures = [executor.submit(_run_language_command, command, cwd, label) for command, cwd, label in commands]
        for future in futures:
            future.result()


def test_language_matrix_runs_commands_in_parallel(monkeypatch, tmp_path: Path) -> None:
    barrier = threading.Barrier(2)

    def fake_run(_command: list[str], _cwd: Path, _label: str) -> None:
        barrier.wait(timeout=1)

    monkeypatch.setattr(sys.modules[__name__], "_run_language_command", fake_run)
    _run_language_matrix(
        [
            (["first"], tmp_path, "first"),
            (["second"], tmp_path, "second"),
        ]
    )


def _write_python_language_smoke(tmp_path: Path, model_version: int = 1) -> None:
    smoke = """
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from uuid import UUID


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


customer = load_module(
    Path("generated/python/customer/customer_customer_v1.py"), "customer_customer_v1"
)
analytics = load_module(
    Path("generated/python/analytics/analytics_customer_summary_v1.py"),
    "analytics_customer_summary_v1",
)
customer_obj = customer.CustomerCustomerV1(customerId=UUID("123e4567-e89b-12d3-a456-426614174000"), displayName="Alice")
summary_obj = analytics.AnalyticsCustomerSummaryV1(customerId=customer_obj.customerId, name=customer_obj.displayName)
assert summary_obj.name == "Alice"
assert "customerId" in customer.CustomerCustomerV1.__dataclass_fields__
""".strip()
    smoke = smoke.replace("customer_customer_v1", f"customer_customer_v{model_version}")
    smoke = smoke.replace("CustomerCustomerV1", f"CustomerCustomerV{model_version}")
    (tmp_path / "smoke.py").write_text(smoke + "\n", encoding="utf-8")


def _write_typescript_language_smoke(tmp_path: Path, model_version: int = 1) -> None:
    smoke = """
import type { CustomerCustomerV1 } from "./generated/typescript/customer.Customer.v1";
import type { AnalyticsCustomerSummaryV1 } from "./generated/typescript/analytics.CustomerSummary.v1";

const customer: CustomerCustomerV1 = {
  customerId: "123e4567-e89b-12d3-a456-426614174000",
  displayName: "Alice",
};
const summary: AnalyticsCustomerSummaryV1 = {
  customerId: customer.customerId,
  name: customer.displayName,
};
if (summary.name !== "Alice") throw new Error("generated identity fields did not type-check");
""".strip()
    smoke = smoke.replace("customer.Customer.v1", f"customer.Customer.v{model_version}")
    smoke = smoke.replace("CustomerCustomerV1", f"CustomerCustomerV{model_version}")
    (tmp_path / "smoke.ts").write_text(smoke + "\n", encoding="utf-8")


def _write_java_language_smoke(tmp_path: Path, model_version: int = 1) -> None:
    smoke_dir = tmp_path / "analytics"
    smoke_dir.mkdir(parents=True, exist_ok=True)
    smoke = """
package analytics;

import customer.CustomerV1;
import java.util.UUID;

public final class Smoke {
  public static void main(String[] args) {
    var id = UUID.fromString("123e4567-e89b-12d3-a456-426614174000");
    var customer = new CustomerV1(id, "Alice");
    var summary = new CustomerSummaryV1(id, "Alice");
    if (!customer.customerId().equals(summary.customerId()) || !customer.displayName().equals(summary.name())) {
      throw new IllegalStateException("generated identity fields did not survive Java compilation");
    }
  }
}
""".strip()
    smoke = smoke.replace("CustomerV1", f"CustomerV{model_version}")
    if model_version == 2:
        smoke = smoke.replace("import java.util.UUID;", "import java.util.UUID;\nimport java.util.Optional;")
        smoke = smoke.replace('new CustomerV2(id, "Alice")', 'new CustomerV2(id, "Alice", Optional.empty())')
    (smoke_dir / "Smoke.java").write_text(smoke + "\n", encoding="utf-8")


def _write_go_language_smoke(output: Path, model_version: int = 1) -> None:
    (output / "go.mod").write_text("module example.com/modelable-offline-feature\n\ngo 1.26\n", encoding="utf-8")
    customer_dir = output / "customer"
    customer_dir.mkdir(parents=True, exist_ok=True)
    smoke = """
package customer

import (
  "testing"
  "example.com/modelable-offline-feature/analytics"
)

func TestGeneratedIdentity(t *testing.T) {
  customer := CustomerCustomerV1{CustomerId: "123e4567-e89b-12d3-a456-426614174000", DisplayName: "Alice"}
  summary := analytics.AnalyticsCustomerSummaryV1{CustomerId: customer.CustomerId, Name: customer.DisplayName}
  if summary.CustomerId != customer.CustomerId || summary.Name != "Alice" { t.Fatal("generated identity fields did not survive Go compilation") }
}
""".strip()
    smoke = smoke.replace("CustomerCustomerV1", f"CustomerCustomerV{model_version}")
    (customer_dir / "smoke_test.go").write_text(smoke + "\n", encoding="utf-8")


def _write_csharp_language_smoke(tmp_path: Path, model_version: int = 1) -> None:
    (tmp_path / "Smoke.csproj").write_text(
        """
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <OutputType>Exe</OutputType>
    <TargetFramework>net10.0</TargetFramework>
    <ImplicitUsings>enable</ImplicitUsings>
    <Nullable>enable</Nullable>
    <EnableDefaultCompileItems>false</EnableDefaultCompileItems>
  </PropertyGroup>
  <ItemGroup>
    <Compile Include="Program.cs" />
    <Compile Include="generated/csharp/**/*.cs" />
  </ItemGroup>
</Project>
""".strip()
        + "\n",
        encoding="utf-8",
    )
    smoke = """
using System;
using Modelable.Customer;
using Modelable.Analytics;

var id = Guid.Parse("123e4567-e89b-12d3-a456-426614174000");
var customer = new CustomerCustomerV1 { CustomerId = id, DisplayName = "Alice" };
var summary = new AnalyticsCustomerSummaryV1 { CustomerId = customer.CustomerId, Name = customer.DisplayName };
if (summary.CustomerId != customer.CustomerId || summary.Name != "Alice")
    throw new InvalidOperationException("generated identity fields did not survive C# compilation");
""".strip()
    smoke = smoke.replace("CustomerCustomerV1", f"CustomerCustomerV{model_version}")
    (tmp_path / "Program.cs").write_text(smoke + "\n", encoding="utf-8")
