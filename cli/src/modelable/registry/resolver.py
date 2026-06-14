from __future__ import annotations

from dataclasses import dataclass

from modelable.parser.ir import (
    MdlFile,
    ModelVersion,
    ProjectionVersion,
    VersionExact,
    VersionMin,
    VersionPinned,
    VersionRange,
    VersionSpec,
)
from modelable.registry.signature import compute_version_signature


@dataclass(frozen=True)
class ResolvedModelRef:
    domain_name: str
    model_name: str
    version: ModelVersion | ProjectionVersion


def resolve_model_ref(
    mdl: MdlFile,
    model_ref: str,
    version_spec: VersionSpec | int,
) -> ResolvedModelRef:
    """Resolve a model reference to a concrete published model version."""
    domain_name, model_name = _split_model_ref(model_ref)
    versions = _find_model_versions(mdl, domain_name, model_name)
    if not versions:
        raise LookupError(
            f"unresolved model reference {model_ref}@{_format_version_spec(version_spec)}"
        )

    matching = [
        version
        for version in versions
        if _matches(version, version_spec, domain_name, model_name)
    ]
    if not matching:
        raise LookupError(
            f"unresolved model reference {model_ref}@{_format_version_spec(version_spec)}"
        )

    selected = max(matching, key=lambda version: version.version)

    # If using a range or min spec, ensure no breaking change exists between
    # the requested start and the selected version.
    if isinstance(version_spec, (VersionRange, VersionMin)):
        min_v = version_spec.min_inclusive
        # Check all versions from min_v + 1 up to selected.version
        for v in versions:
            if min_v < v.version <= selected.version:
                from modelable.parser.ir import ChangeKind
                if v.change_kind == ChangeKind.breaking:
                    raise LookupError(
                        f"unresolved model reference {model_ref}@{_format_version_spec(version_spec)}: "
                        f"breaking change at version {v.version} blocks automatic resolution"
                    )

    return ResolvedModelRef(
        domain_name=domain_name,
        model_name=model_name,
        version=selected,
    )


def resolved_version_spec(
    mdl: MdlFile,
    model_ref: str,
    version_spec: VersionSpec | int,
) -> VersionExact:
    """Return the concrete version selected by a model reference."""
    resolved = resolve_model_ref(mdl, model_ref, version_spec)
    return VersionExact(version=resolved.version.version)


def find_dependents(
    mdl: MdlFile,
    domain_name: str,
    model_name: str,
    version: int,
) -> list[tuple[str, str, int]]:
    """Return list of (domain, projection, version) depending on the source model version."""
    dependents: list[tuple[str, str, int]] = []
    source_ref = f"{domain_name}.{model_name}"

    for domain in mdl.domains:
        for proj_name, proj_versions in domain.projections.items():
            for pv in proj_versions:
                # Check primary source
                is_dependent = False
                if pv.source.model == source_ref:
                    try:
                        resolved = resolve_model_ref(mdl, pv.source.model, pv.source.version)
                        if resolved.version.version == version:
                            is_dependent = True
                    except LookupError:
                        pass

                # Check joins if not already found
                if not is_dependent:
                    for join in pv.joins:
                        if join.model == source_ref:
                            try:
                                resolved = resolve_model_ref(mdl, join.model, join.version)
                                if resolved.version.version == version:
                                    is_dependent = True
                                    break
                            except LookupError:
                                pass

                if is_dependent:
                    dependents.append((domain.name, proj_name, pv.version))

    return dependents


def validate_references(mdl: MdlFile) -> list[str]:
    """Return unresolved reference errors for projections, joins, and bindings."""
    errors: list[str] = []

    for domain in mdl.domains:
        for projection_name, projection_versions in domain.projections.items():
            for projection_version in projection_versions:
                context = f"{domain.name}.{projection_name}@{projection_version.version}"
                _append_lookup_error(
                    errors,
                    context,
                    projection_version.source.model,
                    projection_version.source.version,
                    mdl,
                )
                for join in projection_version.joins:
                    _append_lookup_error(errors, context, join.model, join.version, mdl)

    for binding in mdl.bindings:
        if not binding.model:
            continue
        _append_lookup_error(
            errors,
            f"binding {binding.name}",
            binding.model,
            binding.model_version,
            mdl,
        )

    return errors


def _append_lookup_error(
    errors: list[str],
    context: str,
    model_ref: str,
    version_spec: VersionSpec | int,
    mdl: MdlFile,
) -> None:
    try:
        resolve_model_ref(mdl, model_ref, version_spec)
    except LookupError as exc:
        errors.append(f"{context}: {exc}")


def _find_model_versions(
    mdl: MdlFile,
    domain_name: str,
    model_name: str,
) -> list[ModelVersion]:
    for domain in mdl.domains:
        if domain.name == domain_name:
            versions: list[ModelVersion] = []
            versions.extend(domain.models.get(model_name, []))
            versions.extend(domain.projections.get(model_name, []))
            return versions
    return []


def _split_model_ref(model_ref: str) -> tuple[str, str]:
    parts = model_ref.split(".", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise LookupError(f"invalid model reference {model_ref}")
    return parts[0], parts[1]


def _matches(
    version: ModelVersion | ProjectionVersion,
    version_spec: VersionSpec | int,
    domain_name: str,
    model_name: str,
) -> bool:
    if isinstance(version_spec, int):
        return version.version == version_spec
    if isinstance(version_spec, VersionExact):
        return version.version == version_spec.version
    if isinstance(version_spec, VersionRange):
        return version_spec.min_inclusive <= version.version < version_spec.max_exclusive
    if isinstance(version_spec, VersionMin):
        return version.version >= version_spec.min_inclusive
    if isinstance(version_spec, VersionPinned):
        if version.version != version_spec.version:
            return False
        return (
            compute_version_signature(domain_name, model_name, version).lower()
            == version_spec.content_hash.lower()
        )
    return False


def _format_version_spec(version_spec: VersionSpec | int) -> str:
    if isinstance(version_spec, int):
        return str(version_spec)
    if isinstance(version_spec, VersionExact):
        return str(version_spec.version)
    if isinstance(version_spec, VersionRange):
        return f">={version_spec.min_inclusive}<{version_spec.max_exclusive}"
    if isinstance(version_spec, VersionMin):
        return f">={version_spec.min_inclusive}"
    if isinstance(version_spec, VersionPinned):
        return f"{version_spec.version}#{version_spec.content_hash}"
    return str(version_spec)
