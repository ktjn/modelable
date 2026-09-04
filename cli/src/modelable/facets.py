"""Parser-independent contracts for typed semantic facets."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Literal, TypeGuard, cast

from modelable.identity import parse_declaration_id, parse_semantic_path

type FacetSubjectKind = Literal["declaration", "field", "projection", "projection_field"]
type PropagationMode = Literal["none", "inherit", "project"]
type FacetInterpretation = Literal["known", "unknown"]

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


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise FacetError(f"{label} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise FacetError(f"{label} keys must be strings")
    return cast(dict[str, object], value)


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
