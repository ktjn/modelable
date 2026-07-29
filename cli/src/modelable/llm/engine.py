from __future__ import annotations

import hashlib
from dataclasses import dataclass
from os import environ
from pathlib import Path

from modelable.compat.diff import FieldChange, compare_model_versions
from modelable.compiler.render import render_mdl, render_model_version, render_projection_version
from modelable.compiler.workspace import load_workspace
from modelable.diagnostics.model import render_diagnostic
from modelable.emitters.csharp import emit_csharp
from modelable.emitters.dbt_yaml import emit_dbt_yaml
from modelable.emitters.go import emit_go
from modelable.emitters.java import emit_java
from modelable.emitters.json_schema import emit_json_schema
from modelable.emitters.markdown import emit_markdown
from modelable.emitters.python import emit_python
from modelable.emitters.rust import emit_rust
from modelable.emitters.typescript import emit_typescript
from modelable.llm.config import LlmConfig, resolve_llm_config
from modelable.llm.context import (
    build_model_summary,
    build_projection_summary,
    build_workspace_summary,
    parse_model_ref,
)
from modelable.llm.conversation import ConversationSession
from modelable.llm.importers import import_from_path, import_from_text
from modelable.llm.providers import LLMProvider, LLMRequest, LLMResponse, build_provider
from modelable.llm.qa import answer_question
from modelable.llm.recommendations import recommend_for_model
from modelable.llm.validation_help import explain_validation_errors
from modelable.parser.ir import (
    AnnKey,
    ChangeKind,
    DirectMapping,
    FieldDef,
    MdlFile,
    ModelKind,
    ModelVersion,
    ParseError,
    PrimitiveType,
    ProjectionField,
    ProjectionVersion,
    SourceRef,
    VersionExact,
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
class AttachResult:
    path: Path
    source_path: Path
    ref: str
    original_content: str
    content: str
    warnings: list[str]
    attached: bool
    from_version: int
    to_version: int | None
    change_kind: str | None
    changes: list[FieldChange]
    source_format: str
    source_name: str
    source_descriptor: str
    source_hash: str


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


def generate_entity_from_prompt(
    prompt: str, *, domain_name: str | None = None, model_name: str | None = None, owner: str | None = None
) -> str:
    domain = domain_name or "generated"
    name = model_name or _derive_name_from_prompt(prompt)
    fields = [
        FieldDef(name=_key_field_name(name), type=_uuid_field(), annotations=[AnnKey()]),
        FieldDef(name="name", type=_string_field()),
    ]
    version = ModelVersion(model_kind=ModelKind.entity, version=1, change_kind="additive", fields=fields)
    return render_model_version(domain, name, version, owner=owner or "generated")


def transform_ref_to_target(path: Path, ref: str, target: str) -> AssistantResult:
    workspace = load_workspace(path)
    domain_name, model_name, version = _split_ref(ref)
    domain = next((d for d in workspace.mdl.domains if d.name == domain_name), None)
    if domain is None:
        raise ValueError(f"Unknown domain: {domain_name}")

    emitters = {
        "typescript": (emit_typescript, Path(".modelable/types"), False),
        "json-schema": (emit_json_schema, Path(".modelable/jsonschema"), True),
        "markdown": (emit_markdown, Path(".modelable/docs"), False),
        "csharp": (emit_csharp, Path(".modelable/csharp"), False),
        "java": (emit_java, Path(".modelable/java"), False),
        "python": (emit_python, Path(".modelable/python"), False),
        "rust": (emit_rust, Path(".modelable/rust"), False),
        "go": (emit_go, Path(".modelable/go"), False),
        "dbt-yaml": (emit_dbt_yaml, Path(".modelable/dbt"), False),
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

    if target in emitters:
        emitter_fn, out_path, is_json = emitters[target]
        artifacts = emitter_fn(workspace, out_path)
        art = next(a for a in artifacts if a.ref == ref)
        content = _json_dump(art.content) if is_json else str(art.content)
        return AssistantResult(
            content=content,
            warnings=art.warnings,
            explanation=_build_transform_explanation(
                ref=ref, target=target, is_projection=model_name in domain.projections
            ),
        )
    raise ValueError(f"Unsupported target: {target}")


def import_definition(
    source: Path | str, source_format: str, *, domain_name: str | None = None, source_name: str | None = None
) -> str:
    if isinstance(source, Path):
        imported = import_from_path(source, source_format, domain_name=domain_name, source_name=source_name)
    else:
        imported = import_from_text(source, source_format, domain_name=domain_name, source_name=source_name)
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
    return render_projection_version(consumer_domain, f"{model_ref.name}View", projection, owner="suggested")


def answer_model_question_cli(path: Path, question: str) -> str:
    workspace = load_workspace(path)
    return answer_question(workspace, question)


def recommend_cli(path: Path, ref: str | None = None, consumer: str | None = None) -> str:
    workspace = load_workspace(path)
    return recommend_for_model(workspace, ref=ref, consumer=consumer)


def explain_validation(path: Path) -> str:
    workspace = load_workspace(path)
    return explain_validation_errors([render_diagnostic(error) for error in workspace.errors])


class _ProviderResponseTracker:
    """Wraps a provider to record the provider/model actually reported by the last completion.

    `UpdateResult.provider`/`.model` historically reflected the identity the LLM response itself
    reported (e.g. `LLMResponse.provider`), not just the static configuration used to build the
    provider. Preserve that so audit output still names the provider that actually served the
    request.
    """

    def __init__(self, inner: LLMProvider) -> None:
        self._inner = inner
        self.last_provider: str | None = None
        self.last_model: str | None = None
        self.call_count = 0

    def complete(self, request: LLMRequest) -> LLMResponse:
        response = self._inner.complete(request)
        self.last_provider = response.provider
        self.last_model = response.model
        self.call_count += 1
        return response

    @property
    def repairs_used(self) -> int:
        """Number of repair round-trips consumed (total completions minus the initial attempt)."""
        return max(self.call_count - 1, 0)


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
    original_text = source_path.read_text(encoding="utf-8")

    if llm_config is None:
        llm_config = resolve_llm_config(workspace=workspace.mdl.workspace, env=environ)
    provider_name = llm_config.provider or "local"
    model_name = llm_config.model or "modelable-local"
    if provider is None:
        provider = build_provider(llm_config.provider, model=llm_config.model, base_url=llm_config.base_url)
    if provider is None:
        raise ValueError(
            "modelable llm update requires an LLM provider; configure one with --provider/--model "
            "or workspace/environment configuration."
        )
    tracker = _ProviderResponseTracker(provider)

    session = ConversationSession(
        path=path,
        provider=tracker,
        focused_ref=ref,
        repair_attempts=llm_config.repair_attempts,
        provider_name=provider_name,
        model_name=model_name,
        confirmation_surface="cli-chat",
    )
    try:
        reply = session.turn(instruction, direct_edit_mode=True)
        provider_name = tracker.last_provider or provider_name
        model_name = tracker.last_model or model_name
        diagnostics_repaired = tracker.repairs_used
        if reply.kind != "preview" or reply.operation_kind != "source_change":
            raise ValueError(f"Could not apply the update instruction: {reply.text}")
        preview_file = next((item for item in reply.preview_files if item.path == source_path), None)
        if preview_file is None:
            raise ValueError(f"Update instruction did not change {source_path}")
        new_text = preview_file.after_text
        change_set_id = reply.change_set_id
        assert change_set_id is not None
        if not write:
            session.engine.discard(change_set_id)
            return UpdateResult(
                path=output or source_path,
                source_path=source_path,
                ref=ref,
                original_content=original_text,
                content=new_text,
                warnings=list(reply.assumptions),
                provider=provider_name,
                model=model_name,
                diagnostics_repaired=diagnostics_repaired,
            )
        if output is not None and output != source_path:
            # Redirect: leave the workspace source untouched, discard the change set instead
            # of applying it, and write the new content only to the requested output path.
            session.engine.discard(change_set_id)
            output.write_text(new_text, encoding="utf-8")
            return UpdateResult(
                path=output,
                source_path=source_path,
                ref=ref,
                original_content=original_text,
                content=new_text,
                warnings=list(reply.assumptions),
                provider=provider_name,
                model=model_name,
                diagnostics_repaired=diagnostics_repaired,
            )
        applied = session.engine.apply(change_set_id)
        if applied.kind != "applied":
            raise ValueError(f"Could not apply the update instruction: {applied.text}")
    finally:
        session.close()

    return UpdateResult(
        path=source_path,
        source_path=source_path,
        ref=ref,
        original_content=original_text,
        content=new_text,
        warnings=list(reply.assumptions),
        provider=provider_name,
        model=model_name,
        diagnostics_repaired=diagnostics_repaired,
    )


_BREAKING_ATTACH_CHANGE_KINDS = {"removed_field", "type_changed", "enum_changed", "identity_changed"}


def attach_external_version(
    path: Path,
    ref: str,
    source: Path | str,
    source_format: str,
    *,
    source_name: str | None = None,
    output: Path | None = None,
    write: bool = True,
) -> AttachResult:
    """Attach a model version to an external dbt or FHIR source.

    If the external source's fields differ from the referenced model version, append a
    new `.mdl` version block with a computed `additive`/`breaking` change kind.
    """
    workspace = load_workspace(path)
    model_ref = parse_model_ref(ref)
    source_path = _find_source_path_for_ref(workspace, model_ref.domain, model_ref.name)
    if source_path is None:
        raise ValueError(f"Could not find source file for {ref}")

    mdl_text = source_path.read_text(encoding="utf-8")
    mdl = parse_text_to_ir(mdl_text)
    domain = next((item for item in mdl.domains if item.name == model_ref.domain), None)
    if domain is None:
        raise ValueError(f"Unknown domain: {model_ref.domain}")
    versions = domain.models.get(model_ref.name)
    if not versions:
        raise ValueError(f"Unknown model: {ref}")
    current = next((item for item in versions if item.version == model_ref.version), None)
    if current is None:
        raise ValueError(f"Unknown model version: {ref}")

    if isinstance(source, Path):
        source_text = source.read_text(encoding="utf-8")
        source_descriptor = str(source)
    else:
        source_text = source
        source_descriptor = "inline"
    imported = import_from_text(source_text, source_format, domain_name=model_ref.domain, source_name=source_name)
    source_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()

    new_fields = _build_attached_fields(current.fields, imported.model_version.fields)
    candidate_version = ModelVersion(
        model_kind=current.model_kind,
        version=current.version,
        change_kind=current.change_kind,
        fields=new_fields,
    )
    changes = compare_model_versions(current, candidate_version)

    if not changes:
        return AttachResult(
            path=output or source_path,
            source_path=source_path,
            ref=ref,
            original_content=mdl_text,
            content=mdl_text,
            warnings=imported.warnings,
            attached=False,
            from_version=current.version,
            to_version=None,
            change_kind=None,
            changes=[],
            source_format=source_format,
            source_name=imported.source_name,
            source_descriptor=source_descriptor,
            source_hash=source_hash,
        )

    change_kind = _classify_attach_change_kind(changes)
    next_version_number = max(item.version for item in versions) + 1
    new_version = ModelVersion(
        model_kind=current.model_kind,
        version=next_version_number,
        change_kind=ChangeKind(change_kind),
        fields=new_fields,
    )
    versions.append(new_version)

    new_text = render_mdl(mdl)
    _, errors = validate_generated_text(new_text)
    if errors:
        raise ValueError("Attached definition failed validation: " + "; ".join(errors))

    out_path = output or source_path
    if write:
        out_path.write_text(new_text, encoding="utf-8")

    return AttachResult(
        path=out_path,
        source_path=source_path,
        ref=ref,
        original_content=mdl_text,
        content=new_text,
        warnings=imported.warnings,
        attached=True,
        from_version=current.version,
        to_version=next_version_number,
        change_kind=change_kind,
        changes=changes,
        source_format=source_format,
        source_name=imported.source_name,
        source_descriptor=source_descriptor,
        source_hash=source_hash,
    )


def _build_attached_fields(old_fields: list[FieldDef], candidate_fields: list[FieldDef]) -> list[FieldDef]:
    """Combine the current field set with imported fields, preserving existing annotations."""
    candidate_by_name = {field.name: field for field in candidate_fields}
    old_names = {field.name for field in old_fields}
    new_fields: list[FieldDef] = []
    for old_field in old_fields:
        candidate = candidate_by_name.get(old_field.name)
        if candidate is None:
            continue
        new_fields.append(
            FieldDef(
                name=old_field.name,
                type=candidate.type,
                optional=candidate.optional,
                default=old_field.default,
                annotations=list(old_field.annotations),
            )
        )
    for candidate in candidate_fields:
        if candidate.name not in old_names:
            new_fields.append(
                FieldDef(
                    name=candidate.name,
                    type=candidate.type,
                    optional=candidate.optional,
                    default=candidate.default,
                    annotations=list(candidate.annotations),
                )
            )
    return new_fields


def _classify_attach_change_kind(changes: list[FieldChange]) -> str:
    for change in changes:
        if change.kind in _BREAKING_ATTACH_CHANGE_KINDS:
            return "breaking"
        if change.kind == "nullability_changed" and change.from_optional and not change.to_optional:
            return "breaking"
    return "additive"


def render_attach_audit_summary(result: AttachResult) -> str:
    return render_write_audit_summary(
        provider="local",
        model="modelable-local",
        validation_status="passed",
        files_written=str(result.path),
        inputs=f"ref={result.ref} source={result.source_descriptor} format={result.source_format}",
        diagnostics_repaired=0,
    )


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
