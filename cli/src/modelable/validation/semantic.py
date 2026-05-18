from __future__ import annotations

from pathlib import Path
import re

from modelable.compat.diff import compare_model_versions
from modelable.diagnostics.model import Diagnostic
from modelable.parser.ir import (
    ChangeKind,
    ClassificationLevel,
    ComputedMapping,
    MdlFile,
    ModelKind,
    ModelVersion,
)

_VALID_CLASSIFICATION_LEVELS = {level.value for level in ClassificationLevel}
_CLASSIFICATION_LEVELS_DISPLAY = ", ".join(sorted(_VALID_CLASSIFICATION_LEVELS))

_AGGREGATE_FUNCTIONS = ("count", "sum", "min", "max", "avg")
_AGGREGATE_PATTERN = re.compile(
    r"\b(" + "|".join(_AGGREGATE_FUNCTIONS) + r")\s*\(",
    re.IGNORECASE,
)


def validate(mdl: MdlFile) -> list[str]:
    """Return semantic validation errors. An empty list means the file is valid."""
    return [diagnostic.message for diagnostic in validate_diagnostics(mdl)]


def validate_diagnostics(mdl: MdlFile, path: str | Path | None = None) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for domain in mdl.domains:
        _validate_models(domain.name, domain.models, diagnostics, path)
        _validate_projections(domain.name, domain.projections, diagnostics, path)
    return diagnostics


def _validate_classification_level(
    fqn: str,
    field_name: str,
    level: str,
    diagnostics: list[Diagnostic],
    path: str | Path | None,
) -> None:
    if level not in _VALID_CLASSIFICATION_LEVELS:
        diagnostics.append(
            _diag(
                "SEM",
                f"{fqn}: field '{field_name}' has invalid classification level '{level}'. "
                f"Valid levels are: {_CLASSIFICATION_LEVELS_DISPLAY}",
                path,
            )
        )


def _validate_models(
    domain_name,
    models,
    diagnostics: list[Diagnostic],
    path: str | Path | None,
) -> None:
    for model_name, versions in models.items():
        fqn = f"{domain_name}.{model_name}"
        version_numbers = [version.version for version in versions]

        for index in range(1, len(version_numbers)):
            previous = version_numbers[index - 1]
            current = version_numbers[index]
            if current <= previous:
                diagnostics.append(
                    _diag(
                        "SEM",
                        f"{fqn}: versions must be strictly ascending, "
                        f"but found {previous} followed by {current}",
                        path,
                    )
                )

        for version in versions:
            key_fields = [field for field in version.fields if field.is_key]
            if version.model_kind in (ModelKind.entity, ModelKind.aggregate):
                if len(key_fields) != 1:
                    diagnostics.append(
                        _diag(
                            "SEM",
                            f"{fqn}@{version.version}: {version.model_kind.value} "
                            "must have exactly one @key field",
                            path,
                        )
                    )
            elif key_fields:
                diagnostics.append(
                    _diag(
                        "SEM",
                        f"{fqn}@{version.version}: {version.model_kind.value} "
                        "must not have an @key field",
                        path,
                    )
                )
            for field in version.fields:
                for annotation in field.annotations:
                    if annotation.kind == "classification":
                        _validate_classification_level(
                            f"{fqn}@{version.version}",
                            field.name,
                            annotation.level,
                            diagnostics,
                            path,
                        )

        for index in range(1, len(versions)):
            previous = versions[index - 1]
            current = versions[index]
            _validate_change_kind(fqn, previous, current, diagnostics, path)


def _validate_projections(
    domain_name,
    projections,
    diagnostics: list[Diagnostic],
    path: str | Path | None,
) -> None:
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
                    diagnostics.append(
                        _diag(
                            "SEM",
                            f"{fqn}@{version.version}: field '{field.name}' uses "
                            f"aggregation function '{aggregate_match.group(1)}' "
                            "but the projection has no group by clause",
                            path,
                        )
                    )
            for field in version.fields:
                for annotation in field.annotations:
                    if annotation.kind == "classification":
                        _validate_classification_level(
                            f"{fqn}@{version.version}",
                            field.name,
                            annotation.level,
                            diagnostics,
                            path,
                        )


def _validate_change_kind(
    fqn: str,
    previous: ModelVersion,
    current: ModelVersion,
    diagnostics: list[Diagnostic],
    path: str | Path | None,
) -> None:
    changes = compare_model_versions(previous, current)
    incompatible_changes: list[str] = []

    for change in changes:
        if change.kind == "added_field":
            field = _find_field(current, change.field_name)
            if field is None or not field.optional:
                incompatible_changes.append(f"added required field {change.field_name}")
            continue

        if change.kind == "nullability_changed":
            if change.from_optional is False and change.to_optional is True:
                continue
            incompatible_changes.append(f"nullability change {change.field_name}")
            continue

        incompatible_changes.append(f"{change.kind} {change.field_name}")

    context = f"{fqn}@{current.version}"
    if current.change_kind == ChangeKind.additive:
        if incompatible_changes:
            diagnostics.append(
                _diag(
                    "COMPAT",
                    f"{context}: additive declaration includes incompatible changes: "
                    + ", ".join(incompatible_changes),
                    path,
                )
            )
    elif current.change_kind == ChangeKind.breaking:
        if not incompatible_changes:
            diagnostics.append(
                _diag(
                    "COMPAT",
                    f"{context}: breaking declaration must include at least one incompatible change",
                    path,
                )
            )


def _find_field(version: ModelVersion, field_name: str):
    return next((field for field in version.fields if field.name == field_name), None)


def _diag(code: str, message: str, path: str | Path | None) -> Diagnostic:
    return Diagnostic(code=code, message=message, severity="error", path=str(path or "<workspace>"))
