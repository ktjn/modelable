from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from modelable.compiler.workspace import load_workspace
from modelable.emitters.json_schema import emit_json_schema
from modelable.emitters.markdown import emit_markdown
from modelable.emitters.typescript import emit_typescript
from modelable.llm.context import (
    build_model_summary,
    build_projection_summary,
    build_workspace_summary,
    parse_model_ref,
)
from modelable.llm.importers import import_from_path, import_from_text
from modelable.llm.qa import answer_question
from modelable.llm.recommendations import recommend_for_model
from modelable.llm.render import render_mdl, render_model_version, render_projection_version
from modelable.llm.validation_help import explain_validation_errors
from modelable.parser.ir import (
    AnnKey,
    DirectMapping,
    FieldDef,
    MdlFile,
    ModelKind,
    ModelVersion,
    ProjectionField,
    ProjectionVersion,
    SourceRef,
    VersionExact,
    PrimitiveType,
)
from modelable.parser.parse import parse_text_to_ir
from modelable.planner.planner import expand_auto_projections
from modelable.validation.semantic import validate


@dataclass(frozen=True)
class AssistantResult:
    content: str
    warnings: list[str]


@dataclass(frozen=True)
class UpdateResult:
    path: Path
    content: str
    warnings: list[str]


def describe_path_or_ref(path: Path | None = None, ref: str | None = None) -> str:
    if ref and path is not None:
        workspace = load_workspace(path)
        if ref.count(".") == 1 and "@" in ref:
            model_ref = parse_model_ref(ref)
            domain = next((d for d in workspace.mdl.domains if d.name == model_ref.domain), None)
            if domain and model_ref.name in domain.projections:
                return build_projection_summary(workspace, ref)
            return build_model_summary(workspace, ref)
    if path is not None:
        workspace = load_workspace(path)
        return build_workspace_summary(workspace)
    return "No path or reference provided."


def generate_entity_from_prompt(prompt: str, *, domain_name: str | None = None, model_name: str | None = None) -> str:
    domain = domain_name or "generated"
    name = model_name or _derive_name_from_prompt(prompt)
    fields = [
        FieldDef(name=_key_field_name(name), type=_uuid_field(), annotations=[AnnKey()]),
        FieldDef(name="name", type=_string_field()),
    ]
    version = ModelVersion(model_kind=ModelKind.entity, version=1, change_kind="additive", fields=fields)
    return render_model_version(domain, name, version)


def transform_ref_to_target(path: Path, ref: str, target: str) -> AssistantResult:
    workspace = load_workspace(path)
    domain_name, model_name, version = _split_ref(ref)
    domain = next((d for d in workspace.mdl.domains if d.name == domain_name), None)
    if domain is None:
        raise ValueError(f"Unknown domain: {domain_name}")

    if model_name in domain.models:
        mv = next((item for item in domain.models[model_name] if item.version == version), None)
        if mv is None:
            raise ValueError(f"Unknown model version: {ref}")
        if target == "typescript":
            artifacts = emit_typescript(workspace, Path(".modelable/types"))
            art = next(a for a in artifacts if a.ref == ref)
            return AssistantResult(content=str(art.content), warnings=art.warnings)
        if target == "json-schema":
            artifacts = emit_json_schema(workspace, Path(".modelable/jsonschema"))
            art = next(a for a in artifacts if a.ref == ref)
            return AssistantResult(content=_json_dump(art.content), warnings=art.warnings)
        if target == "markdown":
            artifacts = emit_markdown(workspace, Path(".modelable/docs"))
            art = next(a for a in artifacts if a.ref == ref)
            return AssistantResult(content=str(art.content), warnings=art.warnings)
    raise ValueError(f"Unsupported target: {target}")


def import_definition(source: Path | str, source_format: str, *, domain_name: str | None = None) -> str:
    if isinstance(source, Path):
        imported = import_from_path(source, source_format, domain_name=domain_name)
    else:
        imported = import_from_text(source, source_format, domain_name=domain_name)
    return imported.to_mdl()


def suggest_projection(path: Path, source_ref: str, consumer_domain: str) -> str:
    workspace = load_workspace(path)
    model_ref = parse_model_ref(source_ref)
    domain = next((d for d in workspace.mdl.domains if d.name == model_ref.domain), None)
    if domain is None:
        raise ValueError(f"Unknown domain: {model_ref.domain}")
    versions = domain.models.get(model_ref.name)
    if not versions:
        raise ValueError(f"Unknown model: {source_ref}")
    version = next((item for item in versions if item.version == model_ref.version), None)
    if version is None:
        raise ValueError(f"Unknown model version: {source_ref}")

    target_fields: list[ProjectionField] = []
    alias = model_ref.name[0].lower() + model_ref.name[1:]
    for field in version.fields:
        if field.is_pii or any(ann.kind == "server" for ann in field.annotations):
            continue
        target_fields.append(
            ProjectionField(
                name=field.name,
                mapping=DirectMapping(source_alias=alias, source_field=field.name),
                annotations=list(field.annotations),
            )
        )
    projection = ProjectionVersion(
        version=version.version,
        source=SourceRef(
            model=f"{model_ref.domain}.{model_ref.name}",
            version=VersionExact(version=version.version),
            alias=alias,
        ),
        fields=target_fields,
    )
    return render_projection_version(consumer_domain, f"{model_ref.name}View", projection)


def answer_model_question_cli(path: Path, question: str) -> str:
    workspace = load_workspace(path)
    return answer_question(workspace, question)


def recommend_cli(path: Path, ref: str | None = None, consumer: str | None = None) -> str:
    workspace = load_workspace(path)
    return recommend_for_model(workspace, ref=ref, consumer=consumer)


def explain_validation(path: Path) -> str:
    workspace = load_workspace(path)
    return explain_validation_errors(workspace.errors)


def update_definition(path: Path, ref: str, instruction: str, *, output: Path | None = None) -> UpdateResult:
    workspace = load_workspace(path)
    model_ref = parse_model_ref(ref)
    source_path = _find_source_path_for_ref(workspace, model_ref.domain, model_ref.name)
    if source_path is None:
        raise ValueError(f"Could not find source file for {ref}")

    source_text = source_path.read_text(encoding="utf-8")
    mdl = parse_text_to_ir(source_text)

    domain = next((item for item in mdl.domains if item.name == model_ref.domain), None)
    if domain is None:
        raise ValueError(f"Unknown domain: {model_ref.domain}")

    warnings: list[str] = []
    updated = False

    if model_ref.name in domain.models:
        version = next((item for item in domain.models[model_ref.name] if item.version == model_ref.version), None)
        if version is None:
            raise ValueError(f"Unknown model version: {ref}")
        updated, warnings = _apply_model_update(version, instruction)
    else:
        raise ValueError("The first update workflow supports model versions only.")

    if not updated:
        raise ValueError("No supported update instructions were recognized")

    new_text = render_mdl(mdl)
    _, errors = validate_generated_text(new_text)
    if errors:
        raise ValueError("Updated definition failed validation: " + "; ".join(errors))

    out_path = output or source_path
    out_path.write_text(new_text, encoding="utf-8")
    return UpdateResult(path=out_path, content=new_text, warnings=warnings)


def validate_generated_text(text: str) -> tuple[MdlFile, list[str]]:
    mdl = parse_text_to_ir(text)
    errors = validate(mdl)
    if errors:
        return mdl, errors
    expanded_errors = expand_auto_projections(mdl)
    if expanded_errors:
        return mdl, expanded_errors
    return mdl, []


def _derive_name_from_prompt(prompt: str) -> str:
    words = [word for word in prompt.replace("/", " ").replace("-", " ").split() if word.isalpha()]
    for word in words:
        if len(word) > 2:
            return word[:1].upper() + word[1:]
    return "GeneratedModel"


def _key_field_name(model_name: str) -> str:
    return model_name[:1].lower() + model_name[1:] + "Id"


def _uuid_field() -> PrimitiveType:
    return PrimitiveType(kind="uuid")


def _string_field() -> PrimitiveType:
    return PrimitiveType(kind="string")


def _split_ref(ref: str) -> tuple[str, str, int]:
    model_ref = parse_model_ref(ref)
    return model_ref.domain, model_ref.name, model_ref.version


def _find_source_path_for_ref(workspace, domain_name: str, model_name: str) -> Path | None:
    for source in workspace.sources:
        domain = next((item for item in source.mdl.domains if item.name == domain_name), None)
        if domain is None:
            continue
        if model_name in domain.models or model_name in domain.projections:
            return source.path
    return None


def _apply_model_update(version: ModelVersion, instruction: str) -> tuple[bool, list[str]]:
    warnings: list[str] = []
    updated = False
    lowered = instruction.lower()

    for field in list(version.fields):
        if _matches_optional(field.name, lowered):
            field.optional = True
            updated = True
        if _matches_required(field.name, lowered):
            field.optional = False
            updated = True
        rename = _extract_rename(field.name, instruction)
        if rename is not None:
            field.name = rename
            updated = True
        if _matches_remove(field.name, lowered):
            version.fields = [item for item in version.fields if item is not field]
            updated = True
            continue
        change_type = _extract_type_change(field.name, instruction)
        if change_type is not None:
            field.type = change_type
            updated = True

    add_match = _extract_field_addition(instruction)
    if add_match is not None:
        field_name, field_type, optional = add_match
        if any(field.name == field_name for field in version.fields):
            warnings.append(f"Field '{field_name}' already exists; skipped add")
        else:
            version.fields.append(
                FieldDef(
                    name=field_name,
                    type=field_type or _string_field(),
                    optional=optional,
                )
            )
            updated = True

    return updated, warnings


def _extract_field_addition(instruction: str) -> tuple[str, PrimitiveType | None, bool] | None:
    patterns = [
        r"\badd\s+(?:a\s+)?field\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*(?:as|:)?\s*(?P<type>[A-Za-z_][A-Za-z0-9_<>,()]*)?(?P<optional>\s+optional)?\b",
        r"\badd\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*(?:as|:)?\s*(?P<type>[A-Za-z_][A-Za-z0-9_<>,()]*)?(?P<optional>\s+optional)?\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, instruction, re.IGNORECASE)
        if match:
            field_name = match.group("name")
            field_type = _type_from_text(match.group("type")) if match.group("type") else None
            optional = bool(match.group("optional"))
            return field_name, field_type, optional
    return None


def _extract_rename(existing_name: str, instruction: str) -> str | None:
    import re
    match = re.search(rf"\brename\s+{re.escape(existing_name)}\s+to\s+([A-Za-z_][A-Za-z0-9_]*)\b", instruction, re.IGNORECASE)
    if match:
        return match.group(1)
    return None


def _extract_type_change(existing_name: str, instruction: str) -> PrimitiveType | None:
    import re
    match = re.search(rf"\b(?:change|set)\s+{re.escape(existing_name)}\s+(?:to|as)\s+([A-Za-z_][A-Za-z0-9_<>,()]*)\b", instruction, re.IGNORECASE)
    if match:
        return _type_from_text(match.group(1))
    return None


def _matches_optional(field_name: str, instruction_lower: str) -> bool:
    return f"{field_name.lower()} optional" in instruction_lower or f"make {field_name.lower()} optional" in instruction_lower


def _matches_required(field_name: str, instruction_lower: str) -> bool:
    return f"{field_name.lower()} required" in instruction_lower or f"make {field_name.lower()} required" in instruction_lower


def _matches_remove(field_name: str, instruction_lower: str) -> bool:
    return f"remove {field_name.lower()}" in instruction_lower or f"delete {field_name.lower()}" in instruction_lower


def _type_from_text(type_name: str | None) -> PrimitiveType | None:
    if type_name is None:
        return None
    normalized = type_name.strip().lower()
    mapping = {
        "string": "string",
        "text": "string",
        "uuid": "uuid",
        "int": "int",
        "integer": "int",
        "float": "float",
        "number": "float",
        "bool": "bool",
        "boolean": "bool",
        "date": "date",
        "time": "time",
        "timestamp": "timestamp",
        "duration": "duration",
        "binary": "binary",
    }
    kind = mapping.get(normalized)
    if kind is None:
        return PrimitiveType(kind="string")
    return PrimitiveType(kind=kind)


def _json_dump(value) -> str:
    import json
    return json.dumps(value, indent=2, ensure_ascii=False)
