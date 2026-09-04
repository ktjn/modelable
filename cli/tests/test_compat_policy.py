from __future__ import annotations

from pathlib import Path

from modelable.compat.policy import FacetRequirement, evaluate_facets, load_policy
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
