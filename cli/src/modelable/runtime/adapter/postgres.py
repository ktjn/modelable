from __future__ import annotations

from typing import Any

import psycopg

from modelable.parser.ir import DecimalType, EnumType, FieldType, PrimitiveType

from .base import RuntimeAdapter


def type_to_postgres(field_type: FieldType) -> str:
    # ... (rest of implementation)
    mapping = {
        "string": "TEXT",
        "int": "INTEGER",
        "float": "DOUBLE PRECISION",
        "bool": "BOOLEAN",
        "date": "DATE",
        "time": "TIME",
        "timestamp": "TIMESTAMP",
        "uuid": "UUID",
        "duration": "INTERVAL",
        "binary": "BYTEA",
    }
    if isinstance(field_type, PrimitiveType):
        return mapping.get(field_type.kind, "TEXT")
    if isinstance(field_type, DecimalType):
        return f"NUMERIC({field_type.precision}, {field_type.scale})"
    if isinstance(field_type, EnumType):
        return "TEXT"
    return "TEXT"

class PostgresAdapter(RuntimeAdapter):
    """PostgreSQL runtime adapter."""

    def bootstrap(self, config: dict[str, Any]) -> None:
        """Initialize the PostgreSQL environment."""
        conn_str = config["connection_string"]
        with psycopg.connect(conn_str) as conn, conn.cursor() as cur:
            # Example: create a schema if configured
            schema = config.get("schema", "public")
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
            conn.commit()

    def materialize(self, projection_plan: dict[str, Any], data: Any) -> None:
        """Stream or update data into the target materialization."""
        # This implementation assumes data is a list of dictionaries where keys match projection field names
        # and projection_plan contains 'table_name' and 'keys'.
        table_name = projection_plan["table_name"]
        keys = projection_plan["keys"]
        conn_str = projection_plan["connection_string"]

        with psycopg.connect(conn_str) as conn, conn.cursor() as cur:
            for record in data:
                columns = record.keys()
                values = [record[col] for col in columns]
                
                # Construct UPSERT
                col_names = ", ".join(columns)
                placeholders = ", ".join(["%s"] * len(columns))
                update_stmt = ", ".join([f"{col} = EXCLUDED.{col}" for col in columns if col not in keys])
                
                query = f"""
                        INSERT INTO {table_name} ({col_names})
                        VALUES ({placeholders})
                        ON CONFLICT ({', '.join(keys)})
                        DO UPDATE SET {update_stmt};
                    """
                
                cur.execute(query, values)
            conn.commit()

    def generate_table_ddl(self, table_name: str, fields: list[Any]) -> str:
        """Generate DDL for a projection table."""
        columns = []
        for field in fields:
            pg_type = type_to_postgres(field.type)
            columns.append(f"{field.name} {pg_type}")
        
        return f"CREATE TABLE IF NOT EXISTS {table_name} (\n  {', '.join(columns)}\n);"
