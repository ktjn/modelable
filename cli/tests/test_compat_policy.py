from __future__ import annotations

from pathlib import Path

import pytest

from modelable.compat.policy import FacetRequirement, _canonical_json, _copy_json_value, evaluate_facets, load_policy
from modelable.facets import Facet, FacetIdentity, FacetSubject


def _facet(*, interpretation: str) -> Facet:
    return Facet(
        identity=FacetIdentity.from_canonical("org.example/retention-class@1"),
        value="regulated",
        subject=FacetSubject.parse("field:orders.Order@1#customerId"),
        propagation="project",
        interpretation=interpretation,  # type: ignore[arg-type]
    )


def test_known_matching_facet_satisfies_loaded_external_requirement(tmp_path: Path) -> None:
    """Dropping typed matching would make a configured governance requirement inert."""
    policy_path = tmp_path / "policy.yml"
    policy_path.write_text(
        """
facets:
  - identity: org.example/retention-class@1
    subject_kind: field
    value: regulated
""",
        encoding="utf-8",
    )

    policy = load_policy(policy_path)

    assert policy.facet_requirements == (FacetRequirement("org.example/retention-class@1", "field", "regulated"),)
    assert policy.evaluate_facets((_facet(interpretation="known"),)) == ()


def test_unknown_facet_never_satisfies_a_typed_requirement() -> None:
    """Treating an unknown schema as typed knowledge would bypass local validation."""
    requirement = FacetRequirement("org.example/retention-class@1", "field", "regulated")

    findings = evaluate_facets((requirement,), (_facet(interpretation="unknown"),))

    assert [finding.as_dict() for finding in findings] == [
        {
            "code": "facet_requirement_unsatisfied",
            "identity": "org.example/retention-class@1",
            "subject_kind": "field",
            "value": "regulated",
        }
    ]


@pytest.mark.parametrize(
    ("facets", "message"),
    [
        ("wrong", "must be an array of requirements"),
        (["wrong"], "must be a mapping"),
        ([{1: "wrong"}], "keys must be strings"),
        ([{"identity": "org.example/x@1"}], "missing key"),
        ([{"identity": "org.example/x@1", "value": 1, "extra": True}], "unsupported key"),
        ([{"identity": 1, "value": 1}], "identity must be a string"),
        ([{"identity": "org.example/x@1", "subject_kind": 1, "value": 1}], "subject_kind must be"),
        ([{"identity": "invalid", "value": 1}], "invalid canonical facet identity"),
        ([{"identity": "org.example/x@1", "subject_kind": "invalid", "value": 1}], "subject_kind must be one"),
    ],
)
def test_loaded_facet_requirements_reject_invalid_shapes(facets: object, message: str, tmp_path: Path) -> None:
    policy_path = tmp_path / "policy.yml"
    policy_path.write_text("facets: " + repr(facets), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_policy(policy_path)


def test_facet_json_helpers_reject_non_json_values() -> None:
    with pytest.raises(ValueError, match="must be JSON-compatible"):
        _copy_json_value(object(), "value")
    with pytest.raises(ValueError, match="must be JSON-compatible"):
        _canonical_json(object())
