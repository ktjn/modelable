from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from modelable.llm.render import render_model_version
from modelable.parser.ir import (
    AnnKey,
    AnnPii,
    ArrayType,
    ChangeKind,
    DecimalType,
    DomainDef,
    EnumType,
    FieldDef,
    MdlFile,
    ModelKind,
    ModelVersion,
    NamedType,
    ObjectType,
    PrimitiveType,
    RefType,
)


@dataclass(frozen=True)
class ImportedModel:
    source_format: str
    source_name: str
    domain_name: str
    model_name: str
    model_version: ModelVersion
    warnings: list[str] = field(default_factory=list)

    def to_mdl(self) -> str:
        return render_model_version(self.domain_name, self.model_name, self.model_version, owner="imported")

    def to_workspace(self) -> MdlFile:
        return MdlFile(domains=[DomainDef(name=self.domain_name, models={self.model_name: [self.model_version]})])


def import_from_text(source_text: str, source_format: str, *, domain_name: str | None = None) -> ImportedModel:
    source_format = source_format.lower()
    if source_format == "json-schema":
        return _import_json_schema(source_text, domain_name=domain_name)
    if source_format == "openapi":
        return _import_openapi(source_text, domain_name=domain_name)
    if source_format == "avro":
        return _import_avro(source_text, domain_name=domain_name)
    if source_format == "protobuf":
        return _import_protobuf(source_text, domain_name=domain_name)
    if source_format in {"sql", "ddl"}:
        return _import_sql(source_text, domain_name=domain_name)
    raise ValueError(f"Unsupported source format: {source_format}")


def import_from_path(path: str | Path, source_format: str, *, domain_name: str | None = None) -> ImportedModel:
    return import_from_text(Path(path).read_text(encoding="utf-8"), source_format, domain_name=domain_name)


def _import_json_schema(source_text: str, *, domain_name: str | None) -> ImportedModel:
    schema = json.loads(source_text)
    title = schema.get("title") or "ImportedModel"
    domain = domain_name or _guess_domain_name(title)
    model_name = _sanitize_ident(title)
    fields, warnings = _fields_from_json_schema(schema)
    version = ModelVersion(model_kind=ModelKind.entity, version=1, change_kind=ChangeKind.additive, fields=fields)
    return ImportedModel("json-schema", title, domain, model_name, version, warnings)


def _import_openapi(source_text: str, *, domain_name: str | None) -> ImportedModel:
    doc = json.loads(source_text)
    schema = doc.get("components", {}).get("schemas", {})
    if schema:
        name, payload = next(iter(schema.items()))
    else:
        name, payload = "OpenApiModel", doc
    domain = domain_name or _guess_domain_name(name)
    model_name = _sanitize_ident(name)
    fields, warnings = _fields_from_json_schema(payload)
    version = ModelVersion(model_kind=ModelKind.entity, version=1, change_kind=ChangeKind.additive, fields=fields)
    return ImportedModel("openapi", name, domain, model_name, version, warnings)


def _import_avro(source_text: str, *, domain_name: str | None) -> ImportedModel:
    doc = json.loads(source_text)
    name = doc.get("name") or doc.get("type") or "AvroRecord"
    domain = domain_name or _guess_domain_name(name)
    fields: list[FieldDef] = []
    warnings: list[str] = []
    for item in doc.get("fields", []):
        fields.append(_field_from_avro(item, warnings))
    version = ModelVersion(model_kind=ModelKind.entity, version=1, change_kind=ChangeKind.additive, fields=fields)
    return ImportedModel("avro", name, domain, _sanitize_ident(name), version, warnings)


def _import_protobuf(source_text: str, *, domain_name: str | None) -> ImportedModel:
    message_match = re.search(r"message\s+([A-Za-z_][A-Za-z0-9_]*)\s*\{(?P<body>.*?)\}", source_text, re.DOTALL)
    name = message_match.group(1) if message_match else "ProtoMessage"
    body = message_match.group("body") if message_match else source_text
    domain = domain_name or _guess_domain_name(name)
    fields: list[FieldDef] = []
    warnings: list[str] = []
    for line in body.splitlines():
        line = line.strip().rstrip(";")
        if not line or line.startswith("//"):
            continue
        match = re.match(
            r"(optional|required|repeated)?\s*([A-Za-z_][A-Za-z0-9_<>,.]*)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\d+", line
        )
        if not match:
            warnings.append(f"Skipped unsupported protobuf line: {line}")
            continue
        label, type_name, field_name = match.groups()
        field = FieldDef(name=field_name, type=_primitive_or_named_type(type_name), optional=label == "optional")
        fields.append(field)
    version = ModelVersion(model_kind=ModelKind.entity, version=1, change_kind=ChangeKind.additive, fields=fields)
    return ImportedModel("protobuf", name, domain, _sanitize_ident(name), version, warnings)


def _import_sql(source_text: str, *, domain_name: str | None) -> ImportedModel:
    match = re.search(
        r"create\s+table\s+([A-Za-z_][A-Za-z0-9_\.]*)\s*\((?P<body>.*?)\)\s*;?", source_text, re.IGNORECASE | re.DOTALL
    )
    table_name = match.group(1) if match else "ImportedTable"
    body = match.group("body") if match else source_text
    domain = domain_name or _guess_domain_name(table_name)
    fields: list[FieldDef] = []
    warnings: list[str] = []
    primary_key: set[str] = set()
    for chunk in _split_sql_columns(body):
        lower = chunk.lower()
        if lower.startswith("primary key"):
            primary_key.update(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", chunk))
            continue
        parts = chunk.split()
        if len(parts) < 2:
            warnings.append(f"Skipped unsupported SQL column: {chunk}")
            continue
        field_name = parts[0]
        type_tokens: list[str] = []
        for token in parts[1:]:
            if token.upper() in {
                "NOT",
                "NULL",
                "PRIMARY",
                "KEY",
                "DEFAULT",
                "REFERENCES",
                "CONSTRAINT",
                "UNIQUE",
                "CHECK",
            }:
                break
            type_tokens.append(token)
        type_name = " ".join(type_tokens) if type_tokens else parts[1]
        optional = "NOT NULL" not in chunk.upper()
        field = FieldDef(name=field_name, type=_sql_type_to_field_type(type_name), optional=optional)
        fields.append(field)
    for field in fields:
        if field.name in primary_key:
            field.annotations.append(AnnKey())
            field.optional = False
    version = ModelVersion(model_kind=ModelKind.entity, version=1, change_kind=ChangeKind.additive, fields=fields)
    return ImportedModel("sql", table_name, domain, _sanitize_ident(_basename_name(table_name)), version, warnings)


def _fields_from_json_schema(schema: dict) -> tuple[list[FieldDef], list[str]]:
    warnings: list[str] = []
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    key_field_name = next(
        (name for name in properties if name in required and (name.lower() == "id" or name.lower().endswith("id"))),
        None,
    )
    fields: list[FieldDef] = []
    for name, prop in properties.items():
        field_type = _field_type_from_json_schema(prop, warnings)
        annotations: list = []
        if name == key_field_name or name in schema.get("x-modelable-key-fields", []):
            annotations.append(AnnKey())
        if prop.get("x-modelable-field", {}).get("pii"):
            annotations.append(AnnPii())
        fields.append(
            FieldDef(
                name=name,
                type=field_type,
                optional=name not in required,
                annotations=annotations,
            )
        )
    return fields, warnings


def _field_type_from_json_schema(prop: dict, warnings: list[str]):
    if "enum" in prop:
        return EnumType(values=[str(item) for item in prop["enum"]])
    if prop.get("type") == "array":
        return ArrayType(item=_field_type_from_json_schema(prop.get("items", {}), warnings))
    if prop.get("type") == "object" and "properties" in prop:
        return ObjectType(
            fields=[
                FieldDef(
                    name=name,
                    type=_field_type_from_json_schema(child, warnings),
                    optional=name not in set(prop.get("required", [])),
                )
                for name, child in prop["properties"].items()
            ]
        )
    if prop.get("x-modelable-ref"):
        return RefType(target=str(prop["x-modelable-ref"]))
    if prop.get("type") == "integer":
        return PrimitiveType(kind="int")
    if prop.get("type") == "number":
        return PrimitiveType(kind="float")
    if prop.get("type") == "boolean":
        return PrimitiveType(kind="bool")
    if prop.get("type") == "string":
        fmt = prop.get("format")
        if fmt == "date-time":
            return PrimitiveType(kind="timestamp")
        if fmt == "date":
            return PrimitiveType(kind="date")
        if fmt == "time":
            return PrimitiveType(kind="time")
        if fmt == "uuid":
            return PrimitiveType(kind="uuid")
        return PrimitiveType(kind="string")
    if prop.get("type") == "object" and prop.get("additionalProperties"):
        return ObjectType(fields=[])
    warnings.append(f"Falling back to named type for schema fragment: {prop}")
    return NamedType(name=prop.get("title") or "Unknown")


def _field_from_avro(item: dict, warnings: list[str]) -> FieldDef:
    name = item["name"]
    field_type = item.get("type")
    optional = False
    if isinstance(field_type, list) and "null" in field_type:
        optional = True
        field_type = next((entry for entry in field_type if entry != "null"), "string")
    return FieldDef(name=name, type=_avro_type_to_field_type(field_type, warnings), optional=optional)


def _avro_type_to_field_type(field_type, warnings: list[str]):
    if isinstance(field_type, dict):
        kind = field_type.get("type")
        if kind == "record":
            return ObjectType(fields=[_field_from_avro(child, warnings) for child in field_type.get("fields", [])])
        if kind == "enum":
            return EnumType(values=[str(value) for value in field_type.get("symbols", [])])
    if field_type == "string":
        return PrimitiveType(kind="string")
    if field_type == "bytes":
        return PrimitiveType(kind="binary")
    if field_type == "int" or field_type == "long":
        return PrimitiveType(kind="int")
    if field_type == "float" or field_type == "double":
        return PrimitiveType(kind="float")
    if field_type == "boolean":
        return PrimitiveType(kind="bool")
    warnings.append(f"Falling back to named type for Avro field type: {field_type}")
    return NamedType(name=str(field_type))


def _sql_type_to_field_type(type_name: str):
    normalized = type_name.strip().lower()
    if normalized.startswith("varchar") or normalized in {"text", "char", "character varying"}:
        return PrimitiveType(kind="string")
    if normalized in {"int", "integer", "bigint", "smallint"}:
        return PrimitiveType(kind="int")
    if normalized in {"float", "double", "real", "numeric", "decimal"} or normalized.startswith("decimal"):
        match = re.search(r"\((\d+)\s*,\s*(\d+)\)", normalized)
        if match:
            return DecimalType(precision=int(match.group(1)), scale=int(match.group(2)))
        return PrimitiveType(kind="float")
    if normalized in {"bool", "boolean"}:
        return PrimitiveType(kind="bool")
    if normalized in {"timestamp", "timestamptz", "datetime"}:
        return PrimitiveType(kind="timestamp")
    if normalized == "date":
        return PrimitiveType(kind="date")
    if normalized == "time":
        return PrimitiveType(kind="time")
    if normalized == "uuid":
        return PrimitiveType(kind="uuid")
    return NamedType(name=_sanitize_ident(type_name))


def _split_sql_columns(body: str) -> list[str]:
    chunks: list[str] = []
    current = []
    depth = 0
    for char in body:
        if char == "," and depth == 0:
            chunk = "".join(current).strip()
            if chunk:
                chunks.append(chunk)
            current = []
            continue
        if char == "(":
            depth += 1
        elif char == ")" and depth > 0:
            depth -= 1
        current.append(char)
    chunk = "".join(current).strip()
    if chunk:
        chunks.append(chunk)
    return chunks


def _primitive_or_named_type(type_name: str):
    normalized = type_name.lower()
    if normalized in {"string", "bytes"}:
        return PrimitiveType(kind="string" if normalized == "string" else "binary")
    if normalized in {"int32", "int64", "uint32", "uint64", "sint32", "sint64", "fixed32", "fixed64"}:
        return PrimitiveType(kind="int")
    if normalized in {"double", "float"}:
        return PrimitiveType(kind="float")
    if normalized == "bool":
        return PrimitiveType(kind="bool")
    return NamedType(name=_sanitize_ident(type_name))


def _guess_domain_name(text: str) -> str:
    return _sanitize_ident(_basename_name(text).replace("-", "_").lower())


def _basename_name(text: str) -> str:
    return text.rsplit(".", 1)[-1]


def _sanitize_ident(text: str) -> str:
    parts = re.split(r"[^A-Za-z0-9]+", text)
    cleaned = "".join(part[:1].upper() + part[1:] for part in parts if part)
    return cleaned or "ImportedModel"
