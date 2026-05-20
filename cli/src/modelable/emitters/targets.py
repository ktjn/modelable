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
        description="Deferred first-class C# generated-language target",
        status="deferred",
        kind="language",
    ),
    CodegenTarget(
        name="java",
        description="Deferred first-class Java generated-language target",
        status="deferred",
        kind="language",
    ),
    CodegenTarget(
        name="python",
        description="Deferred first-class Python generated-language target",
        status="deferred",
        kind="language",
    ),
    CodegenTarget(
        name="rust",
        description="Deferred first-class Rust generated-language target",
        status="deferred",
        kind="language",
    ),
    CodegenTarget(
        name="go",
        description="Deferred first-class Go generated-language target",
        status="deferred",
        kind="language",
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
