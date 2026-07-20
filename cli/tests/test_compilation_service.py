from __future__ import annotations

import dataclasses
import json
import os
import stat
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

import modelable.operations.compilation as compilation
from modelable.compiler.workspace import load_workspace
from modelable.lsp.definition import definition_location_for_ref
from modelable.operations.compilation import (
    CompilationConfirmation,
    CompilationError,
    CompilationPolicy,
    CompilationRequest,
    CompilationService,
    StaleCompilationError,
)
from modelable.operations.file_transaction import (
    FileTransaction,
    FileTransactionCommittedError,
    FileTransactionError,
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


def confirmation_for(pending) -> CompilationConfirmation:
    return CompilationConfirmation(
        session_id="session-1",
        action_id=pending.action_id,
        manifest_fingerprint=pending.manifest_fingerprint,
        surface="cli-chat",
        provider="ollama",
        model="qwen",
    )


def test_apply_writes_exact_stage_and_private_audit(tmp_path: Path) -> None:
    source = write_workspace(tmp_path)
    service = CompilationService(
        temp_root=tmp_path.parent,
        new_id=lambda: "compile-1",
        clock=lambda: "2026-07-20T10:00:00Z",
    )
    pending = service.preview(
        CompilationRequest(
            source=source,
            target="rust",
            out_dir=Path("generated/rust"),
        ),
        policy=CompilationPolicy.conversation(),
    )
    staged = {item.destination: item.staged_path.read_bytes() for item in pending.files}
    assert pending.audit_path == (tmp_path / ".modelable" / "audit" / "compilations" / "compile-1.json").resolve()

    applied = service.apply(pending, confirmation=confirmation_for(pending))

    assert {path: path.read_bytes() for path in staged} == staged
    assert applied.written_paths == tuple(sorted((*staged, applied.audit_path)))
    assert applied.action_id == pending.action_id
    assert applied.audit_path == pending.audit_path
    assert applied.files == pending.files
    assert applied.affected_definitions == pending.affected_definitions
    audit = json.loads(applied.audit_path.read_text(encoding="utf-8"))
    assert audit["manifestFingerprint"] == pending.manifest_fingerprint
    assert audit["schemaVersion"] == 1
    assert "prompt" not in json.dumps(audit).lower()
    assert not pending.staging_dir.exists()


@pytest.mark.parametrize("category", ["registry_ids", "registry", "artifact"])
def test_apply_rejects_stale_destination_inputs(
    tmp_path: Path,
    category: str,
) -> None:
    service = CompilationService(temp_root=tmp_path.parent)
    pending = service.preview(
        CompilationRequest(
            source=write_workspace(tmp_path),
            target="rust",
            out_dir=Path("generated/rust"),
        ),
        policy=CompilationPolicy.conversation(),
    )
    destination = next(item.destination for item in pending.files if item.category == category)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(b"concurrent change")

    with pytest.raises(StaleCompilationError, match=category.replace("_", " ")):
        service.apply(pending, confirmation=confirmation_for(pending))

    assert destination.read_bytes() == b"concurrent change"
    assert not pending.staging_dir.exists()


def test_apply_rejects_stale_source(tmp_path: Path) -> None:
    source = write_workspace(tmp_path)
    service = CompilationService(temp_root=tmp_path.parent)
    pending = service.preview(
        CompilationRequest(source=source, target="rust"),
        policy=CompilationPolicy.conversation(),
    )
    source.write_text(source.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(StaleCompilationError, match="source"):
        service.apply(pending, confirmation=confirmation_for(pending))

    assert not pending.staging_dir.exists()
    assert not (tmp_path / ".modelable" / "locks").exists()


def test_apply_rejects_changed_resolved_parent_even_with_same_bytes(
    tmp_path: Path,
) -> None:
    source = write_workspace(tmp_path)
    service = CompilationService(temp_root=tmp_path.parent)
    initial = service.preview(
        CompilationRequest(
            source=source,
            target="rust",
            out_dir=Path("generated/rust"),
        ),
        policy=CompilationPolicy.conversation(),
    )
    initial_artifact = next(item for item in initial.files if item.category == "artifact")
    initial_artifact.destination.parent.mkdir(parents=True)
    initial_artifact.destination.write_bytes(initial_artifact.staged_path.read_bytes())
    service.discard(initial)
    pending = service.preview(
        CompilationRequest(
            source=source,
            target="rust",
            out_dir=Path("generated/rust"),
        ),
        policy=CompilationPolicy.conversation(),
    )
    file = next(item for item in pending.files if item.category == "artifact")
    outside = tmp_path.parent / f"{tmp_path.name}-redirect"
    outside.mkdir()
    redirected = outside / file.destination.name
    redirected.write_bytes(file.destination.read_bytes())
    original_parent = file.destination.parent
    moved_parent = original_parent.with_name(f"{original_parent.name}-original")
    original_parent.rename(moved_parent)
    try:
        original_parent.symlink_to(outside, target_is_directory=True)
    except OSError:
        moved_parent.rename(original_parent)
        pytest.skip("directory symlinks are unavailable")

    with pytest.raises(StaleCompilationError, match="resolved parent"):
        service.apply(pending, confirmation=confirmation_for(pending))

    assert not pending.staging_dir.exists()


def test_apply_rejects_stage_and_manifest_tampering(tmp_path: Path) -> None:
    service = CompilationService(temp_root=tmp_path.parent)
    pending = service.preview(
        CompilationRequest(source=write_workspace(tmp_path), target="rust"),
        policy=CompilationPolicy.conversation(),
    )
    pending.files[0].staged_path.write_bytes(b"tampered")

    with pytest.raises(StaleCompilationError, match="staged"):
        service.apply(pending, confirmation=confirmation_for(pending))

    pending = service.preview(
        CompilationRequest(source=tmp_path / "workspace.mdl", target="rust"),
        policy=CompilationPolicy.conversation(),
    )
    tampered = dataclasses.replace(pending, warnings=(*pending.warnings, "tampered"))
    with pytest.raises(StaleCompilationError, match="manifest"):
        service.apply(tampered, confirmation=confirmation_for(tampered))
    assert not pending.staging_dir.exists()

    pending = service.preview(
        CompilationRequest(source=tmp_path / "workspace.mdl", target="rust"),
        policy=CompilationPolicy.conversation(),
    )
    duplicate_stage = pending.staging_dir / "duplicate-stage"
    duplicate_stage.write_bytes(pending.files[0].staged_path.read_bytes())
    relocated_file = dataclasses.replace(
        pending.files[0],
        staged_path=duplicate_stage,
    )
    tampered = dataclasses.replace(
        pending,
        files=(relocated_file, *pending.files[1:]),
    )
    with pytest.raises(StaleCompilationError, match="manifest"):
        service.apply(tampered, confirmation=confirmation_for(tampered))
    assert not pending.staging_dir.exists()

    pending = service.preview(
        CompilationRequest(source=tmp_path / "workspace.mdl", target="rust"),
        policy=CompilationPolicy.conversation(),
    )
    tampered = dataclasses.replace(
        pending,
        preview_timestamp="2099-01-01T00:00:00Z",
    )
    with pytest.raises(StaleCompilationError, match="manifest"):
        service.apply(tampered, confirmation=confirmation_for(tampered))
    assert not pending.staging_dir.exists()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("action_id", "foreign-action", "action"),
        ("manifest_fingerprint", "0" * 64, "manifest"),
    ],
)
def test_apply_requires_exact_confirmation_binding(
    tmp_path: Path,
    field: str,
    value: str,
    message: str,
) -> None:
    service = CompilationService(temp_root=tmp_path.parent)
    pending = service.preview(
        CompilationRequest(source=write_workspace(tmp_path), target="rust"),
        policy=CompilationPolicy.conversation(),
    )
    confirmation = dataclasses.replace(confirmation_for(pending), **{field: value})

    with pytest.raises(StaleCompilationError, match=message):
        service.apply(pending, confirmation=confirmation)

    assert not pending.staging_dir.exists()


def test_apply_promotes_stage_without_recompiling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = CompilationService(temp_root=tmp_path.parent)
    pending = service.preview(
        CompilationRequest(source=write_workspace(tmp_path), target="rust"),
        policy=CompilationPolicy.conversation(),
    )

    def unexpected_compile(*args, **kwargs):
        raise AssertionError("apply recompiled")

    monkeypatch.setattr(compilation, "_run_compilation", unexpected_compile)

    service.apply(pending, confirmation=confirmation_for(pending))


def test_audit_promotion_failure_rolls_back_compilation_files(
    tmp_path: Path,
) -> None:
    source = write_workspace(tmp_path)
    before = snapshot_tree(tmp_path)

    class AuditFailingTransaction(FileTransaction):
        def promote(self, files, *, validate=None):
            audit_destination = files[-1].destination

            def fail_audit(source_path, destination_path):
                if Path(destination_path) == audit_destination:
                    raise OSError("audit write failed")
                os.replace(source_path, destination_path)

            self._replace = fail_audit
            return super().promote(files, validate=validate)

    service = CompilationService(
        temp_root=tmp_path.parent,
        transaction_factory=lambda root: AuditFailingTransaction(workspace_root=root),
    )
    pending = service.preview(
        CompilationRequest(source=source, target="rust"),
        policy=CompilationPolicy.conversation(),
    )

    with pytest.raises(FileTransactionError, match="audit write failed"):
        service.apply(pending, confirmation=confirmation_for(pending))

    assert snapshot_tree(tmp_path) == before
    assert not pending.staging_dir.exists()


def test_waiting_apply_rechecks_freshness_under_workspace_lock(
    tmp_path: Path,
) -> None:
    source = write_workspace(tmp_path)
    identifiers = iter(("first-action", "second-action"))
    first_replace_started = threading.Event()
    release_first_replace = threading.Event()
    blocked_once = False

    def synchronized_replace(source_path, destination_path):
        nonlocal blocked_once
        if ".modelable-tmp-" in Path(source_path).name and not blocked_once:
            blocked_once = True
            first_replace_started.set()
            assert release_first_replace.wait(timeout=10)
        os.replace(source_path, destination_path)

    service = CompilationService(
        temp_root=tmp_path.parent,
        new_id=lambda: next(identifiers),
        transaction_factory=lambda root: FileTransaction(
            workspace_root=root,
            replace=synchronized_replace,
            lock_timeout=10,
        ),
    )
    first = service.preview(
        CompilationRequest(source=source, target="rust"),
        policy=CompilationPolicy.conversation(),
    )
    second = service.preview(
        CompilationRequest(source=source, target="rust"),
        policy=CompilationPolicy.conversation(),
    )
    first_staged = {item.destination: item.staged_path.read_bytes() for item in first.files}

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(
            service.apply,
            first,
            confirmation=confirmation_for(first),
        )
        assert first_replace_started.wait(timeout=10)
        second_future = executor.submit(
            service.apply,
            second,
            confirmation=confirmation_for(second),
        )
        release_first_replace.set()
        applied = first_future.result(timeout=20)
        with pytest.raises(StaleCompilationError):
            second_future.result(timeout=20)

    assert {path: path.read_bytes() for path in first_staged} == first_staged
    assert applied.audit_path.exists()
    assert not (tmp_path / ".modelable" / "audit" / "compilations" / "second-action.json").exists()


def test_json_schema_validation_warning_never_leaks_staging_path_to_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modelable.emitters import json_schema

    source = write_workspace(tmp_path)
    service = CompilationService(
        temp_root=tmp_path.parent,
        new_id=lambda: "warning-action",
    )

    def fail_validation(schema) -> None:
        raise ValueError("injected schema validation detail")

    monkeypatch.setattr(
        json_schema.Draft202012Validator,
        "check_schema",
        fail_validation,
    )
    pending = service.preview(
        CompilationRequest(source=source, target="json-schema"),
        policy=CompilationPolicy.conversation(),
    )

    assert any("EMIT004" in warning for warning in pending.warnings)
    assert all(str(pending.staging_dir) not in warning for warning in pending.warnings)
    applied = service.apply(pending, confirmation=confirmation_for(pending))
    serialized = applied.audit_path.read_text(encoding="utf-8")
    assert str(pending.staging_dir) not in serialized
    assert "modelable-compile-" not in serialized


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


def test_overlapping_previews_use_explicit_isolated_plan_destinations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    first_source = write_workspace(first_root)
    second_source = write_workspace(second_root)
    initial_cwd = Path.cwd()
    barrier = threading.Barrier(2)
    observed_plan_dirs: list[Path] = []
    original_write_plans = compilation.write_plans

    def synchronized_write_plans(workspace, plans_dir: Path):
        observed_plan_dirs.append(plans_dir)
        barrier.wait(timeout=10)
        return original_write_plans(workspace, plans_dir)

    monkeypatch.setattr(compilation, "write_plans", synchronized_write_plans)
    service = CompilationService(temp_root=tmp_path)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    service.preview,
                    CompilationRequest(source=source, target="json-schema"),
                    policy=CompilationPolicy.conversation(),
                )
                for source in (first_source, second_source)
            ]
            pending = [future.result(timeout=20) for future in futures]

        assert Path.cwd() == initial_cwd
        assert all(path.is_absolute() for path in observed_plan_dirs)
        assert all(file.staged_path.is_relative_to(item.staging_dir) for item in pending for file in item.files)
        assert snapshot_tree(first_root) == {Path("workspace.mdl"): first_source.read_bytes()}
        assert snapshot_tree(second_root) == {Path("workspace.mdl"): second_source.read_bytes()}
    finally:
        os.chdir(initial_cwd)
        for path in tmp_path.glob("modelable-compile-*"):
            if path.exists():
                compilation.shutil.rmtree(path)


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


def test_preview_uses_authoritative_python_artifact_refs(tmp_path: Path) -> None:
    pending = preview_for(tmp_path, write_workspace(tmp_path), target="python")

    artifact_refs = {file.ref for file in pending.files if file.category == "artifact"}
    assert {"platform.Order@1", "platform.OrderView@1"} <= artifact_refs
    assert all(file.ref is not None for file in pending.files if file.category == "artifact")


def test_affected_definitions_include_actual_cross_domain_dependencies_only(tmp_path: Path) -> None:
    source = write_workspace(
        tmp_path,
        """
domain shared {
  owner: "shared-team"
  entity Source @ 1 (additive) {
    @key sourceId: uuid
  }
  entity Unrelated @ 1 (additive) {
    @key unrelatedId: uuid
  }
}

domain consumer {
  owner: "consumer-team"
  projection SourceView @ 1
    from shared.Source @ 1 as source
  {
    sourceId <- source.sourceId
  }
}
""",
    )

    pending = preview_for(
        tmp_path,
        source,
        target="sql-postgres",
        domains=("consumer", "shared"),
    )
    affected = {item.ref: item for item in pending.affected_definitions}

    assert "consumer.SourceView@1" in affected
    assert affected["consumer.SourceView@1"].reason == "sql-postgres artifact"
    assert "shared.Source@1" in affected
    assert "required by consumer.SourceView@1" in affected["shared.Source@1"].reason
    assert "shared.Unrelated@1" not in affected
    workspace = load_workspace(source)
    assert all(
        definition_location_for_ref(workspace, ref) is not None for ref in ("consumer.SourceView@1", "shared.Source@1")
    )


def test_domain_artifact_reports_complete_definition_and_dependency_closure(tmp_path: Path) -> None:
    source = write_workspace(
        tmp_path,
        """
domain catalog {
  owner: "catalog-team"
  semantic ExternalId : string

  entity Customer @ 1 (additive) {
    @key customerId: uuid
    externalId: ExternalId
  }

  entity Account @ 1 (additive) {
    @key accountId: uuid
    customerId: uuid
  }

  projection CustomerAccount @ 1
    from catalog.Customer @ 1 as customer
    join catalog.Account @ 1 as account on customer.customerId == account.customerId
  {
    customerId <- customer.customerId
    accountId <- account.accountId
  }
}

domain unrelated {
  owner: "unrelated-team"
  semantic OtherCode : string
  entity Other @ 1 (additive) {
    @key otherId: uuid
    code: OtherCode
  }
}
""",
    )

    pending = preview_for(
        tmp_path,
        source,
        target="openmetadata",
        domains=("catalog",),
    )
    affected = {item.ref for item in pending.affected_definitions}

    assert {
        "catalog",
        "catalog.Customer@1",
        "catalog.Account@1",
        "catalog.CustomerAccount@1",
        "catalog.ExternalId",
    } <= affected
    assert not any(ref.startswith("unrelated") for ref in affected)


def test_duplicate_semantic_names_report_only_compiler_selected_declaration(tmp_path: Path) -> None:
    source = write_workspace(
        tmp_path,
        """
domain alpha {
  owner: "alpha-team"
  semantic SharedId : string
}

domain beta {
  owner: "beta-team"
  semantic SharedId : u64
}

domain consumer {
  owner: "consumer-team"
  entity Event @ 1 (additive) {
    @key eventId: uuid
    sharedId: SharedId
  }
}
""",
    )

    pending = preview_for(
        tmp_path,
        source,
        target="openmetadata",
        domains=("alpha", "consumer"),
    )
    affected = {item.ref for item in pending.affected_definitions}

    assert "alpha.SharedId" in affected
    assert "beta.SharedId" not in affected


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


@pytest.mark.parametrize(
    "registry_ids_path",
    [
        Path("safe/../.modelable/locks/ids.lock"),
        Path(".MODELABLE/intermediate/../LOCKS/ids.lock"),
    ],
)
def test_preview_normalizes_before_rejecting_internal_control_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    registry_ids_path: Path,
) -> None:
    source = write_workspace(tmp_path)

    def unexpected_ledger_read(path: Path):
        raise AssertionError(f"ledger read before policy validation: {path}")

    monkeypatch.setattr(compilation, "read_lock_file", unexpected_ledger_read)

    with pytest.raises(CompilationError, match=r"\.modelable/locks"):
        CompilationService(temp_root=tmp_path.parent).preview(
            CompilationRequest(
                source=source,
                target="json-schema",
                registry_ids_path=registry_ids_path,
            ),
            policy=CompilationPolicy.conversation(),
        )


@pytest.mark.parametrize(
    ("registry_ids_path", "message"),
    [
        (Path(".modelable/locks./ids.lock"), r"\.modelable/locks"),
        (Path(".modelable/locks /ids.lock"), r"\.modelable/locks"),
        (Path(".git./ids.lock"), r"\.git"),
        (Path(".git /ids.lock"), r"\.git"),
    ],
)
def test_preview_rejects_win32_trailing_dot_and_space_control_aliases_before_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    registry_ids_path: Path,
    message: str,
) -> None:
    source = write_workspace(tmp_path)

    def unexpected_ledger_read(path: Path):
        raise AssertionError(f"ledger read before policy validation: {path}")

    monkeypatch.setattr(compilation, "read_lock_file", unexpected_ledger_read)

    with pytest.raises(CompilationError, match=message):
        CompilationService(temp_root=tmp_path.parent).preview(
            CompilationRequest(
                source=source,
                target="json-schema",
                registry_ids_path=registry_ids_path,
            ),
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
    monkeypatch: pytest.MonkeyPatch,
    target: str,
    fixture: str,
    pattern: str,
) -> None:
    monkeypatch.chdir(tmp_path)
    source = tmp_path / fixture
    source.write_bytes((FIXTURES / fixture).read_bytes())
    result = CompilationService().execute_direct(request_for(tmp_path, source, target))

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


def test_execute_direct_emitter_failure_leaves_every_destination_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    source = write_workspace(tmp_path)
    ledger = tmp_path / "registry-ids.lock"
    registry = tmp_path / ".modelable" / "registry.db"
    plan = tmp_path / ".modelable" / "plans" / "existing.plan.json"
    artifact = tmp_path / "generated" / "existing.rs"
    for path, content in (
        (ledger, b'{"platform.SchemaId": 7}\n'),
        (registry, b"old registry"),
        (plan, b"old plan"),
        (artifact, b"old artifact"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    before = snapshot_tree(tmp_path)

    def fail_emitter(*args, **kwargs):
        raise CompilationError("injected emitter failure")

    monkeypatch.setattr(compilation, "_emit_target", fail_emitter)

    with pytest.raises(CompilationError, match="injected emitter failure"):
        CompilationService().execute_direct(
            CompilationRequest(
                source=source,
                target="rust",
                out_dir=tmp_path / "generated",
                registry_path=str(registry),
                registry_ids_path=ledger,
                allow_orphaned_registry_ids=True,
            )
        )

    assert snapshot_tree(tmp_path) == before


def test_execute_direct_promotion_failure_restores_every_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    source = write_workspace(tmp_path)
    ledger = tmp_path / "registry-ids.lock"
    registry = tmp_path / ".modelable" / "registry.db"
    ledger.write_text('{"platform.SchemaId": 1}\n', encoding="utf-8")
    registry.parent.mkdir(parents=True)
    registry.write_bytes(b"old registry")
    before = snapshot_tree(tmp_path)
    promotions = 0
    failed = False

    def fail_second_promotion(source_path, destination_path):
        nonlocal promotions, failed
        if ".modelable-tmp-" in Path(source_path).name:
            if promotions == 1 and not failed:
                failed = True
                raise OSError("injected direct promotion failure")
            promotions += 1
        os.replace(source_path, destination_path)

    service = CompilationService(
        transaction_factory=lambda root: FileTransaction(
            workspace_root=root,
            replace=fail_second_promotion,
        )
    )

    with pytest.raises(FileTransactionError, match="injected direct promotion failure"):
        service.execute_direct(
            CompilationRequest(
                source=source,
                target="rust",
                out_dir=tmp_path / "generated",
                registry_path=str(registry),
                registry_ids_path=ledger,
            )
        )

    assert snapshot_tree(tmp_path) == before


def test_execute_direct_does_not_write_conversational_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    CompilationService(new_id=lambda: "must-not-be-used").execute_direct(
        request_for(tmp_path, write_workspace(tmp_path), "rust")
    )

    assert not (tmp_path / ".modelable" / "audit").exists()


def test_execute_direct_preserves_relative_plan_and_artifact_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    result = CompilationService().execute_direct(
        CompilationRequest(
            source=write_workspace(tmp_path),
            target="rust",
            out_dir=Path("generated"),
            registry_path=".modelable/registry.db",
            registry_ids_path=Path("registry-ids.lock"),
        )
    )

    plan_event = next(
        event for event in result.events if event.path is not None and event.path.name.endswith(".plan.json")
    )
    artifact_events = [event for event in result.events if event.path is not None and event.path.suffix == ".rs"]
    assert plan_event.path is not None
    assert not plan_event.path.is_absolute()
    assert plan_event.message == f"wrote {plan_event.path}"
    assert artifact_events
    assert all(not event.path.is_absolute() for event in artifact_events if event.path is not None)
    assert all(event.message == str(event.path) for event in artifact_events)


def test_execute_direct_preserves_last_writer_for_overlapping_registry_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    source = write_workspace(tmp_path)
    reference_ledger = tmp_path / "reference-ids.lock"
    reference_registry = tmp_path / "reference-registry.db"
    CompilationService().execute_direct(
        CompilationRequest(
            source=source,
            target="rust",
            out_dir=tmp_path / "reference-generated",
            registry_path=str(reference_registry),
            registry_ids_path=reference_ledger,
        )
    )
    expected_registry = reference_registry.read_bytes()
    overlap = tmp_path / "overlap-state"

    result = CompilationService().execute_direct(
        CompilationRequest(
            source=source,
            target="rust",
            out_dir=tmp_path / "generated",
            registry_path=str(overlap),
            registry_ids_path=overlap,
        )
    )

    assert overlap.read_bytes() == expected_registry
    assert result.written_paths.count(overlap) == 1
    assert result.events[0].message == f"wrote {overlap}"
    assert not (tmp_path / ".modelable" / "audit").exists()


def test_execute_direct_normalizes_relative_and_absolute_overlapping_state_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    source = write_workspace(tmp_path)
    reference_registry = tmp_path / "reference-registry.db"
    CompilationService().execute_direct(
        CompilationRequest(
            source=source,
            target="rust",
            out_dir=tmp_path / "reference-generated",
            registry_path=str(reference_registry),
            registry_ids_path=Path("reference-ids.lock"),
        )
    )
    expected_registry = reference_registry.read_bytes()
    absolute_state = (tmp_path / "mixed-state").resolve()

    result = CompilationService().execute_direct(
        CompilationRequest(
            source=source,
            target="rust",
            out_dir=tmp_path / "generated",
            registry_path=str(absolute_state),
            registry_ids_path=Path("mixed-state"),
        )
    )

    assert absolute_state.read_bytes() == expected_registry
    assert absolute_state in result.written_paths
    assert Path("mixed-state") not in result.written_paths
    assert result.events[0].message == f"wrote {absolute_state}"


@pytest.mark.parametrize("mode", ["direct", "apply"])
def test_committed_outcome_survives_staging_cleanup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    monkeypatch.chdir(tmp_path)
    source = write_workspace(tmp_path)
    ledger = tmp_path / "registry-ids.lock"
    ledger.write_text('{"platform.SchemaId": 1}\n', encoding="utf-8")
    failed_backup = False

    def fail_backup_unlink(path: Path, *, missing_ok: bool = False) -> None:
        nonlocal failed_backup
        if ".modelable-backup-" in path.name and not failed_backup:
            failed_backup = True
            raise OSError("injected committed backup cleanup failure")
        path.unlink(missing_ok=missing_ok)

    service = CompilationService(
        temp_root=tmp_path.parent,
        transaction_factory=lambda root: FileTransaction(
            workspace_root=root,
            unlink=fail_backup_unlink,
        ),
    )
    pending = None
    if mode == "direct":

        def operation():
            return service.execute_direct(
                CompilationRequest(
                    source=source,
                    target="rust",
                    registry_ids_path=ledger,
                )
            )

    else:
        pending = service.preview(
            CompilationRequest(source=source, target="rust"),
            policy=CompilationPolicy.conversation(),
        )

        def operation():
            assert pending is not None
            return service.apply(
                pending,
                confirmation=confirmation_for(pending),
            )

    original_remove_staging = compilation._remove_staging

    def fail_staging_cleanup(path: Path) -> None:
        if path.name.startswith("modelable-"):
            raise CompilationError(f"injected staging cleanup failure: {path}")
        original_remove_staging(path)

    monkeypatch.setattr(compilation, "_remove_staging", fail_staging_cleanup)

    with pytest.raises(FileTransactionCommittedError) as raised:
        operation()

    assert raised.value.committed
    assert raised.value.written_paths
    assert len(raised.value.cleanup_errors) >= 2
    assert any("staging cleanup failure" in str(error) for error in raised.value.cleanup_errors)
    if pending is not None:
        audit = tmp_path / ".modelable" / "audit" / "compilations" / f"{pending.action_id}.json"
        assert audit.exists()
