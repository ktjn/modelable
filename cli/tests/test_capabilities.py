from modelable.capabilities import Capability, CapabilityStatus, build_capability_manifest


def test_manifest_targets_match_the_codegen_registry():
    from modelable.emitters.targets import CODEGEN_TARGETS

    manifest = build_capability_manifest()

    manifest_names = {capability.name for capability in manifest.targets}
    registry_names = {target.name for target in CODEGEN_TARGETS}
    assert manifest_names == registry_names


def test_manifest_sql_dialects_match_the_sql_registry():
    from modelable.emitters.sql import SQL_DIALECTS

    manifest = build_capability_manifest()

    manifest_names = {capability.name for capability in manifest.sql_dialects}
    registry_names = {dialect.name for dialect in SQL_DIALECTS}
    assert manifest_names == registry_names


def test_manifest_model_kinds_match_model_kind_enum():
    from modelable.parser.ir import ModelKind

    manifest = build_capability_manifest()

    manifest_names = {capability.name for capability in manifest.model_kinds}
    enum_names = {kind.value for kind in ModelKind}
    assert manifest_names == enum_names


def test_manifest_annotations_include_all_eleven_kinds():
    manifest = build_capability_manifest()

    manifest_names = {capability.name for capability in manifest.annotations}
    assert manifest_names == {
        "key",
        "pii",
        "classification",
        "deprecated",
        "owner",
        "server",
        "wire",
        "pit_cutoff",
        "latest_before",
        "latest_only",
        "custom",
    }


def test_manifest_deferred_features_are_all_status_deferred():
    manifest = build_capability_manifest()

    assert manifest.deferred_features
    assert all(capability.status is CapabilityStatus.deferred for capability in manifest.deferred_features)
    assert all(capability.notes for capability in manifest.deferred_features)


def test_manifest_all_returns_every_capability_across_categories():
    manifest = build_capability_manifest()

    total = len(manifest.all())
    expected = (
        len(manifest.targets)
        + len(manifest.sql_dialects)
        + len(manifest.model_kinds)
        + len(manifest.annotations)
        + len(manifest.deferred_features)
    )
    assert total == expected
    assert total > 0


def test_capability_status_has_the_plans_five_values():
    assert {status.value for status in CapabilityStatus} == {
        "implemented",
        "experimental",
        "deferred",
        "candidate",
        "removed",
    }


def test_capability_is_a_plain_frozen_record():
    capability = Capability(name="x", category="target", status=CapabilityStatus.implemented, description="d")
    assert capability.notes is None


def test_compile_command_target_choices_match_the_manifest():
    from click.testing import CliRunner

    from modelable.cli import cli

    result = CliRunner().invoke(cli, ["compile", "--help"])
    manifest = build_capability_manifest()
    implemented_target_names = {
        capability.name for capability in manifest.targets if capability.status.value == "implemented"
    }

    for name in implemented_target_names:
        assert name in result.output, f"{name} is implemented but missing from `compile --help`"
