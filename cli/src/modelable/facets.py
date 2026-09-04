"""Parser-independent contracts for typed semantic facets."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal, TypeGuard, cast

from modelable.dependency_graph import build_projection_dependencies
from modelable.identity import parse_declaration_id, parse_semantic_path
from modelable.parser.ir import FieldDef, MdlFile, ModelVersion, ObjectType, ProjectionVersion

if TYPE_CHECKING:
    from modelable.compiler.workspace import Workspace

type FacetSubjectKind = Literal["declaration", "field", "projection", "projection_field"]
type PropagationMode = Literal["none", "inherit", "project"]
type FacetInterpretation = Literal["known", "unknown"]

FACET_SCHEMA = "modelable.facets/v1"

_SUBJECT_KINDS = frozenset({"declaration", "field", "projection", "projection_field"})
_PROPAGATION_MODES = frozenset({"none", "inherit", "project"})
_SCHEMA_KEYWORDS = frozenset(
    {
        "type",
        "const",
        "enum",
        "properties",
        "required",
        "items",
        "minItems",
        "maxItems",
        "minimum",
        "maximum",
        "pattern",
        "additionalProperties",
    }
)
_VALUE_TYPES = frozenset({"null", "boolean", "integer", "number", "string", "array", "object"})
_QUALIFIED_IDENTIFIER = re.compile(r"[a-z][a-z0-9]*(?:[.-][a-z][a-z0-9]*)*")
_CANONICAL_IDENTITY = re.compile(
    r"(?P<namespace>[a-z][a-z0-9]*(?:[.-][a-z][a-z0-9]*)*)/"
    r"(?P<name>[a-z][a-z0-9]*(?:[.-][a-z][a-z0-9]*)*)@"
    r"(?P<version>[1-9][0-9]*)"
)


class FacetError(ValueError):
    """Raised when a facet contract is malformed or does not validate."""


class FacetPropagationError(FacetError):
    """Raised when a validated facet cannot be attached or propagated semantically."""


@dataclass(frozen=True)
class FacetIdentity:
    """A versioned, namespaced facet schema identity."""

    namespace: str
    name: str
    schema_version: int

    def __post_init__(self) -> None:
        if not isinstance(self.namespace, str) or not _QUALIFIED_IDENTIFIER.fullmatch(self.namespace):
            raise FacetError(f"facet namespace must be a lowercase qualified identifier: {self.namespace!r}")
        if not isinstance(self.name, str) or not _QUALIFIED_IDENTIFIER.fullmatch(self.name):
            raise FacetError(f"facet name must be a lowercase qualified identifier: {self.name!r}")
        if (
            not isinstance(self.schema_version, int)
            or isinstance(self.schema_version, bool)
            or self.schema_version <= 0
        ):
            raise FacetError("facet schema version must be a positive integer")

    @property
    def canonical(self) -> str:
        return f"{self.namespace}/{self.name}@{self.schema_version}"

    @classmethod
    def from_canonical(cls, value: str) -> FacetIdentity:
        if not isinstance(value, str):
            raise FacetError("facet identity must be a string")
        match = _CANONICAL_IDENTITY.fullmatch(value)
        if match is None:
            raise FacetError(f"invalid canonical facet identity: {value!r}")
        result = cls(match.group("namespace"), match.group("name"), int(match.group("version")))
        if result.canonical != value:
            raise FacetError(f"non-canonical facet identity: {value!r}")
        return result


@dataclass(frozen=True)
class FacetSubject:
    """A semantic declaration, field, projection, or projection-field target."""

    kind: FacetSubjectKind
    reference: str

    def __post_init__(self) -> None:
        if self.kind not in _SUBJECT_KINDS:
            raise FacetError(f"invalid facet subject kind: {self.kind!r}")
        if not isinstance(self.reference, str):
            raise FacetError("facet subject reference must be a string")
        try:
            if self.kind in {"declaration", "projection"}:
                parse_declaration_id(self.reference)
            else:
                parse_semantic_path(self.reference)
        except ValueError as error:
            raise FacetError(f"invalid {self.kind} facet subject reference: {self.reference!r}") from error

    @property
    def canonical(self) -> str:
        return f"{self.kind}:{self.reference}"

    @classmethod
    def parse(cls, value: str) -> FacetSubject:
        if not isinstance(value, str):
            raise FacetError("facet subject must be a string")
        kind, separator, reference = value.partition(":")
        if not separator or not kind or not reference:
            raise FacetError(f"invalid facet subject: {value!r}")
        result = cls(cast(FacetSubjectKind, kind), reference)
        if result.canonical != value:
            raise FacetError(f"non-canonical facet subject: {value!r}")
        return result


@dataclass(frozen=True)
class FacetSource:
    """Inspectable provenance for a facet's source subject and causal lineage."""

    subject: FacetSubject
    location: str | None = None
    lineage: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.subject, FacetSubject):
            raise FacetError("facet source subject must be a FacetSubject")
        for name, value in (("location", self.location), ("lineage", self.lineage)):
            if value is not None and (not isinstance(value, str) or not value):
                raise FacetError(f"facet source {name} must be a non-empty string or null")

    @classmethod
    def from_document(cls, value: object) -> FacetSource:
        document = _mapping(value, "facet source")
        _require_exact_keys(document, {"subject", "location", "lineage"}, {"subject"}, "facet source")
        subject = FacetSubject.parse(_string(document, "subject", "facet source"))
        location = _optional_string(document.get("location"), "facet source location")
        lineage = _optional_string(document.get("lineage"), "facet source lineage")
        return cls(subject, location, lineage)

    def as_dict(self) -> dict[str, object]:
        result: dict[str, object] = {"subject": self.subject.canonical}
        if self.location is not None:
            result["location"] = self.location
        if self.lineage is not None:
            result["lineage"] = self.lineage
        return result


@dataclass(frozen=True)
class FacetSchema:
    """Local schema knowledge for interpreting a facet identity."""

    identity: FacetIdentity
    value_schema: dict[str, object]
    allowed_subjects: tuple[FacetSubjectKind, ...]
    propagation: PropagationMode

    def __post_init__(self) -> None:
        if not isinstance(self.identity, FacetIdentity):
            raise FacetError("facet schema identity must be a FacetIdentity")
        copied_schema = _copy_json(self.value_schema, "facet value schema")
        if not isinstance(copied_schema, dict):
            raise FacetError("facet value schema must be an object")
        _validate_schema(copied_schema, "facet value schema")
        object.__setattr__(self, "value_schema", copied_schema)

        subjects = tuple(self.allowed_subjects)
        if not subjects:
            raise FacetError("facet schema must allow at least one subject kind")
        if any(subject not in _SUBJECT_KINDS for subject in subjects):
            raise FacetError("facet schema has an invalid allowed subject kind")
        if len(set(subjects)) != len(subjects):
            raise FacetError("facet schema has a duplicate allowed subject kind")
        object.__setattr__(self, "allowed_subjects", subjects)

        if self.propagation not in _PROPAGATION_MODES:
            raise FacetError(f"invalid facet propagation mode: {self.propagation!r}")


@dataclass(frozen=True)
class Facet:
    """A typed or uninterpreted fact attached to one semantic subject."""

    identity: FacetIdentity
    value: object
    subject: FacetSubject
    propagation: PropagationMode
    source: FacetSource | None = None
    interpretation: FacetInterpretation = "unknown"

    def __post_init__(self) -> None:
        if not isinstance(self.identity, FacetIdentity):
            raise FacetError("facet identity must be a FacetIdentity")
        if not isinstance(self.subject, FacetSubject):
            raise FacetError("facet subject must be a FacetSubject")
        if self.propagation not in _PROPAGATION_MODES:
            raise FacetError(f"invalid facet propagation mode: {self.propagation!r}")
        if self.source is not None and not isinstance(self.source, FacetSource):
            raise FacetError("facet source must be a FacetSource or null")
        if self.interpretation not in {"known", "unknown"}:
            raise FacetError(f"invalid facet interpretation: {self.interpretation!r}")
        object.__setattr__(self, "value", _copy_json(self.value, "facet value"))

    @classmethod
    def from_document(cls, value: object) -> Facet:
        document = _mapping(value, "facet")
        _require_exact_keys(
            document,
            {"identity", "value", "subject", "propagation", "source", "interpretation"},
            {"identity", "value", "subject", "propagation"},
            "facet",
        )
        source_value = document.get("source")
        source = FacetSource.from_document(source_value) if source_value is not None else None
        interpretation = document.get("interpretation", "unknown")
        if interpretation not in {"known", "unknown"}:
            raise FacetError("facet interpretation must be 'known' or 'unknown'")
        return cls(
            FacetIdentity.from_canonical(_string(document, "identity", "facet")),
            document["value"],
            FacetSubject.parse(_string(document, "subject", "facet")),
            cast(PropagationMode, _string(document, "propagation", "facet")),
            source,
            cast(FacetInterpretation, interpretation),
        )

    def as_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "identity": self.identity.canonical,
            "value": _canonical_json_value(self.value),
            "subject": self.subject.canonical,
            "propagation": self.propagation,
        }
        if self.source is not None:
            result["source"] = self.source.as_dict()
        result["interpretation"] = self.interpretation
        return result


@dataclass(frozen=True)
class FacetRegistry:
    """Local, explicit schema knowledge used to validate facet values."""

    schemas: Mapping[FacetIdentity, FacetSchema]

    def __post_init__(self) -> None:
        copied: dict[FacetIdentity, FacetSchema] = {}
        for identity, schema in self.schemas.items():
            if not isinstance(identity, FacetIdentity) or not isinstance(schema, FacetSchema):
                raise FacetError("facet registry entries must map FacetIdentity to FacetSchema")
            if identity != schema.identity:
                raise FacetError(f"facet registry key does not match schema identity {schema.identity.canonical!r}")
            copied[identity] = schema
        ordered = {identity: copied[identity] for identity in sorted(copied, key=lambda item: item.canonical)}
        object.__setattr__(self, "schemas", MappingProxyType(ordered))

    def schema_for(self, identity: FacetIdentity) -> FacetSchema | None:
        return self.schemas.get(identity)

    def validate(self, facet: Facet) -> Facet:
        if not isinstance(facet, Facet):
            raise FacetError("facet registry can validate only Facet values")
        schema = self.schema_for(facet.identity)
        if schema is None:
            return replace(facet, interpretation="unknown")
        if facet.subject.kind not in schema.allowed_subjects:
            raise FacetError(
                f"facet {facet.identity.canonical} on {facet.subject.canonical} does not allow subject kind "
                f"{facet.subject.kind!r}"
            )
        if facet.propagation != schema.propagation:
            raise FacetError(
                f"facet {facet.identity.canonical} on {facet.subject.canonical} requires propagation "
                f"{schema.propagation!r}"
            )
        try:
            _validate_value(schema.value_schema, facet.value, "facet value")
        except FacetError as error:
            raise FacetError(f"facet {facet.identity.canonical} on {facet.subject.canonical}: {error}") from error
        return replace(facet, interpretation="known")


def load_facet_document(path: Path) -> tuple[FacetRegistry, tuple[Facet, ...]]:
    """Load one explicit local facet sidecar without resolving any network resource."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise FacetError(f"unable to read facet document: {error}") from error
    except json.JSONDecodeError as error:
        raise FacetError(f"invalid JSON in facet document: {error.msg}") from error
    return load_facet_document_from_mapping(document)


def load_facet_document_from_mapping(document: Mapping[str, object]) -> tuple[FacetRegistry, tuple[Facet, ...]]:
    """Normalize a caller-supplied facet document using only its local schemas."""
    document_mapping = _mapping(document, "facet document")
    _require_exact_keys(
        document_mapping,
        {"$schema", "schemas", "facets"},
        {"$schema", "schemas", "facets"},
        "facet document",
    )
    if _string(document_mapping, "$schema", "facet document") != FACET_SCHEMA:
        raise FacetError(f"facet document $schema must be {FACET_SCHEMA!r}")

    schemas_value = document_mapping["schemas"]
    if not isinstance(schemas_value, list):
        raise FacetError("facet document schemas must be an array")
    schemas: dict[FacetIdentity, FacetSchema] = {}
    for index, value in enumerate(schemas_value):
        schema_document = _mapping(value, f"facet schema at index {index}")
        _require_exact_keys(
            schema_document,
            {"identity", "value_schema", "allowed_subjects", "propagation"},
            {"identity", "value_schema", "allowed_subjects", "propagation"},
            f"facet schema at index {index}",
        )
        allowed_subjects = schema_document["allowed_subjects"]
        if not isinstance(allowed_subjects, list) or any(not isinstance(subject, str) for subject in allowed_subjects):
            raise FacetError(f"facet schema at index {index} allowed_subjects must be an array of strings")
        identity = FacetIdentity.from_canonical(_string(schema_document, "identity", f"facet schema at index {index}"))
        if identity in schemas:
            raise FacetError(f"duplicate facet schema identity: {identity.canonical}")
        schemas[identity] = FacetSchema(
            identity=identity,
            value_schema=_mapping(schema_document["value_schema"], f"facet schema {identity.canonical} value_schema"),
            allowed_subjects=cast(tuple[FacetSubjectKind, ...], tuple(allowed_subjects)),
            propagation=cast(
                PropagationMode, _string(schema_document, "propagation", f"facet schema {identity.canonical}")
            ),
        )

    registry = FacetRegistry(schemas)
    facets_value = document_mapping["facets"]
    if not isinstance(facets_value, list):
        raise FacetError("facet document facets must be an array")
    facets: list[Facet] = []
    for index, value in enumerate(facets_value):
        facet_document = _mapping(value, f"facet at index {index}")
        _require_exact_keys(
            facet_document,
            {"identity", "value", "subject", "propagation", "source"},
            {"identity", "value", "subject", "propagation"},
            f"facet at index {index}",
        )
        facets.append(registry.validate(Facet.from_document(facet_document)))
    return registry, tuple(sorted(facets, key=lambda facet: (facet.identity.canonical, facet.subject.canonical)))


def normalize_workspace_facets(workspace: Workspace) -> tuple[Facet, ...]:
    """Resolve known facets over workspace subjects and projection field lineage.

    The sidecar remains the source of explicit facts. This pass adds only known,
    inherited or projected facts; unknown facts are retained at their source but
    are deliberately never candidates for semantic propagation.
    """
    explicit_by_subject = _explicit_facets_by_subject(workspace)
    subjects = _workspace_subjects(workspace.mdl)
    subjects.update(explicit_by_subject)
    resolved: dict[FacetSubject, tuple[Facet, ...]] = {}
    resolving: set[FacetSubject] = set()

    def resolve(subject: FacetSubject) -> tuple[Facet, ...]:
        if subject in resolved:
            return resolved[subject]
        if subject in resolving:
            raise FacetPropagationError(f"facet propagation cycle at {subject.canonical}")
        resolving.add(subject)
        try:
            explicit = explicit_by_subject.get(subject, ())
            explicit_identities = {facet.identity for facet in explicit}
            inherited = _inherited_facets(subject, explicit_by_subject)
            projected = _projected_facets(workspace.mdl, subject, resolve)
            result = tuple(
                sorted(
                    (
                        *explicit,
                        *(facet for facet in inherited if facet.identity not in explicit_identities),
                        *(facet for facet in projected if facet.identity not in explicit_identities),
                    ),
                    key=_facet_sort_key,
                )
            )
            resolved[subject] = result
            return result
        finally:
            resolving.remove(subject)

    normalized = [facet for subject in sorted(subjects, key=lambda item: item.canonical) for facet in resolve(subject)]
    return tuple(sorted(normalized, key=_facet_sort_key))


def facets_for_subject(workspace: Workspace, subject: FacetSubject) -> tuple[Facet, ...]:
    """Return the normalized facets attached to one canonical semantic subject."""
    if not isinstance(subject, FacetSubject):
        raise FacetPropagationError("facet subject queries require a FacetSubject")
    return tuple(facet for facet in normalize_workspace_facets(workspace) if facet.subject == subject)


def _explicit_facets_by_subject(workspace: Workspace) -> dict[FacetSubject, tuple[Facet, ...]]:
    explicit: dict[FacetSubject, list[Facet]] = {}
    seen: set[tuple[FacetSubject, FacetIdentity]] = set()
    for facet in workspace.facets:
        if not _subject_exists(workspace.mdl, facet.subject):
            raise FacetPropagationError(f"facet subject does not exist: {facet.subject.canonical}")
        key = (facet.subject, facet.identity)
        if key in seen:
            raise FacetPropagationError(
                f"duplicate explicit facet {facet.identity.canonical} on {facet.subject.canonical}"
            )
        seen.add(key)
        explicit.setdefault(facet.subject, []).append(facet)
    return {subject: tuple(sorted(facets, key=_facet_sort_key)) for subject, facets in explicit.items()}


def _workspace_subjects(mdl: MdlFile) -> set[FacetSubject]:
    subjects: set[FacetSubject] = set()
    for domain in mdl.domains:
        for name, versions in domain.models.items():
            for model_version in versions:
                declaration = f"{domain.name}.{name}@{model_version.version}"
                subjects.add(FacetSubject("declaration", declaration))
                for model_field in model_version.fields:
                    subjects.add(FacetSubject("field", f"{declaration}#{model_field.name}"))
        for name, projection_versions in domain.projections.items():
            for projection_version in projection_versions:
                declaration = f"{domain.name}.{name}@{projection_version.version}"
                subjects.add(FacetSubject("projection", declaration))
                for projection_field in projection_version.fields:
                    subjects.add(FacetSubject("projection_field", f"{declaration}#{projection_field.name}"))
    return subjects


def _subject_exists(mdl: MdlFile, subject: FacetSubject) -> bool:
    if subject.kind in {"declaration", "projection"}:
        domain_name, declaration_name, version_number = parse_declaration_id(subject.reference)
        version = _declaration_version(mdl, domain_name, declaration_name, version_number, subject.kind == "projection")
        return version is not None

    path = parse_semantic_path(subject.reference)
    domain_name, declaration_name, version_number = parse_declaration_id(path.declaration)
    projection = subject.kind == "projection_field"
    version = _declaration_version(mdl, domain_name, declaration_name, version_number, projection)
    if version is None:
        return False
    if projection:
        return len(path.segments) == 1 and any(field.name == path.segments[0] for field in version.fields)
    return _model_field_path_exists(cast(ModelVersion, version).fields, path.segments)


def _declaration_version(
    mdl: MdlFile,
    domain_name: str,
    declaration_name: str,
    version_number: int,
    projection: bool,
) -> ModelVersion | ProjectionVersion | None:
    domain = next((item for item in mdl.domains if item.name == domain_name), None)
    if domain is None:
        return None
    if projection:
        versions: Sequence[ModelVersion | ProjectionVersion] = domain.projections.get(declaration_name, ())
    else:
        versions = domain.models.get(declaration_name, ())
    return next((item for item in versions if item.version == version_number), None)


def _model_field_path_exists(fields: Sequence[FieldDef], segments: tuple[str, ...]) -> bool:
    current_fields = fields
    for index, segment in enumerate(segments):
        if segment in {"[]", "{}", "{key}"}:
            return False
        field_name = segment.removesuffix("[]").removesuffix("{}").removesuffix("{key}")
        field = next((item for item in current_fields if getattr(item, "name", None) == field_name), None)
        if field is None:
            return False
        if index == len(segments) - 1:
            return True
        field_type = getattr(field, "type", None)
        if not isinstance(field_type, ObjectType):
            return False
        current_fields = field_type.fields
    return False


def _inherited_facets(
    subject: FacetSubject,
    explicit_by_subject: Mapping[FacetSubject, tuple[Facet, ...]],
) -> tuple[Facet, ...]:
    ancestors = _inheritance_ancestors(subject)
    inherited: list[Facet] = []
    for ancestor in ancestors:
        for facet in explicit_by_subject.get(ancestor, ()):
            if facet.interpretation != "known" or facet.propagation != "inherit":
                continue
            inherited.append(
                replace(
                    facet,
                    subject=subject,
                    source=_derived_source(ancestor, facet),
                )
            )
    return tuple(inherited)


def _inheritance_ancestors(subject: FacetSubject) -> tuple[FacetSubject, ...]:
    if subject.kind == "field":
        path = parse_semantic_path(subject.reference)
        ancestors = [FacetSubject("declaration", path.declaration)]
        for length in range(1, len(path.segments)):
            ancestors.append(FacetSubject("field", f"{path.declaration}#{'.'.join(path.segments[:length])}"))
        return tuple(ancestors)
    if subject.kind == "projection_field":
        path = parse_semantic_path(subject.reference)
        return (FacetSubject("projection", path.declaration),)
    return ()


def _projected_facets(
    mdl: MdlFile,
    subject: FacetSubject,
    resolve: Callable[[FacetSubject], tuple[Facet, ...]],
) -> tuple[Facet, ...]:
    if subject.kind != "projection_field":
        return ()
    path = parse_semantic_path(subject.reference)
    if len(path.segments) != 1:
        return ()
    domain_name, projection_name, version_number = parse_declaration_id(path.declaration)
    projection = _declaration_version(mdl, domain_name, projection_name, version_number, True)
    if not isinstance(projection, ProjectionVersion):
        return ()

    dependencies = build_projection_dependencies(mdl, domain_name, projection_name, projection)
    projected: list[Facet] = []
    for dependency in sorted(
        (item for item in dependencies if item.target_property == path.segments[0]),
        key=lambda item: (item.source_ref, item.source_property, item.usage_kind),
    ):
        source_kind: FacetSubjectKind = (
            "projection_field" if _declaration_version_for_identity(mdl, dependency.source_ref, True) else "field"
        )
        source_subject = FacetSubject(source_kind, f"{dependency.source_ref}#{dependency.source_property}")
        for facet in resolve(source_subject):
            if facet.interpretation == "known" and facet.propagation == "project":
                projected.append(
                    replace(
                        facet,
                        subject=subject,
                        source=_derived_source(source_subject, facet),
                    )
                )
    return tuple(projected)


def _declaration_version_for_identity(
    mdl: MdlFile, identity: str, projection: bool
) -> ModelVersion | ProjectionVersion | None:
    domain_name, declaration_name, version_number = parse_declaration_id(identity)
    return _declaration_version(mdl, domain_name, declaration_name, version_number, projection)


def _derived_source(subject: FacetSubject, facet: Facet) -> FacetSource:
    source = facet.source
    return FacetSource(
        subject=subject,
        location=source.location if source is not None else None,
        lineage=source.lineage if source is not None else None,
    )


def _facet_sort_key(facet: Facet) -> tuple[str, str, str]:
    return (
        facet.subject.canonical,
        facet.identity.canonical,
        facet.source.subject.canonical if facet.source is not None else "",
    )


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise FacetError(f"{label} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise FacetError(f"{label} keys must be strings")
    return dict(value)


def _require_exact_keys(document: Mapping[str, object], allowed: set[str], required: set[str], label: str) -> None:
    unknown = sorted(set(document) - allowed)
    missing = sorted(required - set(document))
    if unknown:
        raise FacetError(f"{label} has unknown key(s): {', '.join(unknown)}")
    if missing:
        raise FacetError(f"{label} is missing required key(s): {', '.join(missing)}")


def _string(document: Mapping[str, object], key: str, label: str) -> str:
    value = document.get(key)
    if not isinstance(value, str):
        raise FacetError(f"{label} {key} must be a string")
    return value


def _optional_string(value: object, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise FacetError(f"{label} must be a non-empty string or null")
    return value


def _copy_json(value: object, label: str, ancestors: set[int] | None = None) -> object:
    seen = set() if ancestors is None else ancestors
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise FacetError(f"{label} contains a non-finite JSON number")
        return value
    if isinstance(value, list):
        value_id = id(value)
        if value_id in seen:
            raise FacetError(f"{label} must be acyclic")
        seen.add(value_id)
        try:
            return [_copy_json(item, label, seen) for item in value]
        finally:
            seen.remove(value_id)
    if isinstance(value, dict):
        value_id = id(value)
        if value_id in seen:
            raise FacetError(f"{label} must be acyclic")
        if any(not isinstance(key, str) for key in value):
            raise FacetError(f"{label} object keys must be strings")
        seen.add(value_id)
        try:
            return {key: _copy_json(item, label, seen) for key, item in value.items()}
        finally:
            seen.remove(value_id)
    raise FacetError(f"{label} contains a value that is not JSON")


def _canonical_json_value(value: object) -> object:
    copied = _copy_json(value, "facet value")
    if isinstance(copied, dict):
        return {key: _canonical_json_value(copied[key]) for key in sorted(copied)}
    if isinstance(copied, list):
        return [_canonical_json_value(item) for item in copied]
    return copied


def _canonical_json(value: object) -> str:
    return json.dumps(_canonical_json_value(value), sort_keys=True, separators=(",", ":"), allow_nan=False)


def _validate_schema(schema: dict[str, object], label: str) -> None:
    unknown = sorted(set(schema) - _SCHEMA_KEYWORDS)
    if unknown:
        raise FacetError(f"{label} contains unsupported keyword(s): {', '.join(unknown)}")

    types = _schema_types(schema, label)
    if "const" in schema:
        _copy_json(schema["const"], f"{label}.const")
    if "enum" in schema:
        enum = schema["enum"]
        if not isinstance(enum, list) or not enum:
            raise FacetError(f"{label}.enum must be a non-empty array")
        values = [_copy_json(item, f"{label}.enum") for item in enum]
        if len({_canonical_json(item) for item in values}) != len(values):
            raise FacetError(f"{label}.enum contains duplicate enum values")

    if "properties" in schema:
        properties = _mapping(schema["properties"], f"{label}.properties")
        for name, property_schema in properties.items():
            if not name:
                raise FacetError(f"{label}.properties keys must be non-empty")
            child = _mapping(property_schema, f"{label}.properties.{name}")
            _validate_schema(child, f"{label}.properties.{name}")
    if "required" in schema:
        required = schema["required"]
        if not isinstance(required, list) or any(not isinstance(name, str) or not name for name in required):
            raise FacetError(f"{label}.required must be an array of non-empty strings")
        if len(set(required)) != len(required):
            raise FacetError(f"{label}.required contains duplicate property names")
    if "additionalProperties" in schema and not isinstance(schema["additionalProperties"], bool):
        raise FacetError(f"{label}.additionalProperties must be a boolean")
    if "items" in schema:
        _validate_schema(_mapping(schema["items"], f"{label}.items"), f"{label}.items")
    for keyword in ("minItems", "maxItems"):
        if keyword in schema:
            item_count = schema[keyword]
            if not isinstance(item_count, int) or isinstance(item_count, bool) or item_count < 0:
                raise FacetError(f"{label}.{keyword} must be a non-negative integer")
    if "minItems" in schema and "maxItems" in schema:
        min_items = cast(int, schema["minItems"])
        max_items = cast(int, schema["maxItems"])
        if min_items > max_items:
            raise FacetError(f"{label} has minItems greater than maxItems")
    for keyword in ("minimum", "maximum"):
        if keyword in schema and not _is_json_number(schema[keyword]):
            raise FacetError(f"{label}.{keyword} must be a finite JSON number")
    if "minimum" in schema and "maximum" in schema:
        minimum = cast(int | float, schema["minimum"])
        maximum = cast(int | float, schema["maximum"])
        if minimum > maximum:
            raise FacetError(f"{label} has minimum greater than maximum")
    if "pattern" in schema:
        pattern = schema["pattern"]
        if not isinstance(pattern, str):
            raise FacetError(f"{label}.pattern must be a string")
        try:
            re.compile(pattern)
        except re.error as error:
            raise FacetError(f"{label}.pattern is not a valid regular expression") from error

    _validate_keyword_types(types, schema, label)


def _schema_types(schema: Mapping[str, object], label: str) -> tuple[str, ...] | None:
    if "type" not in schema:
        return None
    value = schema["type"]
    if isinstance(value, str):
        types: tuple[str, ...] = (value,)
    elif isinstance(value, list) and value and all(isinstance(item, str) for item in value):
        types = tuple(cast(list[str], value))
    else:
        raise FacetError(f"{label}.type must be a JSON type name or non-empty array of type names")
    if any(item not in _VALUE_TYPES for item in types):
        raise FacetError(f"{label}.type contains an unsupported JSON type")
    if len(set(types)) != len(types):
        raise FacetError(f"{label}.type contains duplicate JSON types")
    return types


def _validate_keyword_types(types: tuple[str, ...] | None, schema: Mapping[str, object], label: str) -> None:
    if types is None:
        return
    supported = set(types)
    if any(key in schema for key in ("properties", "required", "additionalProperties")) and "object" not in supported:
        raise FacetError(f"{label} object keywords require type 'object'")
    if any(key in schema for key in ("items", "minItems", "maxItems")) and "array" not in supported:
        raise FacetError(f"{label} array keywords require type 'array'")
    if any(key in schema for key in ("minimum", "maximum")) and not supported.intersection({"integer", "number"}):
        raise FacetError(f"{label} numeric keywords require type 'integer' or 'number'")
    if "pattern" in schema and "string" not in supported:
        raise FacetError(f"{label} pattern requires type 'string'")


def _validate_value(schema: Mapping[str, object], value: object, label: str) -> None:
    types = _schema_types(schema, label)
    if types is not None and not any(_matches_type(value, type_name) for type_name in types):
        raise FacetError(f"{label} does not match schema type")
    if "const" in schema and _canonical_json(value) != _canonical_json(schema["const"]):
        raise FacetError(f"{label} does not match schema const")
    if "enum" in schema and not any(
        _canonical_json(value) == _canonical_json(item) for item in cast(list[object], schema["enum"])
    ):
        raise FacetError(f"{label} does not match schema enum")

    if isinstance(value, dict):
        properties = cast(dict[str, object], schema.get("properties", {}))
        required = cast(list[str], schema.get("required", []))
        missing = sorted(name for name in required if name not in value)
        if missing:
            raise FacetError(f"{label} is missing required property {missing[0]!r}")
        for name in sorted(set(value) & set(properties)):
            _validate_value(_mapping(properties[name], f"{label}.{name}"), value[name], f"{label}.{name}")
        if schema.get("additionalProperties", True) is False:
            extras = sorted(set(value) - set(properties))
            if extras:
                raise FacetError(f"{label} contains unsupported property {extras[0]!r}")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < cast(int, schema["minItems"]):
            raise FacetError(f"{label} has fewer than minItems")
        if "maxItems" in schema and len(value) > cast(int, schema["maxItems"]):
            raise FacetError(f"{label} has more than maxItems")
        if "items" in schema:
            item_schema = _mapping(schema["items"], f"{label}.items")
            for index, item in enumerate(value):
                _validate_value(item_schema, item, f"{label}[{index}]")
    if _is_json_number(value):
        if "minimum" in schema and value < cast(int | float, schema["minimum"]):
            raise FacetError(f"{label} is below minimum")
        if "maximum" in schema and value > cast(int | float, schema["maximum"]):
            raise FacetError(f"{label} is above maximum")
    if isinstance(value, str) and "pattern" in schema:
        pattern = cast(str, schema["pattern"])
        if re.search(pattern, value) is None:
            raise FacetError(f"{label} does not match pattern")


def _matches_type(value: object, type_name: str) -> bool:
    return (
        (type_name == "null" and value is None)
        or (type_name == "boolean" and isinstance(value, bool))
        or (type_name == "integer" and isinstance(value, int) and not isinstance(value, bool))
        or (type_name == "number" and _is_json_number(value))
        or (type_name == "string" and isinstance(value, str))
        or (type_name == "array" and isinstance(value, list))
        or (type_name == "object" and isinstance(value, dict))
    )


def _is_json_number(value: object) -> TypeGuard[int | float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
