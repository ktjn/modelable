from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from modelable.diagnostics.model import Diagnostic


class ParseError(Exception):
    """Raised when .mdl input cannot be parsed."""

    def __init__(
        self,
        message: str,
        *,
        path: str | None = None,
        line: int | None = None,
        column: int | None = None,
        end_line: int | None = None,
        end_column: int | None = None,
    ) -> None:
        self.message = message
        self.path = path
        self.line = line
        self.column = column
        self.end_line = end_line
        self.end_column = end_column
        super().__init__(message)

    def diagnostic(self, path: str | None = None) -> Diagnostic:
        return Diagnostic(
            code="PARSE",
            message=self.message,
            severity="error",
            path=str(path or self.path or "<input>"),
            line=self.line,
            column=self.column,
            end_line=self.end_line,
            end_column=self.end_column,
        )


class ValidationError(Exception):
    """Raised when .mdl input parses but fails semantic validation."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("\n".join(errors))


class AnnKey(BaseModel):
    kind: Literal["key"] = "key"


class AnnPii(BaseModel):
    kind: Literal["pii"] = "pii"


class ClassificationLevel(StrEnum):
    open = "open"
    internal = "internal"
    confidential = "confidential"
    restricted = "restricted"
    secret = "secret"


class AnnClassification(BaseModel):
    kind: Literal["classification"] = "classification"
    level: str


class AnnDeprecated(BaseModel):
    kind: Literal["deprecated"] = "deprecated"
    replaced_by: str


class AnnOwner(BaseModel):
    kind: Literal["owner"] = "owner"
    team: str


class AnnServer(BaseModel):
    kind: Literal["server"] = "server"


class WireTargetHint(BaseModel):
    encoding: str | None = None
    type: str | None = None
    case: str | None = None
    overrides: dict[str, str] = Field(default_factory=dict)
    field_case: str | None = None


class AnnWire(BaseModel):
    kind: Literal["wire"] = "wire"
    targets: dict[str, WireTargetHint] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_targets(self):
        if not self.targets:
            raise ValueError("wire annotations must declare at least one target")
        for target, hint in self.targets.items():
            if (
                hint.encoding is None
                and hint.type is None
                and hint.case is None
                and not hint.overrides
                and hint.field_case is None
            ):
                raise ValueError(f"wire target '{target}' must define at least one option")
        return self


class AnnPitCutoff(BaseModel):
    kind: Literal["pit_cutoff"] = "pit_cutoff"
    expression: str


class AnnLatestBefore(BaseModel):
    kind: Literal["latest_before"] = "latest_before"
    expression: str


class AnnLatestOnly(BaseModel):
    kind: Literal["latest_only"] = "latest_only"


class AnnCustom(BaseModel):
    kind: Literal["custom"] = "custom"
    name: str
    expression: str | None = None


Annotation = Annotated[
    AnnKey
    | AnnPii
    | AnnClassification
    | AnnDeprecated
    | AnnOwner
    | AnnServer
    | AnnWire
    | AnnPitCutoff
    | AnnLatestBefore
    | AnnLatestOnly
    | AnnCustom,
    Field(discriminator="kind"),
]


class PrimitiveType(BaseModel):
    kind: Literal[
        "string",
        "int",
        "float",
        "bool",
        "date",
        "time",
        "timestamp",
        "uuid",
        "duration",
        "binary",
        "json",
    ]


class DecimalType(BaseModel):
    kind: Literal["decimal"] = "decimal"
    precision: int
    scale: int


class ArrayType(BaseModel):
    kind: Literal["array"] = "array"
    item: FieldType


class MapType(BaseModel):
    kind: Literal["map"] = "map"
    key: FieldType
    value: FieldType


class RefType(BaseModel):
    kind: Literal["ref"] = "ref"
    target: str


class EnumType(BaseModel):
    kind: Literal["enum"] = "enum"
    values: list[str]


class ObjectType(BaseModel):
    kind: Literal["object"] = "object"
    fields: list[FieldDef]


class NamedType(BaseModel):
    kind: Literal["named"] = "named"
    name: str


FieldType = Annotated[
    PrimitiveType
    | DecimalType
    | ArrayType
    | MapType
    | RefType
    | EnumType
    | ObjectType
    | NamedType,
    Field(discriminator="kind"),
]


class FieldDef(BaseModel):
    name: str
    type: FieldType
    optional: bool = False
    default: str | None = None
    annotations: list[Annotation] = Field(default_factory=list)

    @property
    def is_key(self) -> bool:
        return any(annotation.kind == "key" for annotation in self.annotations)

    @property
    def is_pii(self) -> bool:
        return any(annotation.kind == "pii" for annotation in self.annotations)

    @property
    def classification(self) -> ClassificationLevel | None:
        for annotation in self.annotations:
            if annotation.kind == "classification":
                try:
                    return ClassificationLevel(annotation.level)
                except ValueError:
                    return None
        return None

    def wire_targets(self) -> dict[str, WireTargetHint]:
        from modelable.parser.wire import wire_targets_from_annotations

        return wire_targets_from_annotations(self.annotations)


class ModelKind(StrEnum):
    entity = "entity"
    aggregate = "aggregate"
    event = "event"
    value = "value"


class ChangeKind(StrEnum):
    additive = "additive"
    breaking = "breaking"


class AccessGrant(BaseModel):
    principal: str
    permissions: list[str]


class AccessBlock(BaseModel):
    entity: list[AccessGrant] = Field(default_factory=list)
    properties: dict[str, list[AccessGrant]] = Field(default_factory=dict)


class ModelVersion(BaseModel):
    model_kind: ModelKind
    version: int
    change_kind: ChangeKind
    fields: list[FieldDef]
    access: AccessBlock | None = None
    has_version_header: bool = True
    has_change_kind: bool = True
    annotations: list[Annotation] = Field(default_factory=list)

    def wire_targets(self) -> dict[str, WireTargetHint]:
        from modelable.parser.wire import wire_targets_from_annotations

        return wire_targets_from_annotations(self.annotations)


class VersionExact(BaseModel):
    kind: Literal["exact"] = "exact"
    version: int


class VersionRange(BaseModel):
    kind: Literal["range"] = "range"
    min_inclusive: int
    max_exclusive: int


class VersionMin(BaseModel):
    kind: Literal["min"] = "min"
    min_inclusive: int


class VersionPinned(BaseModel):
    kind: Literal["pinned"] = "pinned"
    version: int
    content_hash: str


VersionSpec = Annotated[
    VersionExact | VersionRange | VersionMin | VersionPinned,
    Field(discriminator="kind"),
]


class SourceRef(BaseModel):
    model: str
    version: VersionSpec
    alias: str
    where: str | None = None


class JoinRef(BaseModel):
    model: str
    version: VersionSpec
    alias: str
    on: str
    join_kind: str = "inner"
    cardinality: str | None = None
    annotations: list[Annotation] = Field(default_factory=list)


class DirectMapping(BaseModel):
    kind: Literal["direct"] = "direct"
    source_alias: str
    source_field: str


class ComputedMapping(BaseModel):
    kind: Literal["computed"] = "computed"
    expression: str


ProjectionMapping = Annotated[
    DirectMapping | ComputedMapping,
    Field(discriminator="kind"),
]


class ProjectionField(BaseModel):
    name: str
    mapping: ProjectionMapping
    annotations: list[Annotation] = Field(default_factory=list)

    @property
    def is_pii(self) -> bool:
        return any(annotation.kind == "pii" for annotation in self.annotations)

    @property
    def classification(self) -> ClassificationLevel | None:
        for annotation in self.annotations:
            if annotation.kind == "classification":
                try:
                    return ClassificationLevel(annotation.level)
                except ValueError:
                    return None
        return None

    def wire_targets(self) -> dict[str, WireTargetHint]:
        from modelable.parser.wire import wire_targets_from_annotations

        return wire_targets_from_annotations(self.annotations)


class ProjectionVersion(BaseModel):
    version: int
    source: SourceRef
    joins: list[JoinRef] = Field(default_factory=list)
    where: str | None = None
    group_by: list[str] = Field(default_factory=list)
    fields: list[ProjectionField]
    auto_generated: bool = False
    access: AccessBlock | None = None
    annotations: list[Annotation] = Field(default_factory=list)

    def wire_targets(self) -> dict[str, WireTargetHint]:
        from modelable.parser.wire import wire_targets_from_annotations

        return wire_targets_from_annotations(self.annotations)


class AutoProjectionTarget(BaseModel):
    kind: Literal["db", "request", "reply", "event"]
    excluded_fields: list[str] = Field(default_factory=list)
    excluded_annotations: list[Annotation] = Field(default_factory=list)
    operations: list[str] = Field(default_factory=list)


class AutoProjectionDecl(BaseModel):
    model: str
    version: int
    targets: list[AutoProjectionTarget]


class GenerateTarget(BaseModel):
    name: str
    dialect: str | None = None
    output_path: str | None = None


class AiConfig(BaseModel):
    provider: str | None = None
    model: str | None = None
    repair_attempts: int | None = None


class FieldMapping(BaseModel):
    source: str
    target: str


class BindingDef(BaseModel):
    name: str
    model: str
    model_version: int
    adapter: str
    table: str | None = None
    field_mappings: list[FieldMapping] = Field(default_factory=list)


class DomainDef(BaseModel):
    name: str
    owner: str | None = None
    contact: str | None = None
    description: str | None = None
    models: dict[str, list[ModelVersion]] = Field(default_factory=dict)
    projections: dict[str, list[ProjectionVersion]] = Field(default_factory=dict)
    auto_projections: list[AutoProjectionDecl] = Field(default_factory=list)
    generate_targets: list[GenerateTarget] = Field(default_factory=list)


class WorkspaceDef(BaseModel):
    label: str | None = None
    name: str | None = None
    description: str | None = None
    generate_targets: list[GenerateTarget] = Field(default_factory=list)
    ai: AiConfig | None = None


class MdlFile(BaseModel):
    domains: list[DomainDef] = Field(default_factory=list)
    bindings: list[BindingDef] = Field(default_factory=list)
    workspace: WorkspaceDef | None = None


ArrayType.model_rebuild()
MapType.model_rebuild()
ObjectType.model_rebuild()
FieldDef.model_rebuild()
