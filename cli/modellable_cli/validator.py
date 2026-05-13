"""Structural validation for Modellable YAML definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .loader import detect_doc_type
from .languages import VALID_ARTIFACT_FORMAT_IDS

VALID_FIELD_TYPES = {
    "string", "boolean", "integer", "decimal", "float",
    "timestamp", "date", "time", "duration", "uuid", "binary",
    "enum", "array", "object", "map", "reference",
}

VALID_CLASSIFICATIONS = {
    "public", "internal", "confidential", "pii", "sensitive", "restricted",
}

VALID_MODEL_KINDS = {"entity", "event", "value_object", "aggregate", "read_model", "cache", "replica"}

# Derived kinds require explicit provenance so their data origin is never ambiguous.
DERIVED_MODEL_KINDS = {"read_model", "cache", "replica"}

VALID_PROVENANCE_VIA = {
    "subscription", "cache", "api_call", "event", "cdc", "periodic_sync", "webhook",
}

VALID_SYNC_STRATEGIES = {"eventual", "strong", "periodic"}

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


def _validate_provenance(doc: dict[str, Any], base: str, errors: list, warnings: list) -> None:
    kind = doc.get("kind")
    prov = doc.get("provenance") or {}

    if kind in DERIVED_MODEL_KINDS and not prov:
        _err(errors, base, f"Kind '{kind}' requires a 'provenance' block declaring its data origin")
        return

    if not prov:
        return

    ppath = f"{base}.provenance"

    if kind == "replica":
        if not prov.get("sourceSystem"):
            _err(errors, ppath, "Kind 'replica' requires 'provenance.sourceSystem'")
    elif kind in ("read_model", "cache"):
        if not prov.get("sourceModel"):
            _err(errors, ppath, f"Kind '{kind}' requires 'provenance.sourceModel' (format: domain.Model.vN)")

    via = prov.get("via")
    if via and via not in VALID_PROVENANCE_VIA:
        _err(errors, ppath, f"Unknown 'via' value '{via}'. Must be one of: {', '.join(sorted(VALID_PROVENANCE_VIA))}")

    sync = prov.get("syncStrategy")
    if sync and sync not in VALID_SYNC_STRATEGIES:
        _err(errors, ppath, f"Unknown 'syncStrategy' '{sync}'. Must be one of: {', '.join(sorted(VALID_SYNC_STRATEGIES))}")

    if kind == "cache":
        if not prov.get("ttlSeconds") and not prov.get("cacheKey"):
            _warn(warnings, ppath, "Cache model should declare 'ttlSeconds' and/or 'cacheKey' for clarity")

    if not prov.get("system"):
        _warn(warnings, ppath, "Consider adding 'provenance.system' to identify which service owns this derived model")


def validate_model(doc: dict[str, Any], errors: list, warnings: list) -> None:
    name = f"{doc.get('domain', '?')}.{doc.get('model', '?')}.v{doc.get('version', '?')}"
    base = f"model:{name}"

    if not doc.get("kind"):
        _err(errors, base, "Missing required field 'kind' (entity|event|value_object|aggregate|read_model|cache|replica)")
    elif doc["kind"] not in VALID_MODEL_KINDS:
        _err(errors, base, f"Invalid 'kind' '{doc['kind']}'. Must be one of: {', '.join(sorted(VALID_MODEL_KINDS))}")
    else:
        _validate_provenance(doc, base, errors, warnings)

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

    artifacts = doc.get("artifacts", [])
    for i, artifact in enumerate(artifacts or []):
        apath = f"{base}.artifacts[{i}]"
        if not isinstance(artifact, dict):
            _err(errors, apath, "Artifact entry must be a mapping")
            continue
        fmt = artifact.get("format")
        if not fmt:
            _err(errors, apath, "Missing required field 'format'")
        elif fmt not in VALID_ARTIFACT_FORMAT_IDS:
            _err(
                errors,
                apath,
                f"Unknown artifact format '{fmt}'. "
                f"Run 'modellable codegen list' to see all supported formats.",
            )
        if not artifact.get("outputPath"):
            _warn(warnings, apath, "Missing 'outputPath' — recommended for artifact generation")


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
