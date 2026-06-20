from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from modelable.llm.render import render_model_version
from modelable.parser.ir import (
    AnnClassification,
    AnnKey,
    Annotation,
    AnnOwner,
    AnnPii,
    ArrayType,
    ChangeKind,
    DecimalType,
    DomainDef,
    EnumType,
    FieldDef,
    FieldType,
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


def import_from_text(
    source_text: str, source_format: str, *, domain_name: str | None = None, source_name: str | None = None
) -> ImportedModel:
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
    if source_format == "dbt":
        return _import_dbt(source_text, domain_name=domain_name, source_name=source_name)
    if source_format == "fhir":
        return _import_fhir(source_text, domain_name=domain_name, source_name=source_name)
    if source_format == "odcs":
        return _import_odcs(source_text, domain_name=domain_name, source_name=source_name)
    raise ValueError(f"Unsupported source format: {source_format}")


def import_from_path(
    path: str | Path, source_format: str, *, domain_name: str | None = None, source_name: str | None = None
) -> ImportedModel:
    return import_from_text(
        Path(path).read_text(encoding="utf-8"), source_format, domain_name=domain_name, source_name=source_name
    )


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


def _import_dbt(source_text: str, *, domain_name: str | None, source_name: str | None = None) -> ImportedModel:
    stripped = source_text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            doc = json.loads(stripped)
            if "nodes" in doc:
                return _import_dbt_manifest(doc, domain_name=domain_name, source_name=source_name)
        except json.JSONDecodeError:
            pass

    doc = yaml.safe_load(source_text) or {}
    models = doc.get("models") or []
    if not models:
        return _import_dbt_source_yaml(doc, domain_name=domain_name, source_name=source_name)
    if source_name is not None:
        model = next((item for item in models if item.get("name") == source_name), None)
        if model is None:
            raise ValueError(f"dbt model '{source_name}' not found in source")
    else:
        model = models[0]
    name = model.get("name") or "DbtModel"
    domain = domain_name or _guess_domain_name(name)
    warnings: list[str] = []
    fields = _fields_from_dbt_columns(model.get("columns") or [], warnings)
    version = ModelVersion(model_kind=ModelKind.entity, version=1, change_kind=ChangeKind.additive, fields=fields)
    return ImportedModel("dbt", name, domain, _sanitize_ident(name), version, warnings)


def _import_dbt_source_yaml(
    doc: dict[str, Any], *, domain_name: str | None, source_name: str | None = None
) -> ImportedModel:
    sources = doc.get("sources") or []
    tables: list[dict[str, Any]] = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        for table in source.get("tables") or []:
            if isinstance(table, dict):
                tables.append(table)
    if not tables:
        raise ValueError("dbt schema document does not declare any models or source tables")

    if source_name is not None:
        table = next((item for item in tables if item.get("name") == source_name), None)
        if table is None:
            raise ValueError(f"dbt source table '{source_name}' not found in source")
    else:
        table = tables[0]

    name = table.get("name") or "DbtSource"
    domain = domain_name or _guess_domain_name(name)
    warnings: list[str] = []
    fields = _fields_from_dbt_columns(table.get("columns") or [], warnings)

    version = ModelVersion(model_kind=ModelKind.entity, version=1, change_kind=ChangeKind.additive, fields=fields)
    return ImportedModel("dbt", name, domain, _sanitize_ident(name), version, warnings)


def _import_dbt_manifest(
    doc: dict[str, Any], *, domain_name: str | None, source_name: str | None = None
) -> ImportedModel:
    nodes = doc.get("nodes") or {}
    models = {node["name"]: node for node in nodes.values() if node.get("resource_type") == "model" and "name" in node}
    sources_doc = doc.get("sources") or {}
    sources = {
        source["name"]: source
        for source in sources_doc.values()
        if source.get("resource_type") == "source" and "name" in source
    }
    if not models and not sources:
        raise ValueError("dbt manifest does not declare any models or source tables")

    if source_name is not None:
        model = models.get(source_name)
        source = sources.get(source_name) if model is None else None
        if model is None and source is None:
            raise ValueError(f"dbt model or source table '{source_name}' not found in manifest")
    else:
        model = models[sorted(models.keys())[0]] if models else None
        source = sources[sorted(sources.keys())[0]] if model is None else None

    selected = model or source
    name = selected["name"]
    domain = domain_name or _guess_domain_name(name)
    warnings: list[str] = []
    fields = _fields_from_dbt_columns(selected.get("columns") or {}, warnings)

    version = ModelVersion(model_kind=ModelKind.entity, version=1, change_kind=ChangeKind.additive, fields=fields)
    return ImportedModel("dbt", name, domain, _sanitize_ident(name), version, warnings)


def _fields_from_dbt_columns(columns: Any, warnings: list[str]) -> list[FieldDef]:
    fields: list[FieldDef] = []
    column_items = columns.items() if isinstance(columns, dict) else ((None, column) for column in columns)
    for column_name, column in column_items:
        if not isinstance(column, dict):
            continue
        if "name" not in column and column_name is not None:
            column = {"name": column_name, **column}
        fields.append(_field_from_dbt_column(column, warnings))
    return fields


def _field_from_dbt_column(column: dict[str, Any], warnings: list[str]) -> FieldDef:
    name = column["name"]
    data_type = column.get("data_type")
    field_type: FieldType
    if data_type:
        field_type = _sql_type_to_field_type(data_type)
    else:
        warnings.append(f"Column '{name}' has no data_type; defaulting to string")
        field_type = PrimitiveType(kind="string")

    constraint_types = {
        constraint.get("type") for constraint in column.get("constraints") or [] if isinstance(constraint, dict)
    }
    annotations: list[Annotation] = []
    if "primary_key" in constraint_types:
        annotations.append(AnnKey())
    optional = "not_null" not in constraint_types and "primary_key" not in constraint_types

    meta = column.get("meta") or {}
    if meta.get("modelable_pii"):
        annotations.append(AnnPii())
    classification = meta.get("modelable_classification")
    if classification:
        annotations.append(AnnClassification(level=str(classification)))
    owner = meta.get("modelable_owner")
    if owner:
        annotations.append(AnnOwner(team=str(owner)))

    return FieldDef(name=name, type=field_type, optional=optional, annotations=annotations)


_FHIR_PRIMITIVE_TYPES = {
    "string": "string",
    "code": "string",
    "id": "string",
    "markdown": "string",
    "uri": "string",
    "url": "string",
    "canonical": "string",
    "oid": "string",
    "boolean": "bool",
    "integer": "int",
    "integer64": "int",
    "positiveInt": "int",
    "unsignedInt": "int",
    "decimal": "float",
    "dateTime": "timestamp",
    "instant": "timestamp",
    "date": "date",
    "time": "time",
    "base64Binary": "binary",
}


def _import_fhir(source_text: str, *, domain_name: str | None, source_name: str | None = None) -> ImportedModel:
    doc = json.loads(source_text)
    if doc.get("resourceType") != "StructureDefinition":
        raise ValueError("FHIR source must be a StructureDefinition resource")
    resource_type = doc.get("type") or doc.get("name") or "FhirResource"
    name = doc.get("name") or resource_type
    domain = domain_name or _guess_domain_name(resource_type)

    elements = (doc.get("snapshot") or {}).get("element") or (doc.get("differential") or {}).get("element") or []
    fields: list[FieldDef] = []
    warnings: list[str] = []
    for element in elements:
        path = element.get("path", "")
        segments = path.split(".")
        if len(segments) != 2:
            continue
        field_name = segments[1]
        if field_name == "extension" and element.get("sliceName"):
            field_name = _sanitize_field_ident(str(element["sliceName"]))
            warnings.append(f"Extension slice '{path}' imported as field '{field_name}'")
        if field_name.endswith("[x]"):
            field_name = field_name[: -len("[x]")]
            warnings.append(f"Choice-type element '{path}' flattened to '{field_name}'")
        fields.append(_field_from_fhir_element(field_name, element, warnings))

    version = ModelVersion(model_kind=ModelKind.entity, version=1, change_kind=ChangeKind.additive, fields=fields)
    return ImportedModel("fhir", name, domain, _sanitize_ident(resource_type), version, warnings)


def _import_odcs(source_text: str, *, domain_name: str | None, source_name: str | None = None) -> ImportedModel:
    doc = yaml.safe_load(source_text) or {}
    schema = doc.get("schema") or doc.get("schemas") or []
    if isinstance(schema, dict):
        schema = schema.get("objects") or schema.get("tables") or [schema]
    if not isinstance(schema, list) or not schema:
        raise ValueError("ODCS document does not declare a schema")

    if source_name is not None:
        item = next((entry for entry in schema if isinstance(entry, dict) and entry.get("name") == source_name), None)
        if item is None:
            raise ValueError(f"ODCS schema '{source_name}' not found in source")
    else:
        item = next((entry for entry in schema if isinstance(entry, dict)), None)
    if not isinstance(item, dict):
        raise ValueError("ODCS schema does not contain a supported object")

    name = str(item.get("name") or item.get("physicalName") or "OdcsModel")
    domain = domain_name or _guess_domain_name(name)
    properties = item.get("properties") or item.get("fields") or item.get("columns") or []
    if isinstance(properties, dict):
        properties = [
            {"name": key, **value} if isinstance(value, dict) else {"name": key} for key, value in properties.items()
        ]

    fields: list[FieldDef] = []
    warnings: list[str] = []
    for prop in properties:
        if not isinstance(prop, dict) or not prop.get("name"):
            warnings.append(f"Skipped unsupported ODCS property: {prop}")
            continue
        fields.append(_field_from_odcs_property(prop, warnings))

    version = ModelVersion(model_kind=ModelKind.entity, version=1, change_kind=ChangeKind.additive, fields=fields)
    return ImportedModel("odcs", name, domain, _sanitize_ident(name), version, warnings)


def _field_from_odcs_property(prop: dict[str, Any], warnings: list[str]) -> FieldDef:
    name = str(prop["name"])
    type_name = str(
        prop.get("logicalType")
        or prop.get("physicalType")
        or prop.get("type")
        or prop.get("dataType")
        or prop.get("classification")
        or "string"
    )
    annotations: list[Annotation] = []
    if prop.get("primaryKey") or prop.get("primary_key") or prop.get("key"):
        annotations.append(AnnKey())
    if prop.get("pii") or prop.get("personalData"):
        annotations.append(AnnPii())
    classification = prop.get("modelable_classification") or prop.get("classificationLevel")
    if classification and str(classification).lower() not in {"string", "number", "integer", "boolean"}:
        annotations.append(AnnClassification(level=str(classification)))
    owner = prop.get("owner")
    if owner:
        annotations.append(AnnOwner(team=str(owner)))
    optional = not bool(prop.get("required") or (annotations and any(isinstance(ann, AnnKey) for ann in annotations)))
    return FieldDef(
        name=name, type=_odcs_type_to_field_type(type_name, warnings), optional=optional, annotations=annotations
    )


def _odcs_type_to_field_type(type_name: str, warnings: list[str]) -> FieldType:
    normalized = type_name.strip().lower()
    if normalized in {"string", "text", "varchar"}:
        return PrimitiveType(kind="string")
    if normalized in {"integer", "int", "long", "bigint"}:
        return PrimitiveType(kind="int")
    if normalized in {"number", "float", "double"}:
        return PrimitiveType(kind="float")
    if normalized in {"boolean", "bool"}:
        return PrimitiveType(kind="bool")
    if normalized in {"date", "time", "timestamp", "uuid", "binary"}:
        return PrimitiveType(kind=normalized)
    warnings.append(f"Falling back to named type for ODCS type: {type_name}")
    return NamedType(name=_sanitize_ident(type_name))


def _field_from_fhir_element(field_name: str, element: dict[str, Any], warnings: list[str]) -> FieldDef:
    path = element.get("path", field_name)
    types = element.get("type") or []
    field_type: FieldType
    if not types:
        warnings.append(f"Element '{path}' has no declared type; defaulting to string")
        field_type = PrimitiveType(kind="string")
    else:
        if len(types) > 1:
            codes = ", ".join(str(item.get("code", "?")) for item in types)
            warnings.append(f"Element '{path}' has multiple types ({codes}); using the first")
        field_type = _fhir_type_to_field_type(types[0], path, warnings)
    max_cardinality = str(element.get("max", "1"))
    if max_cardinality == "*" or (max_cardinality.isdigit() and int(max_cardinality) > 1):
        field_type = ArrayType(item=field_type)

    binding = element.get("binding") or {}
    if binding.get("strength") == "required" and binding.get("valueSet"):
        warnings.append(
            f"Element '{path}' has a required binding to {binding['valueSet']}; "
            "represent as enum(...) manually if a fixed value set is known"
        )

    optional = element.get("min", 0) == 0
    annotations: list[Annotation] = []
    if field_name == "id":
        annotations.append(AnnKey())
    return FieldDef(name=field_name, type=field_type, optional=optional, annotations=annotations)


def _fhir_type_to_field_type(type_entry: dict[str, Any], path: str, warnings: list[str]) -> FieldType:
    code = type_entry.get("code", "")
    if code in _FHIR_PRIMITIVE_TYPES:
        return PrimitiveType(kind=_FHIR_PRIMITIVE_TYPES[code])
    if code == "Reference":
        targets = type_entry.get("targetProfile") or []
        if targets:
            return RefType(target=str(targets[0]).rsplit("/", 1)[-1])
        warnings.append(f"Element '{path}' is an untyped Reference; falling back to named type")
        return NamedType(name="Reference")
    if code == "Extension":
        profiles = type_entry.get("profile") or []
        if profiles:
            warnings.append(f"Element '{path}' uses FHIR Extension profile {profiles[0]}; review manually")
        return NamedType(name="Extension")
    warnings.append(f"Element '{path}' has unsupported FHIR type '{code}'; falling back to named type")
    return NamedType(name=code or "Unknown")


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


def _sanitize_field_ident(text: str) -> str:
    ident = _sanitize_ident(text)
    return ident[:1].lower() + ident[1:]
