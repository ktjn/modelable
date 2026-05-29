from __future__ import annotations

import re
from dataclasses import dataclass
from os import environ
from pathlib import Path

from modelable.compiler.workspace import load_workspace
from modelable.emitters.csharp import emit_csharp
from modelable.emitters.go import emit_go
from modelable.emitters.java import emit_java
from modelable.emitters.json_schema import emit_json_schema
from modelable.emitters.markdown import emit_markdown
from modelable.emitters.python import emit_python
from modelable.emitters.rust import emit_rust
from modelable.emitters.typescript import emit_typescript
from modelable.llm.context import (
    build_model_summary,
    build_projection_summary,
    build_workspace_summary,
    parse_model_ref,
)
from modelable.llm.config import LlmConfig, resolve_llm_config
from modelable.llm.importers import import_from_path, import_from_text
from modelable.llm.qa import answer_question
from modelable.llm.providers import LLMProvider, build_provider
from modelable.llm.recommendations import recommend_for_model
from modelable.llm.render import render_mdl, render_model_version, render_projection_version
from modelable.llm.update_plan import UpdateChange, UpdatePlan, build_update_request, parse_update_plan
from modelable.llm.update_plan import build_update_repair_request
from modelable.llm.validation_help import explain_validation_errors
from modelable.diagnostics.model import render_diagnostic
from modelable.parser.ir import (
    AnnKey,
    DirectMapping,
    FieldDef,
    ParseError,
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
    explanation: str | None = None


@dataclass(frozen=True)
class UpdateResult:
    path: Path
    source_path: Path
    ref: str
    original_content: str
    content: str
    warnings: list[str]
    provider: str
    model: str
    diagnostics_repaired: int


@dataclass(frozen=True)
class UpdatePlanResult:
    plan: UpdatePlan
    provider: str
    model: str
    diagnostics_repaired: int


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

    _EMITTERS = {
        "typescript": (emit_typescript, Path(".modelable/types"), False),
        "json-schema": (emit_json_schema, Path(".modelable/jsonschema"), True),
        "markdown": (emit_markdown, Path(".modelable/docs"), False),
        "csharp": (emit_csharp, Path(".modelable/csharp"), False),
        "java": (emit_java, Path(".modelable/java"), False),
        "python": (emit_python, Path(".modelable/python"), False),
        "rust": (emit_rust, Path(".modelable/rust"), False),
        "go": (emit_go, Path(".modelable/go"), False),
    }

    if model_name in domain.models:
        mv = next((item for item in domain.models[model_name] if item.version == version), None)
        if mv is None:
            raise ValueError(f"Unknown model version: {ref}")
    elif model_name in domain.projections:
        pv = next((item for item in domain.projections[model_name] if item.version == version), None)
        if pv is None:
            raise ValueError(f"Unknown projection version: {ref}")
    else:
        raise ValueError(f"Unknown model or projection: {ref}")

    if target in _EMITTERS:
        emitter_fn, out_path, is_json = _EMITTERS[target]
        artifacts = emitter_fn(workspace, out_path)
        art = next(a for a in artifacts if a.ref == ref)
        content = _json_dump(art.content) if is_json else str(art.content)
        return AssistantResult(
            content=content,
            warnings=art.warnings,
            explanation=_build_transform_explanation(ref=ref, target=target, is_projection=model_name in domain.projections),
        )
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
    return explain_validation_errors([render_diagnostic(error) for error in workspace.errors])


def _build_update_plan(
    provider: LLMProvider,
    workspace,
    current_text: str,
    ref: str,
    instruction: str,
) -> UpdatePlanResult:
    current_summary = _summarize_update_target(workspace, ref)
    request = build_update_request(
        ref=ref,
        current_summary=current_summary,
        current_text=current_text,
        instruction=instruction,
    )
    response = provider.complete(request)
    try:
        plan = _parse_update_plan_response(response.content, ref=ref)
        return UpdatePlanResult(plan=plan, provider=response.provider, model=response.model, diagnostics_repaired=0)
    except Exception as exc:
        repair_request = build_update_repair_request(
            ref=ref,
            current_summary=current_summary,
            current_text=current_text,
            instruction=instruction,
            validation_error=str(exc),
        )
        repair_response = provider.complete(repair_request)
        try:
            plan = _parse_update_plan_response(repair_response.content, ref=ref)
            return UpdatePlanResult(
                plan=plan,
                provider=repair_response.provider,
                model=repair_response.model,
                diagnostics_repaired=1,
            )
        except Exception as repair_exc:  # pragma: no cover - provider integration guard
            raise ValueError(f"LLM returned an invalid update plan after repair: {repair_exc}") from repair_exc


def _parse_update_plan_response(content: str, *, ref: str) -> UpdatePlan:
    try:
        plan = parse_update_plan(content)
    except Exception as exc:
        raise ValueError(f"LLM returned an invalid update plan: {exc}") from exc
    if plan.target != ref:
        raise ValueError(f"LLM proposed an update for '{plan.target}' instead of '{ref}'")
    return plan


def update_definition(
    path: Path,
    ref: str,
    instruction: str,
    *,
    output: Path | None = None,
    write: bool = True,
    provider: LLMProvider | None = None,
    llm_config: LlmConfig | None = None,
) -> UpdateResult:
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
    provider_name = "local"
    model_name = llm_config.model if llm_config is not None else "modelable-local"
    diagnostics_repaired = 0

    if provider is None and llm_config is None:
        llm_config = resolve_llm_config(workspace=workspace.mdl.workspace, env=environ)
        provider = build_provider(llm_config.provider, model=llm_config.model, base_url=llm_config.base_url)
        provider_name = llm_config.provider or "local"
        model_name = llm_config.model or model_name
    elif llm_config is not None:
        provider_name = llm_config.provider or "local"
        model_name = llm_config.model or model_name

    if model_ref.name in domain.models:
        version = next((item for item in domain.models[model_ref.name] if item.version == model_ref.version), None)
        if version is None:
            raise ValueError(f"Unknown model version: {ref}")
        if provider is not None:
            plan_result = _build_update_plan(provider, workspace, source_text, ref, instruction)
            updated, warnings = _apply_update_plan_to_model(version, plan_result.plan)
            provider_name = plan_result.provider
            model_name = plan_result.model
            diagnostics_repaired = plan_result.diagnostics_repaired
        else:
            updated, warnings = _apply_model_update(version, instruction)
    elif model_ref.name in domain.projections:
        version = next((item for item in domain.projections[model_ref.name] if item.version == model_ref.version), None)
        if version is None:
            raise ValueError(f"Unknown projection version: {ref}")
        if provider is not None:
            plan_result = _build_update_plan(provider, workspace, source_text, ref, instruction)
            updated, warnings = _apply_update_plan_to_projection(version, plan_result.plan)
            provider_name = plan_result.provider
            model_name = plan_result.model
            diagnostics_repaired = plan_result.diagnostics_repaired
        else:
            updated, warnings = _apply_projection_update(version, instruction)
    else:
        raise ValueError(f"Unknown model or projection: {ref}")

    if not updated:
        raise ValueError("No supported update instructions were recognized")

    original_text = source_text
    new_text = render_mdl(mdl)
    _, errors = validate_generated_text(new_text)
    if errors:
        raise ValueError("Updated definition failed validation: " + "; ".join(errors))

    out_path = output or source_path
    if write:
        out_path.write_text(new_text, encoding="utf-8")
    return UpdateResult(
        path=out_path,
        source_path=source_path,
        ref=ref,
        original_content=original_text,
        content=new_text,
        warnings=warnings,
        provider=provider_name,
        model=model_name,
        diagnostics_repaired=diagnostics_repaired,
    )


def _summarize_update_target(workspace, ref: str) -> str:
    model_ref = parse_model_ref(ref)
    domain = next((item for item in workspace.mdl.domains if item.name == model_ref.domain), None)
    if domain is None:
        return f"Unknown domain: {model_ref.domain}"
    if model_ref.name in domain.models:
        return build_model_summary(workspace, ref)
    if model_ref.name in domain.projections:
        return build_projection_summary(workspace, ref)
    return f"Unknown model or projection: {ref}"


def _apply_update_plan_to_model(version: ModelVersion, plan: UpdatePlan) -> tuple[bool, list[str]]:
    if plan.target_kind != "model":
        raise ValueError(f"Update plan target kind '{plan.target_kind}' does not match model version")
    warnings = list(plan.warnings)
    updated = False
    for change in plan.changes:
        changed, change_warnings = _apply_model_change(version, change)
        updated = updated or changed
        warnings.extend(change_warnings)
    return updated, warnings


def _apply_update_plan_to_projection(version: ProjectionVersion, plan: UpdatePlan) -> tuple[bool, list[str]]:
    if plan.target_kind != "projection":
        raise ValueError(f"Update plan target kind '{plan.target_kind}' does not match projection version")
    warnings = list(plan.warnings)
    updated = False
    for change in plan.changes:
        changed, change_warnings = _apply_projection_change(version, change)
        updated = updated or changed
        warnings.extend(change_warnings)
    return updated, warnings


def _apply_model_change(version: ModelVersion, change: UpdateChange) -> tuple[bool, list[str]]:
    field = next((item for item in version.fields if item.name == change.field), None)
    warnings: list[str] = []
    if change.kind == "add_field":
        field_name = change.new_name or change.field
        if any(item.name == field_name for item in version.fields):
            warnings.append(f"Field '{field_name}' already exists; skipped add")
            return False, warnings
        version.fields.append(
            FieldDef(
                name=field_name,
                type=_type_from_text(change.type) or _string_field(),
                optional=False,
            )
        )
        return True, warnings
    if field is None:
        warnings.append(f"Field '{change.field}' not found; skipped {change.kind}")
        return False, warnings
    if change.kind == "make_optional":
        field.optional = True
        return True, warnings
    if change.kind == "make_required":
        field.optional = False
        return True, warnings
    if change.kind == "rename_field":
        if not change.new_name:
            raise ValueError(f"rename_field for '{change.field}' requires new_name")
        field.name = change.new_name
        return True, warnings
    if change.kind == "remove_field":
        version.fields = [item for item in version.fields if item is not field]
        return True, warnings
    if change.kind == "change_type":
        field.type = _type_from_text(change.type) or _string_field()
        return True, warnings
    raise ValueError(f"Unsupported model update change: {change.kind}")


def _apply_projection_change(version: ProjectionVersion, change: UpdateChange) -> tuple[bool, list[str]]:
    field = next((item for item in version.fields if item.name == change.field), None)
    warnings: list[str] = []
    if change.kind == "add_field":
        field_name = change.new_name or change.field
        if any(item.name == field_name for item in version.fields):
            warnings.append(f"Field '{field_name}' already exists; skipped add")
            return False, warnings
        version.fields.append(
            ProjectionField(
                name=field_name,
                mapping=DirectMapping(
                    source_alias=version.source.alias,
                    source_field=_normalize_source_field(change.source or field_name),
                ),
            )
        )
        return True, warnings
    if field is None:
        warnings.append(f"Field '{change.field}' not found; skipped {change.kind}")
        return False, warnings
    if change.kind == "rename_field":
        if not change.new_name:
            raise ValueError(f"rename_field for '{change.field}' requires new_name")
        field.name = change.new_name
        return True, warnings
    if change.kind == "remove_field":
        version.fields = [item for item in version.fields if item is not field]
        return True, warnings
    if change.kind == "change_source":
        if not isinstance(field.mapping, DirectMapping):
            warnings.append(f"Field '{change.field}' is not a direct mapping; skipped source change")
            return False, warnings
        if not change.source:
            raise ValueError(f"change_source for '{change.field}' requires source")
        field.mapping.source_field = _normalize_source_field(change.source)
        return True, warnings
    if change.kind == "change_type":
        warnings.append(f"Projection field '{change.field}' does not support change_type; skipped")
        return False, warnings
    if change.kind in {"make_optional", "make_required"}:
        warnings.append(f"Projection field '{change.field}' does not support {change.kind}; skipped")
        return False, warnings
    raise ValueError(f"Unsupported projection update change: {change.kind}")


def validate_generated_text(text: str) -> tuple[MdlFile | None, list[str]]:
    try:
        mdl = parse_text_to_ir(text)
    except ParseError as exc:
        return None, [exc.message]
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


def _apply_projection_update(version: ProjectionVersion, instruction: str) -> tuple[bool, list[str]]:
    warnings: list[str] = []
    updated = False
    lowered = instruction.lower()

    for field in list(version.fields):
        rename = _extract_rename(field.name, instruction)
        if rename is not None:
            field.name = rename
            updated = True
        if _matches_remove(field.name, lowered):
            version.fields = [item for item in version.fields if item is not field]
            updated = True
            continue
        if _matches_source_field_change(field.name, instruction):
            new_source = _extract_source_field(field.name, instruction)
            if new_source is not None and isinstance(field.mapping, DirectMapping):
                field.mapping.source_field = new_source
                updated = True

    add_match = _extract_projection_field_addition(instruction)
    if add_match is not None:
        field_name, source_field = add_match
        if any(field.name == field_name for field in version.fields):
            warnings.append(f"Field '{field_name}' already exists; skipped add")
        else:
            version.fields.append(
                ProjectionField(
                    name=field_name,
                    mapping=DirectMapping(
                        source_alias=version.source.alias,
                        source_field=_normalize_source_field(source_field or field_name),
                    ),
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


def _extract_projection_field_addition(instruction: str) -> tuple[str, str | None] | None:
    patterns = [
        r"\badd\s+(?:a\s+)?projection\s+field\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*(?:from|as|=|:)?\s*(?P<source>[A-Za-z_][A-Za-z0-9_\.]*)?",
        r"\badd\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*(?:from|as|=|:)?\s*(?P<source>[A-Za-z_][A-Za-z0-9_\.]*)?",
    ]
    for pattern in patterns:
        match = re.search(pattern, instruction, re.IGNORECASE)
        if match:
            return match.group("name"), match.group("source")
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


def _matches_source_field_change(field_name: str, instruction: str) -> bool:
    lowered = instruction.lower()
    return f"{field_name.lower()} from" in lowered or f"change {field_name.lower()} source" in lowered


def _extract_source_field(existing_name: str, instruction: str) -> str | None:
    match = re.search(
        rf"\b(?:change|set|update)\s+{re.escape(existing_name)}\s+(?:source\s+)?(?:to|from)\s+([A-Za-z_][A-Za-z0-9_\.]*)",
        instruction,
        re.IGNORECASE,
    )
    if match:
        return _normalize_source_field(match.group(1))
    return None


def _normalize_source_field(source_field: str) -> str:
    return source_field.split(".")[-1]


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


def render_update_audit_summary(result: UpdateResult) -> str:
    return render_write_audit_summary(
        provider=result.provider,
        model=result.model,
        validation_status="passed",
        files_written=str(result.path),
        inputs=f"ref={result.ref} source={result.source_path}",
        diagnostics_repaired=result.diagnostics_repaired,
    )


def render_write_audit_summary(
    *,
    provider: str,
    model: str,
    validation_status: str,
    files_written: str,
    inputs: str,
    diagnostics_repaired: int,
) -> str:
    lines = [
        "audit:",
        f"  provider: {provider}",
        f"  model: {model}",
        f"  validation: {validation_status}",
        f"  files_written: {files_written}",
        f"  inputs: {inputs}",
        f"  diagnostics_repaired: {diagnostics_repaired}",
    ]
    return "\n".join(lines)


def _build_transform_explanation(*, ref: str, target: str, is_projection: bool) -> str:
    source_kind = "projection" if is_projection else "model"
    target_notes = {
        "json-schema": "non-optional fields become required and optional fields remain optional in the schema.",
        "markdown": "the output is formatted as human-readable domain, field, source, and lineage tables.",
        "typescript": "field optionality and stable interface names are preserved in the generated typings.",
        "csharp": "field shapes are mapped to C# types using the native backend conventions.",
        "java": "field shapes are mapped to Java types using the native backend conventions.",
        "python": "field shapes are mapped to Python types using the native backend conventions.",
        "rust": "field shapes are mapped to Rust types using the native backend conventions.",
        "go": "field shapes are mapped to Go types using the native backend conventions.",
    }
    detail = target_notes.get(target, "the target emitter preserves the normalized workspace graph.")
    return f"Explanation: emitted {target} for {ref} from the normalized {source_kind} graph; {detail}"
