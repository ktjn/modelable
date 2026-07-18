from __future__ import annotations

import difflib
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from modelable.compat.checker import (
    analyze_impact,
    check_model_version_compatibility,
    find_projection_dependents,
)
from modelable.compiler.workspace import (
    Workspace,
    WorkspaceDocumentSource,
    load_workspace,
    load_workspace_from_sources,
)
from modelable.diagnostics.model import Diagnostic, render_diagnostic
from modelable.llm.context import parse_model_ref
from modelable.llm.conversation_plan import (
    AddField,
    AddSecondaryIndex,
    AppendModelVersion,
    ChangeFieldType,
    ChangeSetPlan,
    CreateModel,
    RemoveField,
    RemoveSecondaryIndex,
    RenameField,
    SetFieldAnnotations,
    SetFieldOptionality,
    SetPrimaryIndex,
)
from modelable.llm.render import render_mdl
from modelable.parser.ir import (
    ChangeKind,
    DomainDef,
    FieldDef,
    IndexDecl,
    MdlFile,
    ModelKind,
    ModelVersion,
    SecondaryIndexDecl,
)


class WorkspaceEditError(ValueError):
    pass


_DRAFT_EDIT_WARNING = (
    "Draft edit requested: local publication state is not known, so this may rewrite a published contract."
)


@dataclass(frozen=True)
class ChangedDefinition:
    ref: str
    reason: str


@dataclass(frozen=True)
class AffectedDefinition:
    ref: str
    status: str
    reason: str


@dataclass(frozen=True)
class CompatibilityFinding:
    ref: str
    status: str
    message: str


@dataclass(frozen=True)
class PendingChangeSet:
    change_set_id: str
    plan: ChangeSetPlan
    assumptions: tuple[str, ...]
    source_fingerprints: dict[Path, str]
    candidate_sources: dict[Path, str]
    changed: list[ChangedDefinition]
    affected: list[AffectedDefinition]
    compatibility: list[CompatibilityFinding]
    diagnostics: list[Diagnostic]
    diff_text: str
    focus_ref: str | None


@dataclass
class _EditableDocument:
    path: Path
    uri: str
    original_text: str
    mdl: MdlFile


class WorkspaceEditor:
    def __init__(self, root: Path, *, workspace: Workspace | None = None) -> None:
        self.root = root
        self.workspace = workspace or load_workspace(root)
        existing_errors = [diagnostic for diagnostic in self.workspace.errors if diagnostic.severity == "error"]
        if existing_errors:
            rendered = "; ".join(render_diagnostic(diagnostic) for diagnostic in existing_errors)
            raise WorkspaceEditError(f"Workspace has validation errors: {rendered}")

    def preview(self, plan: ChangeSetPlan) -> PendingChangeSet:
        documents = self._copy_documents()
        changed_paths: set[Path] = set()
        changed: list[ChangedDefinition] = []
        appended_models: dict[str, str] = {}
        editable_refs: set[str] = set()

        for operation in plan.operations:
            if isinstance(operation, CreateModel):
                path, definition = self._apply_create_model(documents, operation)
                changed_paths.add(path)
                changed.append(definition)
                editable_refs.add(definition.ref)
                continue
            if isinstance(operation, AppendModelVersion):
                path, definition = self._apply_append_model_version(documents, operation)
                changed_paths.add(path)
                changed.append(definition)
                appended_models[definition.ref] = operation.source
                editable_refs.add(definition.ref)
                continue
            if isinstance(operation, AddField):
                path, definition = self._apply_add_field(
                    documents,
                    operation,
                    edit_mode=plan.edit_mode,
                    editable_refs=editable_refs,
                )
                changed_paths.add(path)
                changed.append(definition)
                continue
            if isinstance(operation, RenameField):
                path, definition = self._apply_rename_field(
                    documents,
                    operation,
                    edit_mode=plan.edit_mode,
                    editable_refs=editable_refs,
                )
                changed_paths.add(path)
                changed.append(definition)
                continue
            if isinstance(operation, RemoveField):
                path, definition = self._apply_remove_field(
                    documents,
                    operation,
                    edit_mode=plan.edit_mode,
                    editable_refs=editable_refs,
                )
                changed_paths.add(path)
                changed.append(definition)
                continue
            if isinstance(operation, ChangeFieldType):
                path, definition = self._apply_change_field_type(
                    documents,
                    operation,
                    edit_mode=plan.edit_mode,
                    editable_refs=editable_refs,
                )
                changed_paths.add(path)
                changed.append(definition)
                continue
            if isinstance(operation, SetFieldOptionality):
                path, definition = self._apply_set_field_optionality(
                    documents,
                    operation,
                    edit_mode=plan.edit_mode,
                    editable_refs=editable_refs,
                )
                changed_paths.add(path)
                changed.append(definition)
                continue
            if isinstance(operation, SetFieldAnnotations):
                path, definition = self._apply_set_field_annotations(
                    documents,
                    operation,
                    edit_mode=plan.edit_mode,
                    editable_refs=editable_refs,
                )
                changed_paths.add(path)
                changed.append(definition)
                continue
            if isinstance(operation, SetPrimaryIndex):
                path, definition = self._apply_set_primary_index(
                    documents,
                    operation,
                    edit_mode=plan.edit_mode,
                    editable_refs=editable_refs,
                )
                changed_paths.add(path)
                changed.append(definition)
                continue
            if isinstance(operation, AddSecondaryIndex):
                path, definition = self._apply_add_secondary_index(
                    documents,
                    operation,
                    edit_mode=plan.edit_mode,
                    editable_refs=editable_refs,
                )
                changed_paths.add(path)
                changed.append(definition)
                continue
            if isinstance(operation, RemoveSecondaryIndex):
                path, definition = self._apply_remove_secondary_index(
                    documents,
                    operation,
                    edit_mode=plan.edit_mode,
                    editable_refs=editable_refs,
                )
                changed_paths.add(path)
                changed.append(definition)
                continue
            raise WorkspaceEditError(f"Unsupported workspace operation: {operation.kind}")

        compatibility: list[CompatibilityFinding] = []
        affected: list[AffectedDefinition] = []
        if appended_models:
            staged_sources = {path: render_mdl(documents[path].mdl) for path in sorted(changed_paths)}
            staged_workspace = self._load_candidate_workspace(documents, staged_sources)
            for target_ref, source_ref in appended_models.items():
                source = parse_model_ref(source_ref)
                target = parse_model_ref(target_ref)
                report = check_model_version_compatibility(
                    staged_workspace.mdl,
                    source.domain,
                    source.name,
                    source.version,
                    target.version,
                )
                _, _, target_version = self._find_model_version_document(documents, target_ref)
                target_version.change_kind = ChangeKind.breaking if report.status == "breaking" else ChangeKind.additive
                compatibility.append(
                    CompatibilityFinding(
                        ref=target_ref,
                        status=report.status,
                        message="; ".join(report.findings) if report.findings else "no compatibility changes",
                    )
                )
                for dependent in find_projection_dependents(staged_workspace.mdl, source_ref):
                    impact = analyze_impact(staged_workspace.mdl, report, dependent)
                    affected.append(
                        AffectedDefinition(
                            ref=f"{impact.domain_name}.{impact.projection_name}@{impact.version}",
                            status=impact.status,
                            reason=impact.reason or f"depends on {source_ref}",
                        )
                    )

        rendered_sources = {path: render_mdl(documents[path].mdl) for path in sorted(changed_paths)}
        candidate_workspace = self._load_candidate_workspace(documents, rendered_sources)
        candidate_errors = [diagnostic for diagnostic in candidate_workspace.errors if diagnostic.severity == "error"]
        if candidate_errors:
            rendered = "; ".join(render_diagnostic(diagnostic) for diagnostic in candidate_errors)
            raise WorkspaceEditError(f"Proposed change set failed validation: {rendered}")

        source_fingerprints = {
            source.path: source.content_hash for source in self.workspace.sources if source.path is not None
        }
        diff_text = self._render_diffs(documents, rendered_sources)
        change_set_id = self._change_set_id(plan, source_fingerprints, rendered_sources)
        focus_ref = changed[-1].ref if changed else None
        assumptions = list(plan.assumptions)
        if plan.edit_mode == "draft" and _DRAFT_EDIT_WARNING not in assumptions:
            assumptions.append(_DRAFT_EDIT_WARNING)
        return PendingChangeSet(
            change_set_id=change_set_id,
            plan=plan,
            assumptions=tuple(assumptions),
            source_fingerprints=source_fingerprints,
            candidate_sources=rendered_sources,
            changed=changed,
            affected=affected,
            compatibility=compatibility,
            diagnostics=candidate_workspace.errors,
            diff_text=diff_text,
            focus_ref=focus_ref,
        )

    def _copy_documents(self) -> dict[Path, _EditableDocument]:
        documents: dict[Path, _EditableDocument] = {}
        for source in self.workspace.sources:
            if source.path is None:
                raise WorkspaceEditError(f"Cannot edit non-file workspace source: {source.uri}")
            documents[source.path] = _EditableDocument(
                path=source.path,
                uri=source.uri,
                original_text=source.text,
                mdl=source.mdl.model_copy(deep=True),
            )
        return documents

    def _apply_create_model(
        self,
        documents: dict[Path, _EditableDocument],
        operation: CreateModel,
    ) -> tuple[Path, ChangedDefinition]:
        path, domain = self._find_domain_document(documents, operation.domain)
        if (
            operation.name in domain.models
            or operation.name in domain.projections
            or any(declaration.name == operation.name for declaration in domain.semantic_types)
        ):
            raise WorkspaceEditError(f"Definition {operation.domain}.{operation.name} already exists")
        if operation.version <= 0:
            raise WorkspaceEditError("Model version must be positive")

        fields = [field.to_field_def() for field in operation.fields]
        if operation.model_kind in {ModelKind.entity, ModelKind.aggregate}:
            keys = [field for field in fields if field.is_key]
            if len(keys) != 1:
                raise WorkspaceEditError(
                    f"{operation.model_kind.value} {operation.domain}.{operation.name} must have exactly one @key"
                )

        version = ModelVersion(
            model_kind=operation.model_kind,
            version=operation.version,
            change_kind=ChangeKind.additive,
            fields=fields,
        )
        domain.models[operation.name] = [version]
        ref = f"{operation.domain}.{operation.name}@{operation.version}"
        return path, ChangedDefinition(ref=ref, reason=f"created {operation.model_kind.value}")

    def _apply_append_model_version(
        self,
        documents: dict[Path, _EditableDocument],
        operation: AppendModelVersion,
    ) -> tuple[Path, ChangedDefinition]:
        path, domain, source = self._find_model_version_document(documents, operation.source)
        source_ref = parse_model_ref(operation.source)
        versions = domain.models[source_ref.name]
        next_version = max(version.version for version in versions) + 1
        if operation.version != next_version:
            raise WorkspaceEditError(
                f"Model version {operation.version} is not the next version for "
                f"{source_ref.domain}.{source_ref.name}; expected {next_version}"
            )
        appended = source.model_copy(deep=True)
        appended.version = operation.version
        appended.protobuf_reservations = None
        versions.append(appended)
        source_index = next(
            (
                declaration
                for declaration in domain.index_decls
                if declaration.model == source_ref.name and declaration.version == source_ref.version
            ),
            None,
        )
        if source_index is not None:
            appended_index = source_index.model_copy(deep=True)
            appended_index.version = operation.version
            domain.index_decls.append(appended_index)
        target_ref = f"{source_ref.domain}.{source_ref.name}@{operation.version}"
        return path, ChangedDefinition(ref=target_ref, reason=f"appended from {operation.source}")

    def _apply_add_field(
        self,
        documents: dict[Path, _EditableDocument],
        operation: AddField,
        *,
        edit_mode: str,
        editable_refs: set[str],
    ) -> tuple[Path, ChangedDefinition]:
        if edit_mode != "draft" and operation.target not in editable_refs:
            raise WorkspaceEditError(
                f"Cannot edit existing model version {operation.target}; append a new version or use draft mode"
            )
        path, _, version = self._find_model_version_document(documents, operation.target)
        if any(field.name == operation.field.name for field in version.fields):
            raise WorkspaceEditError(f"Field {operation.field.name} already exists on {operation.target}")
        version.fields.append(operation.field.to_field_def())
        return path, ChangedDefinition(ref=operation.target, reason=f"added field {operation.field.name}")

    def _apply_rename_field(
        self,
        documents: dict[Path, _EditableDocument],
        operation: RenameField,
        *,
        edit_mode: str,
        editable_refs: set[str],
    ) -> tuple[Path, ChangedDefinition]:
        path, version, field = self._editable_model_field(
            documents,
            operation.target,
            operation.field,
            edit_mode=edit_mode,
            editable_refs=editable_refs,
        )
        if any(candidate.name == operation.new_name for candidate in version.fields):
            raise WorkspaceEditError(f"Field {operation.new_name} already exists on {operation.target}")
        field.name = operation.new_name
        return path, ChangedDefinition(
            ref=operation.target,
            reason=f"renamed field {operation.field} to {operation.new_name}",
        )

    def _apply_remove_field(
        self,
        documents: dict[Path, _EditableDocument],
        operation: RemoveField,
        *,
        edit_mode: str,
        editable_refs: set[str],
    ) -> tuple[Path, ChangedDefinition]:
        path, version, field = self._editable_model_field(
            documents,
            operation.target,
            operation.field,
            edit_mode=edit_mode,
            editable_refs=editable_refs,
        )
        version.fields = [candidate for candidate in version.fields if candidate is not field]
        return path, ChangedDefinition(ref=operation.target, reason=f"removed field {operation.field}")

    def _apply_change_field_type(
        self,
        documents: dict[Path, _EditableDocument],
        operation: ChangeFieldType,
        *,
        edit_mode: str,
        editable_refs: set[str],
    ) -> tuple[Path, ChangedDefinition]:
        path, _, field = self._editable_model_field(
            documents,
            operation.target,
            operation.field,
            edit_mode=edit_mode,
            editable_refs=editable_refs,
        )
        field.type = operation.type.model_copy(deep=True)
        return path, ChangedDefinition(ref=operation.target, reason=f"changed type of field {operation.field}")

    def _apply_set_field_optionality(
        self,
        documents: dict[Path, _EditableDocument],
        operation: SetFieldOptionality,
        *,
        edit_mode: str,
        editable_refs: set[str],
    ) -> tuple[Path, ChangedDefinition]:
        path, _, field = self._editable_model_field(
            documents,
            operation.target,
            operation.field,
            edit_mode=edit_mode,
            editable_refs=editable_refs,
        )
        field.optional = operation.optional
        state = "optional" if operation.optional else "required"
        return path, ChangedDefinition(ref=operation.target, reason=f"made field {operation.field} {state}")

    def _apply_set_field_annotations(
        self,
        documents: dict[Path, _EditableDocument],
        operation: SetFieldAnnotations,
        *,
        edit_mode: str,
        editable_refs: set[str],
    ) -> tuple[Path, ChangedDefinition]:
        path, _, field = self._editable_model_field(
            documents,
            operation.target,
            operation.field,
            edit_mode=edit_mode,
            editable_refs=editable_refs,
        )
        field.annotations = [annotation.model_copy(deep=True) for annotation in operation.annotations]
        return path, ChangedDefinition(ref=operation.target, reason=f"set annotations on field {operation.field}")

    def _apply_set_primary_index(
        self,
        documents: dict[Path, _EditableDocument],
        operation: SetPrimaryIndex,
        *,
        edit_mode: str,
        editable_refs: set[str],
    ) -> tuple[Path, ChangedDefinition]:
        path, declaration = self._editable_model_index(
            documents,
            operation.target,
            edit_mode=edit_mode,
            editable_refs=editable_refs,
        )
        declaration.primary = list(operation.fields)
        return path, ChangedDefinition(ref=operation.target, reason="set primary index")

    def _apply_add_secondary_index(
        self,
        documents: dict[Path, _EditableDocument],
        operation: AddSecondaryIndex,
        *,
        edit_mode: str,
        editable_refs: set[str],
    ) -> tuple[Path, ChangedDefinition]:
        path, declaration = self._editable_model_index(
            documents,
            operation.target,
            edit_mode=edit_mode,
            editable_refs=editable_refs,
        )
        if any(index.name == operation.index.name for index in declaration.secondary):
            raise WorkspaceEditError(f"Secondary index {operation.index.name} already exists on {operation.target}")
        declaration.secondary.append(
            SecondaryIndexDecl(
                name=operation.index.name,
                key=list(operation.index.key),
                sort=[item.model_copy(deep=True) for item in operation.index.sort],
                unique=operation.index.unique,
            )
        )
        return path, ChangedDefinition(
            ref=operation.target,
            reason=f"added secondary index {operation.index.name}",
        )

    def _apply_remove_secondary_index(
        self,
        documents: dict[Path, _EditableDocument],
        operation: RemoveSecondaryIndex,
        *,
        edit_mode: str,
        editable_refs: set[str],
    ) -> tuple[Path, ChangedDefinition]:
        path, declaration = self._editable_model_index(
            documents,
            operation.target,
            edit_mode=edit_mode,
            editable_refs=editable_refs,
        )
        index = next((candidate for candidate in declaration.secondary if candidate.name == operation.name), None)
        if index is None:
            raise WorkspaceEditError(f"Unknown secondary index {operation.name} on {operation.target}")
        declaration.secondary = [candidate for candidate in declaration.secondary if candidate is not index]
        return path, ChangedDefinition(
            ref=operation.target,
            reason=f"removed secondary index {operation.name}",
        )

    def _editable_model_field(
        self,
        documents: dict[Path, _EditableDocument],
        target: str,
        field_name: str,
        *,
        edit_mode: str,
        editable_refs: set[str],
    ) -> tuple[Path, ModelVersion, FieldDef]:
        if edit_mode != "draft" and target not in editable_refs:
            raise WorkspaceEditError(
                f"Cannot edit existing model version {target}; append a new version or use draft mode"
            )
        path, _, version = self._find_model_version_document(documents, target)
        field = next((candidate for candidate in version.fields if candidate.name == field_name), None)
        if field is None:
            raise WorkspaceEditError(f"Unknown field {field_name} on {target}")
        return path, version, field

    def _editable_model_index(
        self,
        documents: dict[Path, _EditableDocument],
        target: str,
        *,
        edit_mode: str,
        editable_refs: set[str],
    ) -> tuple[Path, IndexDecl]:
        if edit_mode != "draft" and target not in editable_refs:
            raise WorkspaceEditError(
                f"Cannot edit existing model version {target}; append a new version or use draft mode"
            )
        path, domain, version = self._find_model_version_document(documents, target)
        model_ref = parse_model_ref(target)
        declaration = next(
            (
                candidate
                for candidate in domain.index_decls
                if candidate.model == model_ref.name and candidate.version == model_ref.version
            ),
            None,
        )
        if declaration is None:
            declaration = IndexDecl(
                model=model_ref.name,
                version=model_ref.version,
                primary=[field.name for field in version.fields if field.is_key],
            )
            domain.index_decls.append(declaration)
        return path, declaration

    @staticmethod
    def _find_model_version_document(
        documents: dict[Path, _EditableDocument],
        ref: str,
    ) -> tuple[Path, DomainDef, ModelVersion]:
        try:
            model_ref = parse_model_ref(ref)
        except (TypeError, ValueError) as error:
            raise WorkspaceEditError(str(error)) from error
        matches: list[tuple[Path, DomainDef, ModelVersion]] = []
        for path, document in documents.items():
            for domain in document.mdl.domains:
                if domain.name != model_ref.domain:
                    continue
                for version in domain.models.get(model_ref.name, []):
                    if version.version == model_ref.version:
                        matches.append((path, domain, version))
        if not matches:
            raise WorkspaceEditError(f"Unknown model version: {ref}")
        if len(matches) > 1:
            raise WorkspaceEditError(f"Model version {ref} is defined in multiple source files")
        return matches[0]

    @staticmethod
    def _find_domain_document(
        documents: dict[Path, _EditableDocument],
        domain_name: str,
    ) -> tuple[Path, DomainDef]:
        matches: list[tuple[Path, DomainDef]] = []
        for path, document in documents.items():
            for domain in document.mdl.domains:
                if domain.name == domain_name:
                    matches.append((path, domain))
        if not matches:
            raise WorkspaceEditError(f"Unknown domain: {domain_name}")
        if len(matches) > 1:
            raise WorkspaceEditError(f"Domain {domain_name} is defined in multiple source files")
        return matches[0]

    @staticmethod
    def _load_candidate_workspace(
        documents: dict[Path, _EditableDocument],
        rendered_sources: dict[Path, str],
    ) -> Workspace:
        sources = [
            WorkspaceDocumentSource(
                path=path,
                uri=document.uri,
                text=rendered_sources.get(path, document.original_text),
            )
            for path, document in sorted(documents.items())
        ]
        return load_workspace_from_sources(sources)

    @staticmethod
    def _render_diffs(
        documents: dict[Path, _EditableDocument],
        rendered_sources: dict[Path, str],
    ) -> str:
        sections: list[str] = []
        for path, candidate in sorted(rendered_sources.items()):
            sections.extend(
                difflib.unified_diff(
                    documents[path].original_text.splitlines(),
                    candidate.splitlines(),
                    fromfile=str(path),
                    tofile=f"{path} (preview)",
                    lineterm="",
                )
            )
        return "\n".join(sections)

    @staticmethod
    def _change_set_id(
        plan: ChangeSetPlan,
        source_fingerprints: dict[Path, str],
        rendered_sources: dict[Path, str],
    ) -> str:
        payload = {
            "plan": plan.model_dump(mode="json"),
            "source_fingerprints": {
                path.as_posix(): fingerprint for path, fingerprint in sorted(source_fingerprints.items())
            },
            "candidate_hashes": {
                path.as_posix(): hashlib.sha256(text.encode("utf-8")).hexdigest()
                for path, text in sorted(rendered_sources.items())
            },
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
