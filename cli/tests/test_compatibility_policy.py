from __future__ import annotations

from pathlib import Path

import pytest

from modelable.compat.policy import CompatibilityPolicy, CompatibilityProfile, default_policy, load_policy
from modelable.compat.targets import SEVERITIES, TargetCompatibilityFinding, TargetCompatibilityReport


def _finding(severity: str, code: str = "some_change") -> TargetCompatibilityFinding:
    return TargetCompatibilityFinding(
        code=code,
        status=severity,
        ref="billing.Customer",
        message="synthetic finding",
        axis="wire_compatibility",
        severity=severity,
    )


def _report(target: str, *severities: str) -> TargetCompatibilityReport:
    findings = [_finding(severity) for severity in severities]
    worst = max((s for s in severities), key=SEVERITIES.index, default="compatible")
    return TargetCompatibilityReport(target=target, status=worst, severity=worst, findings=findings)


def test_default_policy_has_no_configured_thresholds():
    assert default_policy().thresholds == {}


def test_load_policy_parses_named_profiles(tmp_path: Path) -> None:
    path = tmp_path / "policy.yml"
    path.write_text(
        """
        profiles:
          public-events:
            targets: [protobuf, avro]
            requirement: full
            thresholds:
              protobuf: breaking
        """,
        encoding="utf-8",
    )
    policy = load_policy(path)

    profile = policy.profile_for("public-events")
    assert profile.targets == ("avro", "protobuf")
    assert profile.requirement == "full"
    assert profile.thresholds == {"protobuf": "breaking"}


def test_profile_for_rejects_unknown_profile() -> None:
    with pytest.raises(ValueError, match="unknown compatibility profile"):
        default_policy().profile_for("missing")


@pytest.mark.parametrize(
    ("profile", "message"),
    [
        ("invalid: []", "must be a mapping"),
        ("'': {targets: [protobuf], requirement: backward}", "non-empty strings"),
        ("invalid: {unknown: true}", "unsupported key"),
        ("invalid: {targets: [], requirement: backward}", "targets must be"),
        ("invalid: {targets: [protobuf], requirement: backward, thresholds: []}", "thresholds must be"),
        (
            "invalid: {targets: [protobuf], requirement: backward, thresholds: {protobuf: invalid}}",
            "invalid threshold",
        ),
    ],
)
def test_load_policy_rejects_invalid_profile_shapes(tmp_path: Path, profile: str, message: str) -> None:
    path = tmp_path / "policy.yml"
    path.write_text(f"profiles:\n  {profile}\n", encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_policy(path)


def test_load_policy_rejects_non_mapping_profiles(tmp_path: Path) -> None:
    path = tmp_path / "policy.yml"
    path.write_text("profiles: [invalid]\n", encoding="utf-8")

    with pytest.raises(ValueError, match=r"profiles.*mapping"):
        load_policy(path)


def test_profile_requires_known_targets_and_direction(tmp_path: Path) -> None:
    path = tmp_path / "policy.yml"
    path.write_text(
        "profiles:\n  invalid:\n    targets: [protobuf]\n    requirement: sideways\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="requirement"):
        load_policy(path)


def test_profile_enforcement_requires_target_membership_and_uses_profile_threshold() -> None:
    profile = CompatibilityProfile("public", ("protobuf",), "backward", {"protobuf": "breaking"})
    policy = CompatibilityPolicy(thresholds={}, profiles={"public": profile})

    assert policy.enforce(_report("protobuf", "migration_required"), profile=profile).passed
    with pytest.raises(ValueError, match="does not include target"):
        policy.enforce(_report("avro", "compatible"), profile=profile)


def test_default_policy_matches_the_shipped_passing_statuses_behavior():
    policy = default_policy()

    assert policy.enforce(_report("protobuf")).passed
    assert not policy.enforce(_report("protobuf", "breaking")).passed
    # gRPC's "requires_read_rebuild" maps to severity "migration_required" (Slice C3);
    # the unconfigured default already failed this before Slice C4 existed
    # (report.status was not in PASSING_STATUSES), and must still fail now.
    assert not policy.enforce(_report("grpc", "migration_required")).passed


@pytest.mark.parametrize("threshold", SEVERITIES)
def test_breaking_finding_always_blocks_regardless_of_configured_threshold(threshold):
    policy = CompatibilityPolicy(thresholds={"protobuf": threshold})

    result = policy.enforce(_report("protobuf", "breaking"))

    assert not result.passed
    assert any(finding.severity == "breaking" for finding in result.blocking_findings)


def test_policy_can_loosen_migration_required_to_pass():
    policy = CompatibilityPolicy(thresholds={"grpc": "breaking"})

    result = policy.enforce(_report("grpc", "migration_required"))

    assert result.passed
    assert result.blocking_findings == ()


def test_policy_can_tighten_review_required_to_fail():
    policy = CompatibilityPolicy(thresholds={"governance-review": "review_required"})

    result = policy.enforce(_report("governance-review", "review_required"))

    assert not result.passed
    assert len(result.blocking_findings) == 1


def test_policy_enforces_targets_independently():
    policy = CompatibilityPolicy(thresholds={"protobuf": "breaking", "grpc": "review_required"})

    protobuf_result = policy.enforce(_report("protobuf", "migration_required"))
    grpc_result = policy.enforce(_report("grpc", "migration_required"))

    assert protobuf_result.passed  # only "breaking" blocks protobuf
    assert not grpc_result.passed  # "review_required" and above blocks grpc


def test_enforce_rejects_an_invalid_threshold():
    policy = CompatibilityPolicy(thresholds={"protobuf": "not-a-severity"})

    with pytest.raises(ValueError, match="invalid compatibility policy threshold"):
        policy.enforce(_report("protobuf"))


def test_load_policy_parses_valid_yaml(tmp_path: Path):
    path = tmp_path / "policy.yml"
    path.write_text(
        """
        compatibility:
          protobuf: breaking
          sql: migration_required
        """,
        encoding="utf-8",
    )

    policy = load_policy(path)

    assert policy.thresholds == {"protobuf": "breaking", "sql": "migration_required"}


def test_load_policy_with_no_compatibility_section_is_empty(tmp_path: Path):
    path = tmp_path / "policy.yml"
    path.write_text("{}", encoding="utf-8")

    assert load_policy(path).thresholds == {}


def test_load_policy_rejects_lint_section(tmp_path: Path):
    path = tmp_path / "policy.yml"
    path.write_text(
        """
        compatibility:
          protobuf: breaking
        lint:
          require_descriptions: warning
        """,
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="lint"):
        load_policy(path)


def test_load_policy_rejects_unknown_top_level_key(tmp_path: Path):
    path = tmp_path / "policy.yml"
    path.write_text("nonsense: true\n", encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported top-level key"):
        load_policy(path)


def test_load_policy_rejects_unknown_severity(tmp_path: Path):
    path = tmp_path / "policy.yml"
    path.write_text(
        """
        compatibility:
          protobuf: super-strict
        """,
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown severity"):
        load_policy(path)


def test_load_policy_rejects_a_non_mapping_document(tmp_path: Path):
    path = tmp_path / "policy.yml"
    path.write_text("- protobuf\n- grpc\n", encoding="utf-8")

    with pytest.raises(ValueError, match="must be a YAML mapping"):
        load_policy(path)


def test_load_policy_rejects_a_non_string_threshold(tmp_path: Path):
    path = tmp_path / "policy.yml"
    path.write_text(
        """
        compatibility:
          protobuf: 42
        """,
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="string target -> string severity"):
        load_policy(path)


def test_load_policy_rejects_non_mapping_compatibility_section(tmp_path: Path):
    path = tmp_path / "policy.yml"
    path.write_text(
        """
        compatibility:
          - protobuf
        """,
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must be a mapping"):
        load_policy(path)
