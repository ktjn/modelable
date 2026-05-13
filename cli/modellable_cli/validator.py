"""Structural validation for Modellable YAML definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .loader import detect_doc_type

VALID_FIELD_TYPES = {
    "string", "boolean", "integer", "decimal", "float",
    "timestamp", "date", "time", "duration", "uuid", "binary",
    "enum", "array", "object", "map", "reference",
}

VALID_CLASSIFICATIONS = {
    "public", "internal", "confidential", "pii", "sensitive", "restricted",
}

VALID_MODEL_KINDS = {"entity", "event", "value_object", "aggregate"}

VALID_STATUSES = {"draft", "published", "deprecated", "retired"}

VALID_MATERIALISATION_STRATEGIES = {
    "append", "upsert", "snapshot", "overwrite_partition",
}


@dataclass
class ValidationError:
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


@dataclass
class ValidationResult:
    file: str
    errors: list[ValidationError] = field(default_factory=list)
    warnings: list[ValidationError] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0


def _err(errors: list[ValidationError], path: str, msg: str) -> None:
    errors.append(ValidationError(path, msg))


def _warn(warnings: list[ValidationError], path: str, msg: str) -> None:
    warnings.append(ValidationError(path, msg))


def validate_domain(doc: dict[str, Any], errors: list, warnings: list) -> None:
    base = f"domain:{doc.get('domain', '?')}"
    if not doc.get("owner"):
        _err(errors, base, "Missing required field 'owner'")
    if not doc.get("description"):
        _warn(warnings, base, "Missing 'description' — consider adding one for lineage documentation")


def validate_model(doc: dict[str, Any], errors: list, warnings: list) -> None:
    name = f"{doc.get('domain', '?')}.{doc.get('model', '?')}.v{doc.get('version', '?')}"
    base = f"model:{name}"

    if not doc.get("kind"):
        _err(errors, base, "Missing required field 'kind' (entity|event|value_object|aggregate)")
    elif doc["kind"] not in VALID_MODEL_KINDS:
        _err(errors, base, f"Invalid 'kind' '{doc['kind']}'. Must be one of: {', '.join(sorted(VALID_MODEL_KINDS))}")

    if not doc.get("version"):
        _err(errors, base, "Missing required field 'version'")

    status = doc.get("status")
    if status and status not in VALID_STATUSES:
        _err(errors, base, f"Invalid 'status' '{status}'. Must be one of: {', '.join(sorted(VALID_STATUSES))}")

    fields = doc.get("fields", {})
    if not fields:
        _warn(warnings, base, "Model has no fields defined")

    for fname, fdef in (fields or {}).items():
        fpath = f"{base}.fields.{fname}"
        if not isinstance(fdef, dict):
            _err(errors, fpath, "Field definition must be a mapping")
            continue
        ftype = fdef.get("type")
        if not ftype:
            _err(errors, fpath, "Missing required field type")
        elif ftype not in VALID_FIELD_TYPES:
            _err(errors, fpath, f"Unknown type '{ftype}'. Must be one of: {', '.join(sorted(VALID_FIELD_TYPES))}")
        cls = fdef.get("classification")
        if cls and cls not in VALID_CLASSIFICATIONS:
            _err(errors, fpath, f"Unknown classification '{cls}'. Must be one of: {', '.join(sorted(VALID_CLASSIFICATIONS))}")
        if ftype == "enum" and not fdef.get("values"):
            _err(errors, fpath, "Enum field requires 'values' list")


def validate_projection(doc: dict[str, Any], errors: list, warnings: list) -> None:
    name = f"{doc.get('domain', '?')}.{doc.get('projection', '?')}.v{doc.get('version', '?')}"
    base = f"projection:{name}"

    if not doc.get("version"):
        _err(errors, base, "Missing required field 'version'")

    sources = doc.get("sources", [])
    if not sources:
        _err(errors, base, "Missing 'sources' — projection must declare at least one source model")

    for i, src in enumerate(sources):
        spath = f"{base}.sources[{i}]"
        if not src.get("domain"):
            _err(errors, spath, "Missing 'domain'")
        if not src.get("model"):
            _err(errors, spath, "Missing 'model'")
        if not src.get("version"):
            _warn(warnings, spath, "Missing 'version' — pin to a specific version for stable contracts")

    fields = doc.get("fields", {})
    if not fields:
        _warn(warnings, base, "Projection has no fields defined")

    for fname, fdef in (fields or {}).items():
        fpath = f"{base}.fields.{fname}"
        if not isinstance(fdef, dict):
            _err(errors, fpath, "Field definition must be a mapping")
            continue
        has_from = "from" in fdef
        has_expr = "expression" in fdef
        if not has_from and not has_expr:
            _err(errors, fpath, "Field must have either 'from' or 'expression'")
        if has_from and has_expr:
            _err(errors, fpath, "Field cannot have both 'from' and 'expression'")
        cls = fdef.get("classification")
        if cls and cls not in VALID_CLASSIFICATIONS:
            _err(errors, fpath, f"Unknown classification '{cls}'")

    mat = doc.get("materialisation", {})
    if mat:
        strategy = mat.get("strategy")
        if strategy and strategy not in VALID_MATERIALISATION_STRATEGIES:
            _err(errors, f"{base}.materialisation", f"Unknown strategy '{strategy}'")


def validate_binding(doc: dict[str, Any], errors: list, warnings: list) -> None:
    name = doc.get("binding", "?")
    base = f"binding:{name}"
    if not doc.get("adapter"):
        _err(errors, base, "Missing required field 'adapter'")
    if not doc.get("role"):
        _warn(warnings, base, "Missing 'role' (sink|stream|source) — recommended for clarity")


def validate_document(
    doc: dict[str, Any],
    errors: list[ValidationError],
    warnings: list[ValidationError],
) -> None:
    dtype = detect_doc_type(doc)
    if dtype == "domain":
        validate_domain(doc, errors, warnings)
    elif dtype == "model":
        validate_model(doc, errors, warnings)
    elif dtype == "projection":
        validate_projection(doc, errors, warnings)
    elif dtype == "binding":
        validate_binding(doc, errors, warnings)
    elif dtype == "scenario":
        if not doc.get("title"):
            warnings.append(ValidationError(f"scenario:{doc.get('scenario', '?')}", "Missing 'title'"))
    # unknown documents are silently skipped


def validate_file(file_path: str, docs: list[dict[str, Any]]) -> ValidationResult:
    result = ValidationResult(file=file_path)
    for doc in docs:
        validate_document(doc, result.errors, result.warnings)
    return result
