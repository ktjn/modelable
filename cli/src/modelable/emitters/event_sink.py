from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from modelable.compiler.workspace import Workspace
from modelable.emitters.base import EmittedArtifact, compute_content_hash
from modelable.emitters.openapi_plan import emit_openapi_projection_plan
from modelable.parser.ir import ProjectionVersion
from modelable.planner.plans import build_plan_documents


def emit_event_sink(workspace: Workspace, out_dir: Path) -> list[EmittedArtifact]:
    """Emit the runtime-neutral contract consumed by event sinks and outboxes.

    This target describes the event envelope, event payload schemas, and the
    operation set for each event projection. It deliberately does not connect
    to a broker or database; adapters can use this single contract to publish
    events and materialize projections transactionally.
    """
    schemas: dict[str, dict[str, Any]] = {}
    events: list[dict[str, Any]] = []
    plans = {(plan["domain"], plan["projection"], plan["version"]): plan for plan in build_plan_documents(workspace)}
    for domain in sorted(workspace.mdl.domains, key=lambda item: item.name):
        for projection_name, versions in sorted(domain.projections.items()):
            if not projection_name.endswith("Event"):
                continue
            for version in sorted(versions, key=lambda item: item.version):
                schema_id = f"{domain.name}.{projection_name}.v{version.version}"
                plan = plans[(domain.name, projection_name, version.version)]
                schema = emit_openapi_projection_plan(plan, "event", schemas)
                schemas[schema_id] = schema
                model_name = _source_model_name(version)
                events.append(
                    {
                        "ref": f"{domain.name}.{projection_name}@{version.version}",
                        "domain": domain.name,
                        "model": model_name,
                        "version": version.version,
                        "channel": f"{domain.name}.{model_name}.events.v{version.version}",
                        "operations": _event_operations(version),
                        "payload_schema": {"$ref": f"#/components/schemas/{schema_id}"},
                    }
                )

    payload: dict[str, Any] = {
        "format": "modelable.event-sink.v1",
        "envelope": {
            "required": ["domain", "model", "version", "operation", "key", "timestamp", "payload"],
            "operations": ["insert", "update", "upsert", "delete", "snapshot"],
            "properties": {
                "domain": {"type": "string"},
                "model": {"type": "string"},
                "version": {"type": "integer", "minimum": 1},
                "operation": {"type": "string"},
                "key": {"type": "string"},
                "sequence": {"type": "string"},
                "timestamp": {"type": "string", "format": "date-time"},
                "payload": {"type": "object"},
            },
        },
        "outbox": {
            "delivery": "transactional",
            "deduplication_key": ["domain", "model", "version", "key", "sequence"],
            "status_fields": ["published_at", "attempts", "last_error"],
        },
        "events": events,
        "components": {"schemas": schemas},
    }
    content = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    return [
        EmittedArtifact(
            target="event-sink",
            ref="workspace#event-sink",
            artifact_id="event-sink",
            path=out_dir / "event-sink.json",
            content=content,
            content_hash=compute_content_hash(content),
        )
    ]


def _source_model_name(version: ProjectionVersion) -> str:
    return version.source.model.rsplit(".", 1)[-1]


def _event_operations(version: ProjectionVersion) -> list[str]:
    operations = version.event_operations or ["created", "updated", "deleted"]
    normalized = {"created": "insert", "updated": "update", "deleted": "delete"}
    return [normalized.get(operation, operation) for operation in operations]
