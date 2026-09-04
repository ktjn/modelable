from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from modelable.identity import DeclarationId, DeclarationVersion
from modelable.parser.ir import (
    AnnDeprecated,
    Annotation,
    AnnOwner,
    DomainDef,
    EnumProjectionDecl,
    FieldDef,
    MdlFile,
    ModelVersion,
    ProjectionField,
    ProjectionVersion,
    RefType,
    SemanticTypeDecl,
    ValueConstraint,
    VersionExact,
    VersionMin,
    VersionPinned,
    VersionRange,
    VersionSpec,
)
from modelable.registry.signature import compute_version_signature

DeclarationValue = ModelVersion | ProjectionVersion | SemanticTypeDecl | EnumProjectionDecl


@dataclass(frozen=True)
class _DeclarationCandidate:
    """Private normalized identity record for one concrete declaration version."""

    domain_name: str
    name: str
    declaration: DeclarationValue
    domain_owner: str | None = None
    domain_contact: str | None = None
    domain_description: str | None = None

    @property
    def version_number(self) -> int:
        return self.declaration.version

    @property
    def kind(self) -> str:
        if isinstance(self.declaration, ModelVersion):
            return "model"
        if isinstance(self.declaration, ProjectionVersion):
            return "projection"
        if isinstance(self.declaration, SemanticTypeDecl):
            return "semantic_type"
        return "enum_projection"


@dataclass(frozen=True)
class ResolvedMember:
    """Common read-only member view for declaration fields and enum members."""

    name: str
    annotations: tuple[Annotation, ...] = ()
    constraints: tuple[ValueConstraint, ...] = ()
    optional: bool | None = None
    nullable: bool | None = None

    @property
    def owner(self) -> str | None:
        """Return the owning team declared for this member, when present."""
        annotation = next((item for item in self.annotations if isinstance(item, AnnOwner)), None)
        return annotation.team if annotation is not None else None

    @property
    def deprecated_replaced_by(self) -> str | None:
        """Return the replacement member named by a deprecation annotation."""
        annotation = next((item for item in self.annotations if isinstance(item, AnnDeprecated)), None)
        return annotation.replaced_by if annotation is not None else None


def _iter_declaration_candidates(mdl: MdlFile) -> Iterator[_DeclarationCandidate]:
    """Yield all concrete named declaration versions through one boundary."""
    for domain in mdl.domains:
        yield from _iter_domain_declaration_candidates(domain)


def _iter_domain_declaration_candidates(domain: DomainDef) -> Iterator[_DeclarationCandidate]:
    """Yield all concrete named declarations belonging to one domain."""
    for model_name, model_versions in domain.models.items():
        for model_declaration in model_versions:
            yield _DeclarationCandidate(
                domain.name,
                model_name,
                model_declaration,
                domain.owner,
                domain.contact,
                domain.description,
            )
    for projection_name, projection_versions in domain.projections.items():
        for projection_declaration in projection_versions:
            yield _DeclarationCandidate(
                domain.name,
                projection_name,
                projection_declaration,
                domain.owner,
                domain.contact,
                domain.description,
            )
    for semantic_declaration in domain.semantic_types:
        yield _DeclarationCandidate(
            domain.name,
            semantic_declaration.name,
            semantic_declaration,
            domain.owner,
            domain.contact,
            domain.description,
        )
    for enum_declaration in domain.enum_projections:
        yield _DeclarationCandidate(
            domain.name,
            enum_declaration.name,
            enum_declaration,
            domain.owner,
            domain.contact,
            domain.description,
        )


def _latest_declaration_candidates(domain: DomainDef, kind: str) -> list[_DeclarationCandidate]:
    latest: dict[str, _DeclarationCandidate] = {}
    for candidate in _iter_domain_declaration_candidates(domain):
        if candidate.kind != kind:
            continue
        current = latest.get(candidate.name)
        if current is None or candidate.version_number > current.version_number:
            latest[candidate.name] = candidate
    return list(latest.values())


def latest_semantic_type_declarations(domain: DomainDef) -> list[SemanticTypeDecl]:
    """Return the latest semantic-type version for each declaration name."""
    return [
        candidate.declaration
        for candidate in _latest_declaration_candidates(domain, "semantic_type")
        if isinstance(candidate.declaration, SemanticTypeDecl)
    ]


def latest_enum_projection_declarations(domain: DomainDef) -> list[EnumProjectionDecl]:
    """Return the latest enum-projection version for each declaration name."""
    return [
        candidate.declaration
        for candidate in _latest_declaration_candidates(domain, "enum_projection")
        if isinstance(candidate.declaration, EnumProjectionDecl)
    ]


@runtime_checkable
class ResolvedDeclarationView(Protocol):
    """Common identity view for every named, versioned declaration."""

    domain_name: str
    name: str
    declaration: DeclarationValue
    kind: str
    version_number: int
    identity: str


@dataclass(frozen=True)
class ResolvedDeclaration:
    """Canonical identity view for every named, versioned declaration."""

    domain_name: str
    name: str
    declaration: DeclarationValue
    kind: str
    version_number: int
    domain_owner: str | None = None
    domain_contact: str | None = None
    domain_description: str | None = None

    @property
    def identity(self) -> str:
        return DeclarationVersion(DeclarationId(self.domain_name, self.name), self.version_number).identity

    @property
    def model_name(self) -> str:
        """Compatibility name for callers that resolve models or projections."""
        return self.name

    @property
    def version(self) -> ModelVersion | ProjectionVersion:
        """Return the resolved model/projection payload for model callers."""
        if not isinstance(self.declaration, (ModelVersion, ProjectionVersion)):
            raise TypeError("resolved declaration is not a model or projection")
        return self.declaration

    @property
    def members(self) -> tuple[ResolvedMember, ...]:
        if isinstance(self.declaration, ModelVersion):
            return tuple(_resolved_field_member(field) for field in self.declaration.fields)
        if isinstance(self.declaration, ProjectionVersion):
            return tuple(_resolved_field_member(field) for field in self.declaration.fields)
        if isinstance(self.declaration, EnumProjectionDecl):
            return tuple(ResolvedMember(name) for name in self.declaration.members)
        return ()

    @property
    def annotations(self) -> tuple[Annotation, ...]:
        annotations = getattr(self.declaration, "annotations", ())
        return tuple(annotations)

    @property
    def lineage(self) -> tuple[str, ...]:
        declaration = self.declaration
        if isinstance(declaration, ProjectionVersion):
            references = [_versioned_reference(self.domain_name, declaration.source.model, declaration.source.version)]
            references.extend(
                _versioned_reference(self.domain_name, join.model, join.version) for join in declaration.joins
            )
            return tuple(references)
        if isinstance(declaration, EnumProjectionDecl):
            return (_versioned_reference(self.domain_name, declaration.source_name, declaration.source_version),)
        return ()


def _resolved_field_member(field: FieldDef | ProjectionField) -> ResolvedMember:
    return ResolvedMember(
        name=field.name,
        annotations=tuple(field.annotations),
        constraints=tuple(field.constraints),
        optional=field.optional if isinstance(field, FieldDef) else None,
        nullable=field.nullable if isinstance(field, FieldDef) else None,
    )


def _versioned_reference(domain_name: str, name: str, version: VersionSpec | int) -> str:
    qualified_name = name if "." in name else f"{domain_name}.{name}"
    return f"{qualified_name}@{_format_version_spec(version)}"


def resolve_declaration(
    mdl: MdlFile,
    declaration_ref: str,
    version_spec: VersionSpec | int,
    *,
    allowed_kinds: frozenset[str] | None = None,
) -> ResolvedDeclaration:
    """Resolve any qualified declaration reference through one boundary.

    This service deliberately handles identity and version selection only.
    Declaration-family-specific validation remains in the compatibility
    wrappers and semantic validators.
    """
    domain_name, name = _split_model_ref(declaration_ref)
    candidates = [
        candidate
        for candidate in _iter_declaration_candidates(mdl)
        if candidate.domain_name == domain_name
        and candidate.name == name
        and (allowed_kinds is None or candidate.kind in allowed_kinds)
    ]
    matching = [
        candidate for candidate in candidates if _matches_declaration(candidate, version_spec, domain_name, name)
    ]
    if not matching:
        raise LookupError(f"unresolved declaration reference {declaration_ref}@{_format_version_spec(version_spec)}")

    selected = max(matching, key=lambda candidate: candidate.version_number)
    return ResolvedDeclaration(
        domain_name=selected.domain_name,
        name=selected.name,
        declaration=selected.declaration,
        kind=selected.kind,
        version_number=selected.version_number,
        domain_owner=selected.domain_owner,
        domain_contact=selected.domain_contact,
        domain_description=selected.domain_description,
    )


def resolve_model_ref(
    mdl: MdlFile,
    model_ref: str,
    version_spec: VersionSpec | int,
) -> ResolvedDeclaration:
    """Resolve a model reference to a concrete published model version."""
    domain_name, model_name = _split_model_ref(model_ref)
    try:
        resolved = resolve_declaration(
            mdl,
            model_ref,
            version_spec,
            allowed_kinds=frozenset({"model", "projection"}),
        )
    except LookupError as exc:
        raise LookupError(f"unresolved model reference {model_ref}@{_format_version_spec(version_spec)}") from exc
    if not isinstance(resolved.declaration, (ModelVersion, ProjectionVersion)):
        raise LookupError(f"unresolved model reference {model_ref}@{_format_version_spec(version_spec)}")

    selected = resolved.declaration

    # If using a range or min spec, ensure no breaking change exists between
    # the requested start and the selected version.
    if isinstance(version_spec, (VersionRange, VersionMin)):
        min_v = version_spec.min_inclusive
        # Check all versions from min_v + 1 up to selected.version
        versions = _find_model_versions(mdl, domain_name, model_name)
        for v in versions:
            if min_v < v.version <= selected.version:
                from modelable.parser.ir import ChangeKind

                if isinstance(v, ModelVersion) and v.change_kind == ChangeKind.breaking:
                    raise LookupError(
                        f"unresolved model reference {model_ref}@{_format_version_spec(version_spec)}: "
                        f"breaking change at version {v.version} blocks automatic resolution"
                    )

    return resolved


def resolve_ref_type(field_type: RefType, mdl: MdlFile) -> ResolvedDeclaration:
    """Resolve a ref<> field's target to a concrete model version.

    Unversioned ref<Domain.Model> resolves via VersionMin(1) ("latest
    matching") — the documented interpretation for existing files, and the
    same rule already implicit in emitters/typescript.py's codegen and the
    LSP's definition/hover "unversioned ref" handling.
    """
    version_spec = field_type.version if field_type.version is not None else VersionMin(min_inclusive=1)
    return resolve_model_ref(mdl, field_type.target, version_spec)


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


class AmbiguousSemanticTypeError(LookupError):
    """Raised when a bare semantic-type name matches more than one domain's declaration.

    A subclass of ``LookupError`` so existing ``except LookupError`` callers that
    treat "couldn't resolve" uniformly (e.g. skip and move on) keep working
    unchanged; callers that need to react differently to a genuine ambiguity
    (as opposed to a name that simply doesn't exist) can catch this specifically.
    """


def _resolve_semantic_type_ref(
    mdl: MdlFile,
    current_domain: str,
    name: str,
    exact_version: int | None = None,
) -> tuple[str, SemanticTypeDecl]:
    """Resolve a semantic-type reference to (declaring_domain_name, SemanticTypeDecl).

    ``name`` may be a bare name (resolved in ``current_domain`` first, falling back to
    a workspace-wide search only when exactly one declaration matches) or a
    domain-qualified reference (``"orders.Id"``).

    When ``exact_version`` is given, only a declaration of that name at exactly
    that version matches — a later version never re-resolves an earlier
    published consumer (evolution plan E2). Without it, the latest declared
    version wins, matching historical behavior.
    """
    if "." in name:
        selector: VersionSpec | int = exact_version if exact_version is not None else VersionMin(min_inclusive=0)
        try:
            resolved = resolve_declaration(
                mdl,
                name,
                selector,
                allowed_kinds=frozenset({"semantic_type"}),
            )
        except LookupError:
            # Preserve the established diagnostic for qualified semantic refs.
            pass
        else:
            if isinstance(resolved.declaration, SemanticTypeDecl):
                return resolved.domain_name, resolved.declaration

        domain_name, type_name = name.split(".", 1)
        domain = next((item for item in mdl.domains if item.name == domain_name), None)
        if domain is None:
            raise LookupError(f"unknown domain '{domain_name}' in semantic type reference '{name}'")
        decl = _find_semantic_decl(domain, type_name, exact_version)
        if decl is None:
            raise _unknown_semantic_type_error(name, domain, type_name, exact_version)
        return domain_name, decl

    current = next((item for item in mdl.domains if item.name == current_domain), None)
    if current is not None:
        local = _find_semantic_decl(current, name, exact_version)
        if local is not None:
            return current_domain, local

    # Workspace-wide fallback mirrors bare-name semantics: only a unique
    # workspace match is accepted, more than one is ambiguous.
    matches: list[tuple[str, SemanticTypeDecl]] = []
    for domain in mdl.domains:
        decl = _find_semantic_decl(domain, name, exact_version)
        if decl is not None:
            matches.append((domain.name, decl))
    if not matches:
        known_domains = [domain for domain in mdl.domains if any(item.name == name for item in domain.semantic_types)]
        if known_domains and exact_version is not None:
            known = sorted(
                {item.version for domain in known_domains for item in domain.semantic_types if item.name == name}
            )
            raise LookupError(f"semantic type '{name}' has no version {exact_version} (known versions: {known})")
        raise LookupError(f"unknown semantic type '{name}'")
    if len(matches) > 1:
        candidates = ", ".join(f"{domain_name}.{decl.name}" for domain_name, decl in matches)
        raise AmbiguousSemanticTypeError(f"ambiguous semantic type '{name}'; candidates: {candidates}")
    return matches[0]


def _resolve_enum_type_ref(
    mdl: MdlFile,
    current_domain: str,
    name: str,
    exact_version: int | None = None,
) -> tuple[str, SemanticTypeDecl | EnumProjectionDecl]:
    """Resolve an enum reference to a semantic enum or enum projection.

    Semantic-type resolution remains the authoritative first path so callers
    that historically resolve a shared name keep their existing behavior.
    Projection lookup is used only when that path has no match; projection
    sources intentionally continue to use ``resolve_semantic_type_ref``.
    """
    try:
        return _resolve_semantic_type_ref(mdl, current_domain, name, exact_version)
    except LookupError as semantic_error:
        if isinstance(semantic_error, AmbiguousSemanticTypeError):
            raise
        current = next((item for item in mdl.domains if item.name == current_domain), None)
        if "." not in name and current is not None:
            local = _find_enum_projection_decl(current, name, exact_version)
            if local is not None:
                return current_domain, local
        # A semantic ambiguity must not be hidden by a projection fallback.
        # A missing exact semantic version may still fall back to an exact
        # projection reference of the same name in another domain.
        if "." in name:
            domain_name, projection_name = name.split(".", 1)
            domain = next((item for item in mdl.domains if item.name == domain_name), None)
            if domain is None:
                raise semantic_error
            projection = _find_enum_projection_decl(domain, projection_name, exact_version)
            if projection is None:
                raise semantic_error
            return domain_name, projection

        matches: list[tuple[str, EnumProjectionDecl]] = []
        for domain in mdl.domains:
            projection = _find_enum_projection_decl(domain, name, exact_version)
            if projection is not None:
                matches.append((domain.name, projection))
        if not matches:
            known = sorted(
                {item.version for domain in mdl.domains for item in domain.enum_projections if item.name == name}
            )
            if known and exact_version is not None:
                raise LookupError(
                    f"enum projection '{name}' has no version {exact_version} (known versions: {known})"
                ) from semantic_error
            raise semantic_error
        if len(matches) > 1:
            candidates = ", ".join(f"{domain_name}.{projection.name}" for domain_name, projection in matches)
            raise AmbiguousSemanticTypeError(
                f"ambiguous enum type '{name}'; candidates: {candidates}"
            ) from semantic_error
        return matches[0]


def resolve_named_declaration(
    mdl: MdlFile,
    current_domain: str,
    name: str,
    exact_version: int | None = None,
    *,
    include_enum_projections: bool = True,
) -> ResolvedDeclaration:
    """Resolve one named declaration through the shared identity service."""
    if include_enum_projections:
        domain_name, declaration = _resolve_enum_type_ref(mdl, current_domain, name, exact_version)
    else:
        domain_name, declaration = _resolve_semantic_type_ref(mdl, current_domain, name, exact_version)
    return resolve_declaration(
        mdl,
        f"{domain_name}.{declaration.name}",
        declaration.version,
        allowed_kinds=frozenset(
            {
                "semantic_type" if isinstance(declaration, SemanticTypeDecl) else "enum_projection",
            }
        ),
    )


def resolve_semantic_type_ref(
    mdl: MdlFile,
    current_domain: str,
    name: str,
    exact_version: int | None = None,
) -> tuple[str, SemanticTypeDecl]:
    """Resolve a semantic type using the shared named-declaration service."""
    resolved = resolve_named_declaration(
        mdl,
        current_domain,
        name,
        exact_version,
        include_enum_projections=False,
    )
    if not isinstance(resolved.declaration, SemanticTypeDecl):
        raise TypeError("shared named-declaration service returned a non-semantic declaration")
    return resolved.domain_name, resolved.declaration


def resolve_enum_type_ref(
    mdl: MdlFile,
    current_domain: str,
    name: str,
    exact_version: int | None = None,
) -> tuple[str, SemanticTypeDecl | EnumProjectionDecl]:
    """Resolve an enum type or projection using the shared identity service."""
    resolved = resolve_named_declaration(mdl, current_domain, name, exact_version)
    if not isinstance(resolved.declaration, (SemanticTypeDecl, EnumProjectionDecl)):
        raise TypeError("shared named-declaration service returned an invalid enum declaration")
    return resolved.domain_name, resolved.declaration


def _find_semantic_decl(
    domain: DomainDef,
    name: str,
    exact_version: int | None,
) -> SemanticTypeDecl | None:
    candidate = _find_named_candidate(domain, name, "semantic_type", exact_version)
    return (
        candidate.declaration if candidate is not None and isinstance(candidate.declaration, SemanticTypeDecl) else None
    )


def _find_enum_projection_decl(
    domain: DomainDef,
    name: str,
    exact_version: int | None,
) -> EnumProjectionDecl | None:
    candidate = _find_named_candidate(domain, name, "enum_projection", exact_version)
    return (
        candidate.declaration
        if candidate is not None and isinstance(candidate.declaration, EnumProjectionDecl)
        else None
    )


def _find_named_candidate(
    domain: DomainDef,
    name: str,
    kind: str,
    exact_version: int | None,
) -> _DeclarationCandidate | None:
    candidates = [
        candidate
        for candidate in _iter_domain_declaration_candidates(domain)
        if candidate.name == name and candidate.kind == kind
    ]
    if exact_version is None:
        return max(candidates, key=lambda candidate: candidate.version_number, default=None)
    return next((candidate for candidate in candidates if candidate.version_number == exact_version), None)


def _unknown_semantic_type_error(
    name: str,
    domain: DomainDef,
    type_name: str,
    exact_version: int | None,
) -> LookupError:
    if exact_version is None:
        return LookupError(f"unknown semantic type '{name}'")
    known = sorted({item.version for item in domain.semantic_types if item.name == type_name})
    return LookupError(f"semantic type '{name}' has no version {exact_version} (known versions: {known})")


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
) -> list[ModelVersion | ProjectionVersion]:
    versions: list[ModelVersion | ProjectionVersion] = []
    for candidate in _iter_declaration_candidates(mdl):
        if (
            candidate.domain_name == domain_name
            and candidate.name == model_name
            and candidate.kind in {"model", "projection"}
            and isinstance(candidate.declaration, (ModelVersion, ProjectionVersion))
        ):
            versions.append(candidate.declaration)
    return versions


def _split_model_ref(model_ref: str) -> tuple[str, str]:
    parts = model_ref.split(".", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise LookupError(f"invalid model reference {model_ref}")
    return parts[0], parts[1]


def _matches_declaration(
    candidate: _DeclarationCandidate,
    version_spec: VersionSpec | int,
    domain_name: str,
    name: str,
) -> bool:
    """Match a version selector without imposing family-specific semantics."""
    version = candidate.version_number
    if isinstance(version_spec, int):
        return version == version_spec
    if isinstance(version_spec, VersionExact):
        return version == version_spec.version
    if isinstance(version_spec, VersionRange):
        return version_spec.min_inclusive <= version < version_spec.max_exclusive
    if isinstance(version_spec, VersionMin):
        return version >= version_spec.min_inclusive
    if isinstance(version_spec, VersionPinned):
        if version != version_spec.version:
            return False
        if not isinstance(candidate.declaration, (ModelVersion, ProjectionVersion)):
            return False
        return (
            compute_version_signature(domain_name, name, candidate.declaration).lower()
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
