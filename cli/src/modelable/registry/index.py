from __future__ import annotations

import json
import sqlite3
from importlib.resources import files
from pathlib import Path

from modelable.compiler.workspace import Workspace
from modelable.parser.ir import ComputedMapping, DirectMapping


def build_registry(workspace: Workspace, output_dir: str | Path = ".modelable") -> Path:
    """Write a rebuildable SQLite registry index for a validated workspace."""
    if workspace.errors:
        joined = "\n".join(f"{path}: {error}" for path, error in workspace.errors)
        raise ValueError(f"Cannot build registry with validation errors:\n{joined}")

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    registry_path = output_path / "registry.db"
    if registry_path.exists():
        registry_path.unlink()

    schema = files("modelable.registry").joinpath("schema.sql").read_text(encoding="utf-8")
    with sqlite3.connect(registry_path) as conn:
        conn.executescript(schema)
        _insert_workspace(conn, workspace)
        conn.commit()

    return registry_path


def _insert_workspace(conn: sqlite3.Connection, workspace: Workspace) -> None:
    source_paths = {
        id(domain): source.path
        for source in workspace.sources
        for domain in source.mdl.domains
    }

    for domain in workspace.mdl.domains:
        conn.execute(
            "insert into domains (name, owner, description) values (?, ?, ?)",
            (domain.name, domain.owner, domain.description),
        )

        for model_name, versions in domain.models.items():
            kind = versions[0].model_kind.value
            conn.execute(
                "insert into models (domain_name, name, kind) values (?, ?, ?)",
                (domain.name, model_name, kind),
            )
            for version in versions:
                conn.execute(
                    """
                    insert into model_versions
                    (domain_name, model_name, version, change_kind, source_path)
                    values (?, ?, ?, ?, ?)
                    """,
                    (
                        domain.name,
                        model_name,
                        version.version,
                        version.change_kind.value,
                        str(source_paths[id(domain)]),
                    ),
                )
                for position, field in enumerate(version.fields):
                    conn.execute(
                        """
                        insert into fields
                        (
                          domain_name, model_name, model_version, field_name,
                          position, type_json, optional, is_key, is_pii
                        )
                        values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            domain.name,
                            model_name,
                            version.version,
                            field.name,
                            position,
                            _to_json(field.type),
                            int(field.optional),
                            int(field.is_key),
                            int(field.is_pii),
                        ),
                    )

        for projection_name, versions in domain.projections.items():
            conn.execute(
                "insert into projections (domain_name, name) values (?, ?)",
                (domain.name, projection_name),
            )
            for version in versions:
                conn.execute(
                    """
                    insert into projection_versions
                    (
                      domain_name, projection_name, version, source_model,
                      source_version_json, source_alias
                    )
                    values (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        domain.name,
                        projection_name,
                        version.version,
                        version.source.model,
                        _to_json(version.source.version),
                        version.source.alias,
                    ),
                )
                conn.execute(
                    """
                    insert into projection_sources
                    (
                      domain_name, projection_name, projection_version,
                      source_kind, source_model, source_version_json, source_alias
                    )
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        domain.name,
                        projection_name,
                        version.version,
                        "primary",
                        version.source.model,
                        _to_json(version.source.version),
                        version.source.alias,
                    ),
                )
                for join in version.joins:
                    conn.execute(
                        """
                        insert into projection_sources
                        (
                          domain_name, projection_name, projection_version,
                          source_kind, source_model, source_version_json,
                          source_alias, join_on
                        )
                        values (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            domain.name,
                            projection_name,
                            version.version,
                            "join",
                            join.model,
                            _to_json(join.version),
                            join.alias,
                            join.on,
                        ),
                    )
                for position, field in enumerate(version.fields):
                    conn.execute(
                        """
                        insert into projection_fields
                        (
                          domain_name, projection_name, projection_version,
                          field_name, position, mapping_json, is_pii
                        )
                        values (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            domain.name,
                            projection_name,
                            version.version,
                            field.name,
                            position,
                            _to_json(field.mapping),
                            int(field.is_pii),
                        ),
                    )
                    _insert_field_mapping(
                        conn,
                        domain.name,
                        projection_name,
                        version.version,
                        field.name,
                        field.mapping,
                    )

    for binding in workspace.mdl.bindings:
        conn.execute(
            """
            insert into adapter_bindings (name, model_ref, adapter, table_name)
            values (?, ?, ?, ?)
            """,
            (
                binding.name,
                f"{binding.model}@{binding.model_version}",
                binding.adapter,
                binding.table,
            ),
        )


def _insert_field_mapping(
    conn: sqlite3.Connection,
    domain_name: str,
    projection_name: str,
    projection_version: int,
    target_field: str,
    mapping: DirectMapping | ComputedMapping,
) -> None:
    if isinstance(mapping, DirectMapping):
        conn.execute(
            """
            insert into field_mappings
            (
              domain_name, projection_name, projection_version, target_field,
              mapping_kind, source_alias, source_field
            )
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                domain_name,
                projection_name,
                projection_version,
                target_field,
                mapping.kind,
                mapping.source_alias,
                mapping.source_field,
            ),
        )
        return

    conn.execute(
        """
        insert into field_mappings
        (
          domain_name, projection_name, projection_version, target_field,
          mapping_kind, expression
        )
        values (?, ?, ?, ?, ?, ?)
        """,
        (
            domain_name,
            projection_name,
            projection_version,
            target_field,
            mapping.kind,
            mapping.expression,
        ),
    )


def _to_json(value) -> str:
    return json.dumps(value.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
