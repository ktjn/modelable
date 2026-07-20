from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

from modelable.operations.compilation import (
    CompilationError,
    CompilationRequest,
    CompilationService,
)

FIXTURES = Path(__file__).parent / "fixtures"


def write_workspace(tmp_path: Path, text: str | None = None) -> Path:
    source = tmp_path / "workspace.mdl"
    source.write_text(
        text
        or """
domain platform {
  owner: "platform-team"

  semantic SchemaId : u32 { registry: true }

  entity Order @ 1 (additive) {
    @key orderId: uuid
    schemaId: SchemaId
  }

  projection OrderView @ 1
    from platform.Order @ 1 as order
  {
    orderId <- order.orderId
  }
}
""",
        encoding="utf-8",
    )
    return source


def request_for(tmp_path: Path, source: Path, target: str, **kwargs: object) -> CompilationRequest:
    return CompilationRequest(
        source=source,
        target=target,
        out_dir=tmp_path / "generated" / target,
        registry_path=str(tmp_path / ".modelable" / "registry.db"),
        registry_ids_path=tmp_path / "registry-ids.lock",
        **kwargs,
    )


def test_execute_direct_writes_registry_plans_and_rust_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    source = write_workspace(tmp_path)
    request = CompilationRequest(
        source=source,
        target="rust",
        out_dir=tmp_path / "generated",
        registry_path=str(tmp_path / ".modelable" / "registry.db"),
        registry_ids_path=tmp_path / "registry-ids.lock",
    )

    result = CompilationService().execute_direct(request)

    assert result.written_paths == tuple(sorted(result.written_paths))
    assert tmp_path / "registry-ids.lock" in result.written_paths
    assert tmp_path / ".modelable" / "registry.db" in result.written_paths
    assert any(path.is_relative_to(tmp_path / ".modelable" / "plans") for path in result.written_paths)
    assert any(path.suffix == ".rs" for path in result.written_paths)


def test_execute_direct_scopes_target_artifacts_to_requested_domains(tmp_path: Path) -> None:
    source = write_workspace(
        tmp_path,
        """
domain logs {
  owner: "test-team"
  entity LogEntry @ 1 (additive) {
    @key logId: uuid
  }
}

domain nlq {
  owner: "test-team"
  entity Query @ 1 (additive) {
    @key queryId: uuid
  }
}
""",
    )

    result = CompilationService().execute_direct(request_for(tmp_path, source, "rust", domains=("logs",)))

    rust_paths = [path for path in result.written_paths if path.suffix == ".rs"]
    assert rust_paths
    assert all("logs" in path.parts for path in rust_paths)
    assert not any("nlq" in path.parts for path in rust_paths)


@pytest.mark.parametrize(
    ("target", "fixture", "pattern"),
    [
        ("json-schema", "multi_language_target.mdl", "*.json"),
        ("markdown", "multi_language_target.mdl", "*.md"),
        ("typescript", "multi_language_target.mdl", "*.ts"),
        ("csharp", "multi_language_target.mdl", "*.cs"),
        ("java", "multi_language_target.mdl", "*.java"),
        ("python", "multi_language_target.mdl", "*.py"),
        ("rust", "multi_language_target.mdl", "*.rs"),
        ("go", "multi_language_target.mdl", "*.go"),
        ("dbt-yaml", "sql_and_dbt_targets.mdl", "*.yml"),
        ("fhir-profile", "fhir_patient_profile.mdl", "*.json"),
        ("openmetadata", "governance_export_model.mdl", "*.json"),
        ("openlineage", "governance_export_model.mdl", "*.json"),
        ("odcs", "governance_export_model.mdl", "*.yaml"),
        ("protobuf", "multi_language_target.mdl", "*.proto"),
        ("grpc", "multi_language_target.mdl", "*.proto"),
        ("sql-postgres", "sql_and_dbt_targets.mdl", "*.sql"),
        ("sql-clickhouse", "sql_and_dbt_targets.mdl", "*.sql"),
    ],
)
def test_execute_direct_supports_every_implemented_target(
    tmp_path: Path,
    target: str,
    fixture: str,
    pattern: str,
) -> None:
    result = CompilationService().execute_direct(request_for(tmp_path, FIXTURES / fixture, target))

    assert any(path.match(pattern) for path in result.written_paths), target


def _write_fake_protoc(path: Path) -> None:
    source = path / "fake_protoc.py"
    source.write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "out = next(arg.split('=', 1)[1] for arg in sys.argv[1:] if arg.startswith('--descriptor_set_out='))\n"
        "Path(out).write_bytes(b'descriptor')\n",
        encoding="utf-8",
    )
    if sys.platform == "win32":
        (path / "protoc.cmd").write_text(f'@"{sys.executable}" "{source}" %*\n', encoding="utf-8")
    else:
        wrapper = path / "protoc"
        wrapper.write_text(f'#!/usr/bin/env sh\n"{sys.executable}" "{source}" "$@"\n', encoding="utf-8")
        wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)


@pytest.mark.parametrize(
    ("target", "descriptor_suffix"),
    [("protobuf", ".descriptor.pb"), ("grpc", ".grpc.descriptor.pb")],
)
def test_execute_direct_writes_descriptors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
    descriptor_suffix: str,
) -> None:
    source = write_workspace(tmp_path)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_protoc(bin_dir)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))

    result = CompilationService().execute_direct(request_for(tmp_path, source, target, descriptor_set=True))

    assert any(str(path).endswith(descriptor_suffix) for path in result.written_paths)


def test_execute_direct_returns_emitter_warnings_as_events(tmp_path: Path) -> None:
    source = write_workspace(
        tmp_path,
        """
domain platform {
  owner: "platform-team"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    opaquePayload: bytes
  }
}
""",
    )

    result = CompilationService().execute_direct(request_for(tmp_path, source, "typescript"))

    assert any(event.level == "warning" and "EMIT003" in event.message for event in result.events)


def test_execute_direct_reports_empty_target_output(tmp_path: Path) -> None:
    source = write_workspace(
        tmp_path,
        """
domain platform {
  owner: "platform-team"
}
""",
    )

    result = CompilationService().execute_direct(request_for(tmp_path, source, "rust"))

    assert any(event.level == "warning" and event.message == "No artifacts generated." for event in result.events)


def test_execute_direct_rejects_orphaned_registry_ledger_entry(tmp_path: Path) -> None:
    source = write_workspace(tmp_path)
    ledger = tmp_path / "registry-ids.lock"
    ledger.write_text('{"platform.RemovedId": 1, "platform.SchemaId": 2}\n', encoding="utf-8")

    with pytest.raises(CompilationError, match=r"platform\.RemovedId"):
        CompilationService().execute_direct(request_for(tmp_path, source, "rust"))


def test_execute_direct_preserves_unsupported_oci_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = write_workspace(tmp_path)
    monkeypatch.chdir(tmp_path)
    request = CompilationRequest(
        source=source,
        target="markdown",
        out_dir=tmp_path / "generated",
        registry_path="oci://registry.example/modelable",
        registry_ids_path=tmp_path / "registry-ids.lock",
    )

    with pytest.raises(CompilationError, match="OCI registry support is not implemented"):
        CompilationService().execute_direct(request)
