from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from modelable.compat.targets import SEVERITIES, TargetCompatibilityFinding, TargetCompatibilityReport

_SEVERITY_RANK = {name: rank for rank, name in enumerate(SEVERITIES)}

# The lowest severity a target enforces by default: matches the behavior
# validate-compat already shipped before this policy layer existed (only a
# fully "compatible" report passes; anything above that -- including a
# migration-required gRPC read-index change -- fails). A policy overrides
# this per target; it never changes what severity compat/targets.py already
# assigned a finding.
DEFAULT_THRESHOLD = "review_required"
PROFILE_REQUIREMENTS = frozenset({"backward", "forward", "full"})


@dataclass(frozen=True)
class CompatibilityProfile:
    """Named target and direction requirements for a compatibility check."""

    name: str
    targets: tuple[str, ...]
    requirement: str
    thresholds: dict[str, str]


@dataclass(frozen=True)
class CompatibilityPolicy:
    """Per-target enforcement thresholds (Slice C4).

    A threshold is the minimum finding severity that fails a target's
    report. Because SEVERITIES is bounded above by "breaking" and a
    threshold must be one of SEVERITIES, a "breaking" finding always has
    rank >= any valid threshold's rank -- it is structurally impossible to
    configure a policy that lets a breaking change pass. That is the
    "structural errors remain unsuppressible" guarantee, enforced by
    construction rather than by convention.
    """

    thresholds: dict[str, str]
    profiles: dict[str, CompatibilityProfile] | None = None

    def profile_for(self, name: str) -> CompatibilityProfile:
        profiles = self.profiles or {}
        try:
            return profiles[name]
        except KeyError as error:
            raise ValueError(f"unknown compatibility profile {name!r}") from error

    def threshold_for(self, target: str) -> str:
        return self.thresholds.get(target, DEFAULT_THRESHOLD)

    def enforce(
        self, report: TargetCompatibilityReport, *, profile: CompatibilityProfile | None = None
    ) -> EnforcementResult:
        if profile is not None and report.target not in profile.targets:
            raise ValueError(f"compatibility profile {profile.name!r} does not include target {report.target!r}")
        threshold = (
            profile.thresholds.get(report.target, self.threshold_for(report.target))
            if profile is not None
            else self.threshold_for(report.target)
        )
        if threshold not in _SEVERITY_RANK:
            raise ValueError(
                f"invalid compatibility policy threshold {threshold!r} for target {report.target!r}; "
                f"must be one of {', '.join(SEVERITIES)}"
            )
        threshold_rank = _SEVERITY_RANK[threshold]
        blocking = tuple(finding for finding in report.findings if _SEVERITY_RANK[finding.severity] >= threshold_rank)
        return EnforcementResult(
            target=report.target,
            threshold=threshold,
            passed=not blocking,
            blocking_findings=blocking,
        )


@dataclass(frozen=True)
class EnforcementResult:
    target: str
    threshold: str
    passed: bool
    blocking_findings: tuple[TargetCompatibilityFinding, ...]


def default_policy() -> CompatibilityPolicy:
    return CompatibilityPolicy(thresholds={}, profiles={})


def load_policy(path: Path) -> CompatibilityPolicy:
    """Load a compatibility policy from a YAML file.

    Only the `compatibility:` section is implemented. A `lint:` section (see
    the example in ROADMAP.md Slice C4) is not
    yet designed or implemented -- rejecting it explicitly here keeps a
    policy file honest about what it configures, rather than silently
    discarding a section a user believes takes effect.
    """
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(doc, dict):
        raise ValueError(f"policy file {path} must be a YAML mapping")

    unsupported = set(doc) - {"compatibility", "profiles"}
    if "lint" in unsupported:
        raise ValueError(
            "policy file has a 'lint:' section, which is not yet implemented "
            "(see Slice C4 in ROADMAP.md); remove it or "
            "only configure 'compatibility:'"
        )
    if unsupported:
        raise ValueError(f"policy file has unsupported top-level key(s): {', '.join(sorted(unsupported))}")

    compatibility = doc.get("compatibility") or {}
    if not isinstance(compatibility, dict):
        raise ValueError("policy file's 'compatibility:' section must be a mapping of target -> severity")

    thresholds: dict[str, str] = {}
    for target, threshold in compatibility.items():
        if not isinstance(target, str) or not isinstance(threshold, str):
            raise ValueError(
                f"policy file 'compatibility:' entries must be string target -> string severity, got {target!r}: {threshold!r}"
            )
        if threshold not in _SEVERITY_RANK:
            raise ValueError(
                f"policy file sets an unknown severity {threshold!r} for target {target!r}; "
                f"must be one of {', '.join(SEVERITIES)}"
            )
        thresholds[target] = threshold

    profiles_raw = doc.get("profiles") or {}
    if not isinstance(profiles_raw, dict):
        raise ValueError("policy file's 'profiles:' section must be a mapping of names to profiles")
    profiles: dict[str, CompatibilityProfile] = {}
    for name, raw_profile in profiles_raw.items():
        if not isinstance(name, str) or not name:
            raise ValueError(f"compatibility profile names must be non-empty strings: {name!r}")
        if not isinstance(raw_profile, dict):
            raise ValueError(f"compatibility profile {name!r} must be a mapping")
        if set(raw_profile) - {"targets", "requirement", "thresholds"}:
            unknown = sorted(set(raw_profile) - {"targets", "requirement", "thresholds"})
            raise ValueError(f"compatibility profile {name!r} has unsupported key(s): {', '.join(unknown)}")
        targets_raw = raw_profile.get("targets")
        requirement = raw_profile.get("requirement")
        if (
            not isinstance(targets_raw, list)
            or not targets_raw
            or not all(isinstance(target, str) and target for target in targets_raw)
            or len(set(targets_raw)) != len(targets_raw)
        ):
            raise ValueError(f"compatibility profile {name!r} targets must be a non-empty unique string array")
        if not isinstance(requirement, str) or requirement not in PROFILE_REQUIREMENTS:
            raise ValueError(
                f"compatibility profile {name!r} requirement must be one of {', '.join(sorted(PROFILE_REQUIREMENTS))}"
            )
        profile_thresholds_raw = raw_profile.get("thresholds", {})
        if not isinstance(profile_thresholds_raw, dict):
            raise ValueError(f"compatibility profile {name!r} thresholds must be a mapping")
        profile_thresholds: dict[str, str] = {}
        for target, threshold in profile_thresholds_raw.items():
            if not isinstance(target, str) or not isinstance(threshold, str) or threshold not in _SEVERITY_RANK:
                raise ValueError(f"compatibility profile {name!r} has an invalid threshold for {target!r}")
            profile_thresholds[target] = threshold
        profiles[name] = CompatibilityProfile(
            name=name,
            targets=tuple(sorted(targets_raw)),
            requirement=requirement,
            thresholds=profile_thresholds,
        )

    return CompatibilityPolicy(thresholds=thresholds, profiles=profiles)
