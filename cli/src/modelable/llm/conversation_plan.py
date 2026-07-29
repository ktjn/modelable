from __future__ import annotations

import json
import re
import unicodedata
from pathlib import PurePosixPath
from typing import Annotated, Literal

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from modelable.parser.ir import Annotation, FieldDef, FieldType, ModelKind, SortField


class StrictPlanModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FieldSpec(StrictPlanModel):
    name: str
    type: FieldType
    optional: bool = False
    default: str | None = None
    annotations: list[Annotation] = Field(default_factory=list)

    def to_field_def(self) -> FieldDef:
        return FieldDef(
            name=self.name,
            type=self.type.model_copy(deep=True),
            optional=self.optional,
            default=self.default,
            annotations=[annotation.model_copy(deep=True) for annotation in self.annotations],
        )


class DirectMappingSpec(StrictPlanModel):
    kind: Literal["direct"] = "direct"
    source_alias: str
    source_field: str


class ComputedMappingSpec(StrictPlanModel):
    kind: Literal["computed"] = "computed"
    expression: str


type ProjectionMappingSpec = Annotated[
    DirectMappingSpec | ComputedMappingSpec,
    Field(discriminator="kind"),
]


class ProjectionFieldSpec(StrictPlanModel):
    name: str
    mapping: ProjectionMappingSpec
    annotations: list[Annotation] = Field(default_factory=list)


class ProjectionSourceSpec(StrictPlanModel):
    model: str
    version: int
    alias: str


class ProjectionJoinSpec(StrictPlanModel):
    model: str
    version: int
    alias: str
    on: str
    join_kind: Literal["inner", "left"] = "inner"
    cardinality: str | None = None
    annotations: list[Annotation] = Field(default_factory=list)


class SecondaryIndexSpec(StrictPlanModel):
    name: str
    key: list[str] = Field(default_factory=list)
    sort: list[SortField] = Field(default_factory=list)
    unique: bool = False


class CreateModel(StrictPlanModel):
    kind: Literal["create_model"] = "create_model"
    domain: str
    name: str
    model_kind: ModelKind
    version: int = 1
    fields: list[FieldSpec] = Field(min_length=1)


class CreateProjection(StrictPlanModel):
    kind: Literal["create_projection"] = "create_projection"
    domain: str
    name: str
    version: int = 1
    source: ProjectionSourceSpec
    fields: list[ProjectionFieldSpec] = Field(min_length=1)
    joins: list[ProjectionJoinSpec] = Field(default_factory=list)
    where: str | None = None
    group_by: list[str] = Field(default_factory=list)


class AppendModelVersion(StrictPlanModel):
    kind: Literal["append_model_version"] = "append_model_version"
    source: str
    version: int


class AppendProjectionVersion(StrictPlanModel):
    kind: Literal["append_projection_version"] = "append_projection_version"
    source: str
    version: int


class AddField(StrictPlanModel):
    kind: Literal["add_field"] = "add_field"
    target: str
    field: FieldSpec


class RenameField(StrictPlanModel):
    kind: Literal["rename_field"] = "rename_field"
    target: str
    field: str
    new_name: str


class RemoveField(StrictPlanModel):
    kind: Literal["remove_field"] = "remove_field"
    target: str
    field: str


class ChangeFieldType(StrictPlanModel):
    kind: Literal["change_field_type"] = "change_field_type"
    target: str
    field: str
    type: FieldType


class SetFieldOptionality(StrictPlanModel):
    kind: Literal["set_field_optionality"] = "set_field_optionality"
    target: str
    field: str
    optional: bool


class SetFieldAnnotations(StrictPlanModel):
    kind: Literal["set_field_annotations"] = "set_field_annotations"
    target: str
    field: str
    annotations: list[Annotation]


class SetPrimaryIndex(StrictPlanModel):
    kind: Literal["set_primary_index"] = "set_primary_index"
    target: str
    fields: list[str]


class AddSecondaryIndex(StrictPlanModel):
    kind: Literal["add_secondary_index"] = "add_secondary_index"
    target: str
    index: SecondaryIndexSpec


class RemoveSecondaryIndex(StrictPlanModel):
    kind: Literal["remove_secondary_index"] = "remove_secondary_index"
    target: str
    name: str


class SetProjectionSource(StrictPlanModel):
    kind: Literal["set_projection_source"] = "set_projection_source"
    target: str
    source: ProjectionSourceSpec


class AddProjectionField(StrictPlanModel):
    kind: Literal["add_projection_field"] = "add_projection_field"
    target: str
    field: ProjectionFieldSpec


class SetProjectionMapping(StrictPlanModel):
    kind: Literal["set_projection_mapping"] = "set_projection_mapping"
    target: str
    field: str
    mapping: ProjectionMappingSpec


class AddProjectionJoin(StrictPlanModel):
    kind: Literal["add_projection_join"] = "add_projection_join"
    target: str
    join: ProjectionJoinSpec


class SetProjectionFilter(StrictPlanModel):
    kind: Literal["set_projection_filter"] = "set_projection_filter"
    target: str
    expression: str | None


class SetProjectionGrouping(StrictPlanModel):
    kind: Literal["set_projection_grouping"] = "set_projection_grouping"
    target: str
    fields: list[str]


class RenameDefinition(StrictPlanModel):
    kind: Literal["rename_definition"] = "rename_definition"
    target: str
    new_name: str


class RetireDefinition(StrictPlanModel):
    kind: Literal["retire_definition"] = "retire_definition"
    target: str
    replacement: str | None = None


type Operation = Annotated[
    CreateModel
    | CreateProjection
    | AppendModelVersion
    | AppendProjectionVersion
    | AddField
    | RenameField
    | RemoveField
    | ChangeFieldType
    | SetFieldOptionality
    | SetFieldAnnotations
    | SetPrimaryIndex
    | AddSecondaryIndex
    | RemoveSecondaryIndex
    | SetProjectionSource
    | AddProjectionField
    | SetProjectionMapping
    | AddProjectionJoin
    | SetProjectionFilter
    | SetProjectionGrouping
    | RenameDefinition
    | RetireDefinition,
    Field(discriminator="kind"),
]


type QueryKind = Literal[
    "summary",
    "ownership",
    "lineage",
    "dependents",
    "indexes",
    "compatibility",
    "validation",
]


class QueryPlan(StrictPlanModel):
    kind: Literal["query"] = "query"
    query_kind: QueryKind
    refs: list[str] = Field(default_factory=list)
    question: str


class ChangeSetPlan(StrictPlanModel):
    kind: Literal["change_set"] = "change_set"
    summary: str
    assumptions: list[str] = Field(default_factory=list)
    edit_mode: Literal["append_versions", "draft"] = "append_versions"
    operations: list[Operation] = Field(min_length=1)


type ImplementedTarget = Literal[
    "json-schema",
    "markdown",
    "typescript",
    "csharp",
    "java",
    "python",
    "rust",
    "go",
    "sql-postgres",
    "sql-clickhouse",
    "dbt-yaml",
    "fhir-profile",
    "openmetadata",
    "openlineage",
    "odcs",
    "protobuf",
    "grpc",
]


class CompilePlan(StrictPlanModel):
    kind: Literal["compile"] = "compile"
    target: ImplementedTarget
    domains: list[str] = Field(default_factory=list)
    output: str | None = None
    descriptor_set: bool = False
    summary: str

    @model_validator(mode="after")
    def validate_compile_options(self) -> CompilePlan:
        if self.descriptor_set and self.target not in {"protobuf", "grpc"}:
            raise ValueError("descriptor_set is supported only for protobuf and grpc targets")
        for domain in self.domains:
            if (
                not domain.strip()
                or domain != domain.strip()
                or _contains_control_character(domain)
                or _is_scheme_or_drive_form(domain)
                or domain in {".", ".."}
                or "/" in domain
                or "\\" in domain
            ):
                raise ValueError("domains must contain non-empty names, not paths, URLs, or control characters")
        if self.output is not None:
            if (
                not self.output
                or self.output != self.output.strip()
                or _contains_control_character(self.output)
                or _is_scheme_or_drive_form(self.output)
                or "\\" in self.output
            ):
                raise ValueError("output must be a normalized relative POSIX path")
            path = PurePosixPath(self.output)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("output must be a normalized relative POSIX path without parent traversal")
            normalized = str(path)
            if normalized in {"", "."}:
                raise ValueError("output must name a relative directory")
            self.output = normalized
        return self


_SCHEME_OR_DRIVE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def _contains_control_character(value: str) -> bool:
    return any(unicodedata.category(character) in {"Cc", "Cf"} for character in value)


def _is_scheme_or_drive_form(value: str) -> bool:
    return _SCHEME_OR_DRIVE_RE.match(value) is not None


class ClarificationPlan(StrictPlanModel):
    kind: Literal["clarification"] = "clarification"
    question: str
    reason: str


class UnsupportedPlan(StrictPlanModel):
    kind: Literal["unsupported"] = "unsupported"
    request: str
    reason: str
    roadmap_area: Literal["vscode", "operations"] | None = None


type ConversationPlan = Annotated[
    QueryPlan | ChangeSetPlan | CompilePlan | ClarificationPlan | UnsupportedPlan,
    Field(discriminator="kind"),
]

_CONVERSATION_PLAN_ADAPTER: TypeAdapter[ConversationPlan] = TypeAdapter(ConversationPlan)


def parse_conversation_plan(text: str) -> ConversationPlan:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    payload = json.loads(stripped)
    plan = _CONVERSATION_PLAN_ADAPTER.validate_python(payload)
    Draft202012Validator(conversation_plan_json_schema()).validate(payload)
    return plan


def conversation_plan_json_schema(*, exclude_operation_kinds: frozenset[str] = frozenset()) -> dict[str, object]:
    schema = _CONVERSATION_PLAN_ADAPTER.json_schema()
    _close_object_schemas(schema)
    _require_discriminators(schema)
    if exclude_operation_kinds:
        _exclude_operation_kinds(schema, exclude_operation_kinds)
    return schema


_OPERATION_KIND_TO_DEF_NAME: dict[str, str] = {
    "create_model": "CreateModel",
    "create_projection": "CreateProjection",
    "append_model_version": "AppendModelVersion",
    "append_projection_version": "AppendProjectionVersion",
    "add_field": "AddField",
    "rename_field": "RenameField",
    "remove_field": "RemoveField",
    "change_field_type": "ChangeFieldType",
    "set_field_optionality": "SetFieldOptionality",
    "set_field_annotations": "SetFieldAnnotations",
    "set_primary_index": "SetPrimaryIndex",
    "add_secondary_index": "AddSecondaryIndex",
    "remove_secondary_index": "RemoveSecondaryIndex",
    "set_projection_source": "SetProjectionSource",
    "add_projection_field": "AddProjectionField",
    "set_projection_mapping": "SetProjectionMapping",
    "add_projection_join": "AddProjectionJoin",
    "set_projection_filter": "SetProjectionFilter",
    "set_projection_grouping": "SetProjectionGrouping",
    "rename_definition": "RenameDefinition",
    "retire_definition": "RetireDefinition",
}


def _exclude_operation_kinds(schema: dict[str, object], kinds: frozenset[str]) -> None:
    defs = schema.get("$defs")
    if not isinstance(defs, dict):
        return
    operation = defs.get("Operation")
    if not isinstance(operation, dict):
        return
    excluded_def_names = {_OPERATION_KIND_TO_DEF_NAME[kind] for kind in kinds if kind in _OPERATION_KIND_TO_DEF_NAME}
    mapping = operation.get("discriminator", {}).get("mapping")
    if isinstance(mapping, dict):
        for kind in kinds:
            mapping.pop(kind, None)
    one_of = operation.get("oneOf")
    if isinstance(one_of, list):
        operation["oneOf"] = [
            item for item in one_of if item.get("$ref", "").rsplit("/", 1)[-1] not in excluded_def_names
        ]
    for def_name in excluded_def_names:
        defs.pop(def_name, None)


def _close_object_schemas(node: object) -> None:
    if isinstance(node, dict):
        if node.get("type") == "object" and "properties" in node:
            node["additionalProperties"] = False
        for value in node.values():
            _close_object_schemas(value)
    elif isinstance(node, list):
        for value in node:
            _close_object_schemas(value)


def _require_discriminators(node: object) -> None:
    if isinstance(node, dict):
        properties = node.get("properties")
        if isinstance(properties, dict):
            kind = properties.get("kind")
            if isinstance(kind, dict) and "const" in kind:
                required = node.setdefault("required", [])
                if isinstance(required, list) and "kind" not in required:
                    required.insert(0, "kind")
        for value in node.values():
            _require_discriminators(value)
    elif isinstance(node, list):
        for value in node:
            _require_discriminators(value)
