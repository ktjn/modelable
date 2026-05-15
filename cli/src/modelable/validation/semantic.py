from __future__ import annotations

import re

from modelable.parser.ir import ClassificationLevel, ComputedMapping, MdlFile, ModelKind

_VALID_CLASSIFICATION_LEVELS = {level.value for level in ClassificationLevel}
_CLASSIFICATION_LEVELS_DISPLAY = ", ".join(sorted(_VALID_CLASSIFICATION_LEVELS))

_AGGREGATE_FUNCTIONS = ("count", "sum", "min", "max", "avg")
_AGGREGATE_PATTERN = re.compile(
    r"\b(" + "|".join(_AGGREGATE_FUNCTIONS) + r")\s*\(",
    re.IGNORECASE,
)


def validate(mdl: MdlFile) -> list[str]:
    """Return semantic validation errors. An empty list means the file is valid."""
    errors: list[str] = []
    for domain in mdl.domains:
        _validate_models(domain.name, domain.models, errors)
        _validate_projections(domain.name, domain.projections, errors)
    return errors


def _validate_classification_level(fqn: str, field_name: str, level: str, errors: list[str]) -> None:
    if level not in _VALID_CLASSIFICATION_LEVELS:
        errors.append(
            f"{fqn}: field '{field_name}' has invalid classification level '{level}'. "
            f"Valid levels are: {_CLASSIFICATION_LEVELS_DISPLAY}"
        )


def _validate_models(domain_name, models, errors: list[str]) -> None:
    for model_name, versions in models.items():
        fqn = f"{domain_name}.{model_name}"
        version_numbers = [version.version for version in versions]

        for index in range(1, len(version_numbers)):
            previous = version_numbers[index - 1]
            current = version_numbers[index]
            if current <= previous:
                errors.append(
                    f"{fqn}: versions must be strictly ascending, "
                    f"but found {previous} followed by {current}"
                )

        for version in versions:
            key_fields = [field for field in version.fields if field.is_key]
            if version.model_kind in (ModelKind.entity, ModelKind.aggregate):
                if len(key_fields) != 1:
                    errors.append(
                        f"{fqn}@{version.version}: {version.model_kind.value} "
                        "must have exactly one @key field"
                    )
            elif key_fields:
                errors.append(
                    f"{fqn}@{version.version}: {version.model_kind.value} "
                    "must not have an @key field"
                )
            for field in version.fields:
                for annotation in field.annotations:
                    if annotation.kind == "classification":
                        _validate_classification_level(
                            f"{fqn}@{version.version}", field.name, annotation.level, errors
                        )


def _validate_projections(domain_name, projections, errors: list[str]) -> None:
    for projection_name, versions in projections.items():
        fqn = f"{domain_name}.{projection_name}"
        for version in versions:
            has_group_by = bool(version.group_by)
            for field in version.fields:
                mapping = field.mapping
                if not isinstance(mapping, ComputedMapping):
                    continue

                aggregate_match = _AGGREGATE_PATTERN.search(mapping.expression)
                if aggregate_match and not has_group_by:
                    errors.append(
                        f"{fqn}@{version.version}: field '{field.name}' uses "
                        f"aggregation function '{aggregate_match.group(1)}' "
                        "but the projection has no group by clause"
                    )
            for field in version.fields:
                for annotation in field.annotations:
                    if annotation.kind == "classification":
                        _validate_classification_level(
                            f"{fqn}@{version.version}", field.name, annotation.level, errors
                        )
