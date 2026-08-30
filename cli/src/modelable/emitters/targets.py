from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from modelable.extensions import ExtensionDescriptor, modelable_version

TargetStatus = Literal["implemented", "deferred"]
TargetKind = Literal["artifact", "language"]


@dataclass(frozen=True)
class CodegenTarget:
    name: str
    description: str
    status: TargetStatus
    kind: TargetKind
    default_out_dir: Path | None = None
    supports_compat_check: bool = False
    overlay_schema: str | None = None
    capabilities: tuple[str, ...] = ("enums", "maps", "records", "semantic-types")

    def extension_descriptor(self) -> ExtensionDescriptor:
        return ExtensionDescriptor(
            protocol="modelable.extension/v1",
            id=f"modelable.target.{self.name}",
            version=modelable_version(),
            accepted_plan_versions=("modelable.plan/v0",),
            capabilities=self.capabilities,
            configuration_schema=self.overlay_schema,
            output_kinds=(self.kind,),
            compatibility_support=self.supports_compat_check,
        )


CODEGEN_TARGETS: tuple[CodegenTarget, ...] = (
    CodegenTarget(
        name="json-schema",
        description="JSON Schema 2020-12 artifacts with x-modelable extensions",
        status="implemented",
        kind="artifact",
        default_out_dir=Path("./dist/jsonschema"),
        capabilities=("constraints", "enums", "maps", "records", "semantic-types", "unions"),
    ),
    CodegenTarget(
        name="markdown",
        description="Markdown documentation with field and lineage tables",
        status="implemented",
        kind="artifact",
        default_out_dir=Path("./dist/docs"),
    ),
    CodegenTarget(
        name="typescript",
        description="Native TypeScript interfaces emitted from the normalized graph",
        status="implemented",
        kind="language",
        default_out_dir=Path("./dist/types"),
    ),
    CodegenTarget(
        name="csharp",
        description="Native C# records emitted from the normalized graph",
        status="implemented",
        kind="language",
        default_out_dir=Path("./dist/csharp"),
    ),
    CodegenTarget(
        name="java",
        description="Native Java records emitted from the normalized graph",
        status="implemented",
        kind="language",
        default_out_dir=Path("./dist/java"),
    ),
    CodegenTarget(
        name="python",
        description="Native Python dataclasses emitted from the normalized graph",
        status="implemented",
        kind="language",
        default_out_dir=Path("./dist/python"),
    ),
    CodegenTarget(
        name="rust",
        description="Native Rust structs emitted from the normalized graph",
        status="implemented",
        kind="language",
        default_out_dir=Path("./dist/rust"),
    ),
    CodegenTarget(
        name="go",
        description="Native Go structs emitted from the normalized graph",
        status="implemented",
        kind="language",
        default_out_dir=Path("./dist/go"),
    ),
    CodegenTarget(
        name="sql-postgres",
        description="PostgreSQL CREATE TABLE DDL for projections",
        status="implemented",
        kind="artifact",
        default_out_dir=Path("./dist/sql/postgres"),
        overlay_schema="modelable/schemas/overlays/sql-postgres-v1.schema.json",
    ),
    CodegenTarget(
        name="sql-clickhouse",
        description="ClickHouse CREATE TABLE DDL for projections",
        status="implemented",
        kind="artifact",
        default_out_dir=Path("./dist/sql/clickhouse"),
        overlay_schema="modelable/schemas/overlays/sql-clickhouse-v1.schema.json",
    ),
    CodegenTarget(
        name="dbt-yaml",
        description="dbt schema.yml fragments for models and projections",
        status="implemented",
        kind="artifact",
        default_out_dir=Path("./dist/dbt"),
    ),
    CodegenTarget(
        name="fhir-profile",
        description="FHIR R4 StructureDefinition profiles for projections",
        status="implemented",
        kind="artifact",
        default_out_dir=Path("./dist/fhir"),
    ),
    CodegenTarget(
        name="openmetadata",
        description="OpenMetadata ingestion format for domains, lineage, and classification",
        status="implemented",
        kind="artifact",
        default_out_dir=Path("./dist/openmetadata"),
    ),
    CodegenTarget(
        name="openlineage",
        description="OpenLineage design-time run events with dataset schema and column lineage facets",
        status="implemented",
        kind="artifact",
        default_out_dir=Path("./dist/openlineage"),
    ),
    CodegenTarget(
        name="odcs",
        description="Open Data Contract Standard YAML documents for models and projections",
        status="implemented",
        kind="artifact",
        default_out_dir=Path("./dist/odcs"),
    ),
    CodegenTarget(
        name="protobuf",
        description="Protocol Buffers schema artifacts and Modelable schema manifest",
        status="implemented",
        kind="artifact",
        default_out_dir=Path("./dist/protobuf"),
        supports_compat_check=True,
    ),
    CodegenTarget(
        name="grpc",
        description="Scalable gRPC service profile over generated Protocol Buffers schemas",
        status="implemented",
        kind="artifact",
        default_out_dir=Path("./dist/grpc"),
        supports_compat_check=True,
    ),
    CodegenTarget(
        name="openapi",
        description="OpenAPI 3.1 component schemas generated from API-facing projections",
        status="implemented",
        kind="artifact",
        default_out_dir=Path("./dist/openapi"),
        supports_compat_check=True,
        capabilities=("constraints", "enums", "maps", "records", "semantic-types", "unions"),
    ),
    CodegenTarget(
        name="avro",
        description="Avro record schemas for models and event projections",
        status="implemented",
        kind="artifact",
        default_out_dir=Path("./dist/avro"),
    ),
    CodegenTarget(
        name="registry",
        description="Deterministic registry of generated contract versions and signatures",
        status="implemented",
        kind="artifact",
        default_out_dir=Path("./dist/registry"),
    ),
    CodegenTarget(
        name="event-sink",
        description="Adapter-neutral change-event and transactional outbox contract",
        status="implemented",
        kind="artifact",
        default_out_dir=Path("./dist/event-sink"),
    ),
)


def list_codegen_targets() -> list[CodegenTarget]:
    return list(CODEGEN_TARGETS)


def list_implemented_codegen_targets() -> list[CodegenTarget]:
    return [target for target in CODEGEN_TARGETS if target.status == "implemented"]


def get_codegen_target(name: str) -> CodegenTarget:
    for target in CODEGEN_TARGETS:
        if target.name == name:
            return target
    raise KeyError(name)


def list_compat_checkable_targets() -> list[CodegenTarget]:
    return [target for target in CODEGEN_TARGETS if target.supports_compat_check]
