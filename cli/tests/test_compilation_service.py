from __future__ import annotations

import os
import stat
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

import modelable.operations.compilation as compilation
from modelable.operations.compilation import (
    CompilationError,
    CompilationPolicy,
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


def snapshot_tree(root: Path) -> dict[Path, bytes]:
    return {path.relative_to(root): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


def staging_dirs(root: Path) -> set[Path]:
    return set(root.glob("modelable-compile-*"))


def preview_for(
    tmp_path: Path,
    source: Path,
    target: str = "json-schema",
    **kwargs: object,
):
    return CompilationService(
        temp_root=tmp_path.parent,
        new_id=lambda: "compile-1",
    ).preview(
        CompilationRequest(
            source=source,
            target=target,
            out_dir=Path("generated") / target,
            **kwargs,
        ),
        policy=CompilationPolicy.conversation(),
    )


def test_preview_stages_exact_files_without_mutating_workspace(tmp_path: Path) -> None:
    source = write_workspace(tmp_path)
    before = snapshot_tree(tmp_path)

    pending = preview_for(tmp_path, source)

    assert snapshot_tree(tmp_path) == before
    assert {file.status for file in pending.files} >= {"created"}
    assert all(file.staged_path.is_relative_to(pending.staging_dir) for file in pending.files)
    assert all(file.staged_path.read_bytes() for file in pending.files)
    assert pending.affected_definitions
    assert pending.action_id == "compile-1"


def test_preview_models_are_immutable(tmp_path: Path) -> None:
    pending = preview_for(tmp_path, write_workspace(tmp_path))

    with pytest.raises(FrozenInstanceError):
        pending.action_id = "different"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        pending.files[0].status = "changed"  # type: ignore[misc]


def test_preview_classifies_changed_and_unchanged_text_with_complete_diffs(tmp_path: Path) -> None:
    source = write_workspace(tmp_path)
    first = preview_for(tmp_path, source)
    text_files = [file for file in first.files if file.after_text is not None]
    changed_seed = text_files[0]
    unchanged_seed = text_files[1]
    changed_seed.destination.parent.mkdir(parents=True, exist_ok=True)
    changed_seed.destination.write_bytes("old \N{GREEK SMALL LETTER ALPHA}\nlast line\n".encode())
    unchanged_seed.destination.parent.mkdir(parents=True, exist_ok=True)
    unchanged_seed.destination.write_bytes(unchanged_seed.staged_path.read_bytes())
    CompilationService().discard(first)

    pending = preview_for(tmp_path, source)
    changed = next(file for file in pending.files if file.destination == changed_seed.destination)
    unchanged = next(file for file in pending.files if file.destination == unchanged_seed.destination)

    assert changed.status == "changed"
    assert changed.before_text == "old \N{GREEK SMALL LETTER ALPHA}\nlast line\n"
    assert changed.after_text is not None
    assert changed.diff_text is not None
    assert "-old \N{GREEK SMALL LETTER ALPHA}\n" in changed.diff_text
    assert "-last line\n" in changed.diff_text
    assert all(f"+{line}" in changed.diff_text for line in changed.after_text.splitlines())
    assert unchanged.status == "unchanged"
    assert unchanged.before_text is None
    assert unchanged.after_text is None
    assert unchanged.diff_text is None


def test_preview_classifies_registry_as_binary_and_reports_new_registry_ids(tmp_path: Path) -> None:
    pending = preview_for(tmp_path, write_workspace(tmp_path))

    registry = next(file for file in pending.files if file.category == "registry")
    assert registry.media_type == "application/octet-stream"
    assert registry.before_text is None
    assert registry.after_text is None
    assert registry.diff_text is None
    assert pending.registry_id_changes == (compilation.RegistryIdChange("platform.SchemaId", 1),)


def test_preview_classifies_descriptor_as_binary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = write_workspace(tmp_path)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_protoc(bin_dir)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))

    pending = preview_for(tmp_path, source, "protobuf", descriptor_set=True)

    descriptor = next(file for file in pending.files if file.category == "descriptor")
    assert descriptor.media_type == "application/octet-stream"
    assert descriptor.after_text is None
    assert descriptor.after_size == len(descriptor.staged_path.read_bytes())


def test_preview_manifest_order_and_affected_definitions_are_canonical(tmp_path: Path) -> None:
    pending = preview_for(tmp_path, write_workspace(tmp_path))

    assert pending.files == tuple(sorted(pending.files, key=lambda item: item.destination.as_posix()))
    assert "platform.Order@1" in {file.ref for file in pending.files if file.category == "artifact"}
    assert "platform.OrderView@1" in {file.ref for file in pending.files if file.category == "plan"}
    assert pending.affected_definitions == tuple(sorted(pending.affected_definitions, key=lambda item: item.ref))
    assert pending.registry_id_changes == tuple(sorted(pending.registry_id_changes, key=lambda item: item.ref))
    assert len(pending.manifest_fingerprint) == 64


def test_preview_rejects_text_payload_above_two_mib(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = write_workspace(tmp_path)
    assert compilation._TEXT_PREVIEW_LIMIT == 2 * 1024 * 1024
    monkeypatch.setattr(compilation, "_TEXT_PREVIEW_LIMIT", 1)
    before = staging_dirs(tmp_path.parent)

    with pytest.raises(CompilationError, match=r"2 MiB.*modelable compile"):
        preview_for(tmp_path, source)

    assert staging_dirs(tmp_path.parent) == before


def test_preview_rejects_unknown_domains_without_leaving_staging(tmp_path: Path) -> None:
    before = staging_dirs(tmp_path.parent)

    with pytest.raises(CompilationError, match="Unknown --domain"):
        preview_for(tmp_path, write_workspace(tmp_path), domains=("missing",))

    assert staging_dirs(tmp_path.parent) == before


@pytest.mark.parametrize(
    ("out_dir", "message"),
    [
        (Path("../escape"), "outside the workspace"),
        (Path(".git/generated"), ".git"),
        (Path(".modelable/audit/generated"), ".modelable/audit"),
    ],
)
def test_preview_rejects_prohibited_output_paths(
    tmp_path: Path,
    out_dir: Path,
    message: str,
) -> None:
    source = write_workspace(tmp_path)

    with pytest.raises(CompilationError, match=message):
        CompilationService(temp_root=tmp_path.parent).preview(
            CompilationRequest(source=source, target="json-schema", out_dir=out_dir),
            policy=CompilationPolicy.conversation(),
        )


def test_preview_rejects_output_that_overlaps_mdl_source(tmp_path: Path) -> None:
    source = write_workspace(tmp_path)

    with pytest.raises(CompilationError, match=r"\.mdl source"):
        CompilationService(temp_root=tmp_path.parent).preview(
            CompilationRequest(source=source, target="json-schema", out_dir=Path(source.name)),
            policy=CompilationPolicy.conversation(),
        )


@pytest.mark.parametrize(
    ("out_dir", "message"),
    [
        (Path("workspace.mdl/generated"), "overlap"),
        (Path("registry-ids.lock"), "overlap"),
        (Path(".modelable/registry.db/generated"), "internal .modelable"),
    ],
)
def test_preview_rejects_source_and_control_path_overlaps(
    tmp_path: Path,
    out_dir: Path,
    message: str,
) -> None:
    source = write_workspace(tmp_path)

    with pytest.raises(CompilationError, match=message):
        CompilationService(temp_root=tmp_path.parent).preview(
            CompilationRequest(source=source, target="json-schema", out_dir=out_dir),
            policy=CompilationPolicy.conversation(),
        )


def test_preview_rejects_staging_root_inside_workspace(tmp_path: Path) -> None:
    source = write_workspace(tmp_path)
    before = snapshot_tree(tmp_path)

    with pytest.raises(CompilationError, match=r"staging.*outside"):
        CompilationService(temp_root=tmp_path).preview(
            CompilationRequest(source=source, target="json-schema"),
            policy=CompilationPolicy.conversation(),
        )

    assert snapshot_tree(tmp_path) == before


def test_preview_rejects_symlink_that_escapes_workspace(tmp_path: Path) -> None:
    source = write_workspace(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    link = tmp_path / "linked-output"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable")

    with pytest.raises(CompilationError, match="outside the workspace"):
        CompilationService(temp_root=tmp_path.parent).preview(
            CompilationRequest(source=source, target="json-schema", out_dir=Path("linked-output")),
            policy=CompilationPolicy.conversation(),
        )


def test_preview_rejects_oci_and_invalid_descriptor_target_before_staging(tmp_path: Path) -> None:
    source = write_workspace(tmp_path)
    service = CompilationService(temp_root=tmp_path.parent)
    before = staging_dirs(tmp_path.parent)

    with pytest.raises(CompilationError, match="OCI"):
        service.preview(
            CompilationRequest(source=source, target="json-schema", registry_path="oci://example/repo"),
            policy=CompilationPolicy.conversation(),
        )
    with pytest.raises(CompilationError, match=r"descriptor sets.*protobuf.*grpc"):
        service.preview(
            CompilationRequest(source=source, target="json-schema", descriptor_set=True),
            policy=CompilationPolicy.conversation(),
        )

    assert staging_dirs(tmp_path.parent) == before


def test_discard_is_idempotent_and_surfaces_incomplete_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = CompilationService(temp_root=tmp_path.parent)
    pending = service.preview(
        CompilationRequest(source=write_workspace(tmp_path), target="json-schema"),
        policy=CompilationPolicy.conversation(),
    )
    service.discard(pending)
    service.discard(pending)
    pending = service.preview(
        CompilationRequest(source=tmp_path / "workspace.mdl", target="json-schema"),
        policy=CompilationPolicy.conversation(),
    )
    monkeypatch.setattr(compilation.shutil, "rmtree", lambda path: None)

    with pytest.raises(CompilationError, match="cleanup"):
        service.discard(pending)


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
