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
    def _validate_targets(self) -> AnnWire:
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
        "u8",
        "u16",
        "u32",
        "u64",
        "u128",
        "i8",
        "i16",
        "i32",
        "i64",
        "i128",
    ]
    version: Literal[4, 7] = 4


class DecimalType(BaseModel):
    kind: Literal["decimal"] = "decimal"
    precision: int
    scale: int


class FixedBinaryType(BaseModel):
    kind: Literal["fixed_binary"] = "fixed_binary"
    length: int


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
    version: VersionSpec | None = None


class EnumType(BaseModel):
    kind: Literal["enum"] = "enum"
    values: list[str]


class ObjectType(BaseModel):
    kind: Literal["object"] = "object"
    fields: list[FieldDef]


class NamedType(BaseModel):
    kind: Literal["named"] = "named"
    name: str


class EnumRefType(BaseModel):
    """Exact-versioned reference to an enum-backed semantic declaration.

    Nominal by construction: the reference carries declaring identity and exact
    version, never a copied member list (evolution plan E1).
    """

    kind: Literal["enum_ref"] = "enum_ref"
    name: str
    version: int


class UnionVariant(BaseModel):
    tag: str
    type: FieldType


class UnionType(BaseModel):
    kind: Literal["union"] = "union"
    discriminator: str
    variants: list[UnionVariant]

    @model_validator(mode="after")
    def validate_variants(self) -> UnionType:
        if not self.discriminator:
            raise ValueError("union discriminator must not be empty")
        if len(self.variants) < 2:
            raise ValueError("union must contain at least two variants")
        tags = [variant.tag for variant in self.variants]
        if len(tags) != len(set(tags)):
            raise ValueError("union variant tags must be unique")
        if not all(isinstance(variant.type, (ObjectType, NamedType, RefType)) for variant in self.variants):
            raise ValueError("union variants must be object, named, or ref types")
        return self


FieldType = Annotated[
    PrimitiveType
    | DecimalType
    | FixedBinaryType
    | ArrayType
    | MapType
    | RefType
    | EnumType
    | ObjectType
    | NamedType
    | EnumRefType
    | UnionType,
    Field(discriminator="kind"),
]


class ValueConstraint(BaseModel):
    kind: str
    value: bool | float | int | str


class FieldDef(BaseModel):
    name: str
    type: FieldType
    optional: bool = False
    nullable: bool = False
    default: str | None = None
    annotations: list[Annotation] = Field(default_factory=list)
    constraints: list[ValueConstraint] = Field(default_factory=list)

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


class ProtobufReservations(BaseModel):
    numbers: list[int] = Field(default_factory=list)
    names: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate(self) -> ProtobufReservations:
        if not self.numbers and not self.names:
            raise ValueError("protobuf reservations must reserve at least one number or name")
        seen_numbers: set[int] = set()
        for number in self.numbers:
            if number <= 0:
                raise ValueError("protobuf reservation numbers must be positive")
            if number in seen_numbers:
                raise ValueError(f"duplicate protobuf reservation number {number}")
            seen_numbers.add(number)
        seen_names: set[str] = set()
        for name in self.names:
            if name in seen_names:
                raise ValueError(f"duplicate protobuf reservation name {name}")
            seen_names.add(name)
        return self


class FieldProvenance(BaseModel):
    """Records which authored operation last determined a field's identity in
    an `evolves @ N`-expanded `ModelVersion` (evolution plan D2): inherited
    unchanged from the base, or last touched by `add`/`rename`/`replace`.
    Diagnostic/tooling metadata only -- deliberately excluded from canonical
    signature rendering (`render_signature_model_version` does not reference
    it), so it never affects equivalence between a full-form and an
    equivalent delta-form version.
    """

    field_name: str
    origin: Literal["inherited", "add", "rename", "replace"]
    renamed_from: str | None = None


class ModelVersion(BaseModel):
    model_kind: ModelKind
    version: int
    change_kind: ChangeKind
    fields: list[FieldDef]
    access: AccessBlock | None = None
    has_version_header: bool = True
    has_change_kind: bool = True
    annotations: list[Annotation] = Field(default_factory=list)
    protobuf_reservations: ProtobufReservations | None = None
    provenance: list[FieldProvenance] = Field(default_factory=list)

    def wire_targets(self) -> dict[str, WireTargetHint]:
        from modelable.parser.wire import wire_targets_from_annotations

        return wire_targets_from_annotations(self.annotations)


class AddFieldOp(BaseModel):
    """A single `add` operation inside a `evolves @ N` block (evolution plan D1)."""

    kind: Literal["add"] = "add"
    field: FieldDef


class RemoveFieldOp(BaseModel):
    """A single `remove` operation inside a `evolves @ N` block: deletes the
    complete field named ``field_name`` from the base (evolution plan D2)."""

    kind: Literal["remove"] = "remove"
    field_name: str


class RenameFieldOp(BaseModel):
    """A single `rename old -> new` operation inside a `evolves @ N` block.
    Retains the field's position; the field's definition is otherwise
    unchanged (evolution plan D2)."""

    kind: Literal["rename"] = "rename"
    old_name: str
    new_name: str


class ReplaceFieldOp(BaseModel):
    """A single `replace` operation inside a `evolves @ N` block: the target
    field is identified by ``field.name`` and replaced with the complete new
    definition, retaining position (evolution plan D2)."""

    kind: Literal["replace"] = "replace"
    field: FieldDef


EvolutionOperation = Annotated[
    AddFieldOp | RemoveFieldOp | RenameFieldOp | ReplaceFieldOp,
    Field(discriminator="kind"),
]


class ModelEvolutionDecl(BaseModel):
    """A model version authored as a delta against an exact prior version via
    `evolves @ N`, rather than a complete field list (evolution plan
    D1/D2/D3).

    Source-only form: workspace expansion resolves ``base_version`` against
    the model's existing version history, deep-copies that version's fields,
    and applies ``operations`` in order to produce a complete ``ModelVersion``
    before semantic validation ever runs -- canonical ``ModelVersion`` never
    carries partial or delta state.

    ``annotations``/``access`` follow inherit-when-omitted, replace-when-
    present: an empty ``annotations`` list or a ``None`` ``access`` here
    always means "omitted on this declaration" (the grammar has no way to
    author an explicit empty wire-annotation list or an explicit "no access
    block" other than omitting them), so workspace expansion inherits the
    base's value in that case and uses this declaration's value verbatim
    otherwise. ``protobuf_reservations`` is version-local, matching the
    full-form declaration exactly -- it is never inherited.
    """

    model_kind: ModelKind
    name: str
    version: int
    change_kind: ChangeKind = ChangeKind.additive
    has_change_kind: bool = False
    base_version: int
    operations: list[EvolutionOperation] = Field(default_factory=list)
    annotations: list[Annotation] = Field(default_factory=list)
    access: AccessBlock | None = None
    protobuf_reservations: ProtobufReservations | None = None


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


class DomainImport(BaseModel):
    domain: str
    registry: str | None = None
    version: VersionSpec | None = None
    pinned_ref: str | None = None
    pinned_version: int | None = None
    pinned_signature: str | None = None


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
    constraints: list[ValueConstraint] = Field(default_factory=list)

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


class SelectionClause(BaseModel):
    """A projection's `pick(...)`/`omit(...)` clause (Slice H1), before expansion.

    Mirrors AutoProjectionTarget's excluded_fields/excluded_annotations split,
    generalized with qualified_fields for join-alias selectors and a `mode`
    since pick/omit read as opposite of AutoProjectionTarget's always-exclude
    semantics. Expansion (planner/planner.py::expand_projection_selections)
    resolves this against the projection's source/joins and appends ordinary
    ProjectionField/DirectMapping entries to ProjectionVersion.fields -- this
    clause itself is retained afterward only so the formatter can round-trip
    the shorthand rather than re-expand it into explicit `<-` lines.
    """

    mode: Literal["pick", "omit"]
    field_names: list[str] = Field(default_factory=list)
    qualified_fields: list[tuple[str, str]] = Field(default_factory=list)
    annotations: list[Annotation] = Field(default_factory=list)


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
    protobuf_reservations: ProtobufReservations | None = None
    selection: SelectionClause | None = None
    event_operations: list[str] = Field(default_factory=list)

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


class ApiResponse(BaseModel):
    status_code: int
    projection: str
    version: int


class ApiOperation(BaseModel):
    name: str
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: str
    request: tuple[str, int] | None = None
    responses: list[ApiResponse] = Field(default_factory=list)


class ApiDecl(BaseModel):
    model: str
    version: int
    operations: list[ApiOperation] = Field(default_factory=list)


class SemanticTypeDecl(BaseModel):
    name: str
    underlying: FieldType
    version: int = 0
    change_kind: Literal["additive", "breaking"] = "additive"
    has_version_header: bool = False
    has_change_kind: bool = False
    registry: bool = False


class EnumProjectionDecl(BaseModel):
    """A nominal derived subset of an enum-backed semantic declaration.

    Authored via ``pick(...)`` or ``omit(...)`` against an exact source
    version; ``members`` holds the normalized exact resulting subset filled in
    by workspace normalization (evolution plan E3). The projection is a
    distinct contract entity from its source even when subsets match.
    """

    name: str
    version: int = 0
    change_kind: Literal["additive", "breaking"] = "additive"
    has_version_header: bool = False
    has_change_kind: bool = False
    source_name: str
    source_version: int
    selection_kind: Literal["pick", "omit"]
    selected: list[str] = Field(default_factory=list)
    members: list[str] = Field(default_factory=list)


def latest_semantic_types(domain: DomainDef) -> list[SemanticTypeDecl]:
    """Return the latest declaration for each semantic type name."""
    latest: dict[str, SemanticTypeDecl] = {}
    for declaration in domain.semantic_types:
        current = latest.get(declaration.name)
        if current is None or declaration.version > current.version:
            latest[declaration.name] = declaration
    return list(latest.values())


def latest_enum_projections(domain: DomainDef) -> list[EnumProjectionDecl]:
    """Return the latest declaration for each enum projection name."""
    latest: dict[str, EnumProjectionDecl] = {}
    for declaration in domain.enum_projections:
        current = latest.get(declaration.name)
        if current is None or declaration.version > current.version:
            latest[declaration.name] = declaration
    return list(latest.values())


class SortField(BaseModel):
    field: str
    direction: Literal["asc", "desc"] = "asc"


class SecondaryIndexDecl(BaseModel):
    name: str
    key: list[str] = Field(default_factory=list)
    sort: list[SortField] = Field(default_factory=list)
    unique: bool = False


class IndexDecl(BaseModel):
    model: str
    version: int
    primary: list[str] = Field(default_factory=list)
    secondary: list[SecondaryIndexDecl] = Field(default_factory=list)


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
    apis: list[ApiDecl] = Field(default_factory=list)
    generate_targets: list[GenerateTarget] = Field(default_factory=list)
    semantic_types: list[SemanticTypeDecl] = Field(default_factory=list)
    enum_projections: list[EnumProjectionDecl] = Field(default_factory=list)
    index_decls: list[IndexDecl] = Field(default_factory=list)
    model_evolutions: list[ModelEvolutionDecl] = Field(default_factory=list)


class PackageConfig(BaseModel):
    name: str
    include: list[str] = Field(default_factory=list)
    description: str | None = None


class WorkspaceDef(BaseModel):
    label: str | None = None
    name: str | None = None
    description: str | None = None
    generate_targets: list[GenerateTarget] = Field(default_factory=list)
    ai: AiConfig | None = None
    packages: list[PackageConfig] = Field(default_factory=list)


class MdlFile(BaseModel):
    domains: list[DomainDef] = Field(default_factory=list)
    bindings: list[BindingDef] = Field(default_factory=list)
    imports: list[DomainImport] = Field(default_factory=list)
    workspace: WorkspaceDef | None = None


ArrayType.model_rebuild()
MapType.model_rebuild()
ObjectType.model_rebuild()
FieldDef.model_rebuild()
