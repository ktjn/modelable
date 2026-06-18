from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

TargetStatus = Literal["implemented", "deferred"]
TargetKind = Literal["artifact", "language"]


@dataclass(frozen=True)
class CodegenTarget:
    name: str
    description: str
    status: TargetStatus
    kind: TargetKind
    default_out_dir: Path | None = None


CODEGEN_TARGETS: tuple[CodegenTarget, ...] = (
    CodegenTarget(
        name="json-schema",
        description="JSON Schema 2020-12 artifacts with x-modelable extensions",
        status="implemented",
        kind="artifact",
        default_out_dir=Path("./dist/jsonschema"),
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
    ),
    CodegenTarget(
        name="sql-clickhouse",
        description="ClickHouse CREATE TABLE DDL for projections",
        status="implemented",
        kind="artifact",
        default_out_dir=Path("./dist/sql/clickhouse"),
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
