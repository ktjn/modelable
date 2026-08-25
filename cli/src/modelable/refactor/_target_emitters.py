"""Shared dispatch table of every implemented codegen target's emitter
function, reused by A1's `extract_enum.py` and A2's `expand_version.py` /
`compact_version.py` for pre-write output validation (same emitter set as
`scripts/write_golden_artifacts.py`'s `TARGET_EMITTERS`, imported directly
from `modelable.emitters.*` rather than from the `scripts/` tree, which
isn't part of the installed package)."""

from __future__ import annotations

from modelable.emitters.avro import emit_avro
from modelable.emitters.csharp import emit_csharp
from modelable.emitters.dbt_yaml import emit_dbt_yaml
from modelable.emitters.event_sink import emit_event_sink
from modelable.emitters.go import emit_go
from modelable.emitters.grpc import emit_grpc
from modelable.emitters.java import emit_java
from modelable.emitters.json_schema import emit_json_schema
from modelable.emitters.markdown import emit_markdown
from modelable.emitters.odcs import emit_odcs
from modelable.emitters.openapi import emit_openapi
from modelable.emitters.openlineage import emit_openlineage
from modelable.emitters.openmetadata import emit_openmetadata
from modelable.emitters.protobuf import emit_protobuf
from modelable.emitters.python import emit_python
from modelable.emitters.registry_manifest import emit_registry_manifest
from modelable.emitters.rust import emit_rust
from modelable.emitters.sql import emit_sql
from modelable.emitters.typescript import emit_typescript

TARGET_EMITTERS: dict[str, object] = {
    "json-schema": emit_json_schema,
    "markdown": emit_markdown,
    "typescript": emit_typescript,
    "csharp": emit_csharp,
    "java": emit_java,
    "python": emit_python,
    "rust": emit_rust,
    "go": emit_go,
    "sql-postgres": lambda workspace, out_dir: emit_sql(workspace, out_dir, "postgres"),
    "sql-clickhouse": lambda workspace, out_dir: emit_sql(workspace, out_dir, "clickhouse"),
    "dbt-yaml": emit_dbt_yaml,
    "openmetadata": emit_openmetadata,
    "openlineage": emit_openlineage,
    "odcs": emit_odcs,
    "protobuf": emit_protobuf,
    "grpc": emit_grpc,
    "openapi": emit_openapi,
    "avro": emit_avro,
    "registry": emit_registry_manifest,
    "event-sink": emit_event_sink,
}
