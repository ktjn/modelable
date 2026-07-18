from __future__ import annotations

import difflib
import hashlib
import json
import os
import tempfile
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
    AddProjectionField,
    AddProjectionJoin,
    AddSecondaryIndex,
    AppendModelVersion,
    AppendProjectionVersion,
    ChangeFieldType,
    ChangeSetPlan,
    ComputedMappingSpec,
    CreateModel,
    CreateProjection,
    DirectMappingSpec,
    Operation,
    ProjectionFieldSpec,
    ProjectionJoinSpec,
    ProjectionMappingSpec,
    RemoveField,
    RemoveSecondaryIndex,
    RenameDefinition,
    RenameField,
    RetireDefinition,
    SetFieldAnnotations,
    SetFieldOptionality,
    SetPrimaryIndex,
    SetProjectionFilter,
    SetProjectionGrouping,
    SetProjectionMapping,
    SetProjectionSource,
)
from modelable.llm.render import render_mdl
from modelable.parser.ir import (
    ChangeKind,
    ComputedMapping,
    DirectMapping,
    DomainDef,
    FieldDef,
    IndexDecl,
    JoinRef,
    MdlFile,
    ModelKind,
    ModelVersion,
    ProjectionField,
    ProjectionVersion,
    SecondaryIndexDecl,
    SourceRef,
    VersionExact,
)


class WorkspaceEditError(ValueError):
    pass


class StaleChangeSetError(WorkspaceEditError):
    pass


class WorkspaceApplyError(WorkspaceEditError):
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


@dataclass(frozen=True)
class AppliedChangeSet:
    change_set_id: str
    written_paths: tuple[Path, ...]
    changed: list[ChangedDefinition]
    compatibility: list[CompatibilityFinding]
    workspace: Workspace
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
        affected: list[AffectedDefinition] = []
        appended_models: dict[str, str] = {}
        editable_refs: set[str] = set()
        renamed_refs: dict[str, str] = {}

        for operation in plan.operations:
            operation = self._remap_operation_refs(operation, renamed_refs)
            if isinstance(operation, RenameDefinition):
                path, definition, old_refs = self._apply_rename_definition(
                    documents,
                    operation,
                    edit_mode=plan.edit_mode,
                )
                changed_paths.add(path)
                changed.append(definition)
                old_definition = old_refs[0].rsplit("@", 1)[0]
                new_definition = definition.ref.rsplit("@", 1)[0]
                renamed_refs[old_definition] = new_definition
                for old_ref in old_refs:
                    old_version = old_ref.rsplit("@", 1)[1]
                    renamed_refs[old_ref] = f"{new_definition}@{old_version}"
                    for dependent, parent_ref, _ in self._projection_dependents_transitive(
                        self.workspace.mdl,
                        old_ref,
                    ):
                        affected.append(
                            AffectedDefinition(
                                ref=f"{dependent[0]}.{dependent[1]}@{dependent[2]}",
                                status="affected",
                                reason=f"depends on {parent_ref}",
                            )
                        )
                continue
            if isinstance(operation, RetireDefinition):
                raise WorkspaceEditError(
                    f"Cannot retire {operation.target}: the current .mdl language has no "
                    "published-contract retirement declaration."
                )
            if isinstance(operation, CreateModel):
                path, definition = self._apply_create_model(documents, operation)
                changed_paths.add(path)
                changed.append(definition)
                editable_refs.add(definition.ref)
                continue
            if isinstance(operation, CreateProjection):
                path, definition = self._apply_create_projection(documents, operation)
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
            if isinstance(operation, AppendProjectionVersion):
                path, definition = self._apply_append_projection_version(documents, operation)
                changed_paths.add(path)
                changed.append(definition)
                editable_refs.add(definition.ref)
                continue
            if isinstance(operation, SetProjectionSource):
                path, definition = self._apply_set_projection_source(
                    documents,
                    operation,
                    edit_mode=plan.edit_mode,
                    editable_refs=editable_refs,
                )
                changed_paths.add(path)
                changed.append(definition)
                continue
            if isinstance(operation, AddProjectionField):
                path, definition = self._apply_add_projection_field(
                    documents,
                    operation,
                    edit_mode=plan.edit_mode,
                    editable_refs=editable_refs,
                )
                changed_paths.add(path)
                changed.append(definition)
                continue
            if isinstance(operation, SetProjectionMapping):
                path, definition = self._apply_set_projection_mapping(
                    documents,
                    operation,
                    edit_mode=plan.edit_mode,
                    editable_refs=editable_refs,
                )
                changed_paths.add(path)
                changed.append(definition)
                continue
            if isinstance(operation, AddProjectionJoin):
                path, definition = self._apply_add_projection_join(
                    documents,
                    operation,
                    edit_mode=plan.edit_mode,
                    editable_refs=editable_refs,
                )
                changed_paths.add(path)
                changed.append(definition)
                continue
            if isinstance(operation, SetProjectionFilter):
                path, definition = self._apply_set_projection_filter(
                    documents,
                    operation,
                    edit_mode=plan.edit_mode,
                    editable_refs=editable_refs,
                )
                changed_paths.add(path)
                changed.append(definition)
                continue
            if isinstance(operation, SetProjectionGrouping):
                path, definition = self._apply_set_projection_grouping(
                    documents,
                    operation,
                    edit_mode=plan.edit_mode,
                    editable_refs=editable_refs,
                )
                changed_paths.add(path)
                changed.append(definition)
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
        if appended_models:
            staged_sources = {path: render_mdl(documents[path].mdl) for path in sorted(changed_paths)}
            staged_workspace = self._load_candidate_workspace(documents, staged_sources)
            for target_ref, source_ref in appended_models.items():
                source = parse_model_ref(source_ref)
                target_model_ref = parse_model_ref(target_ref)
                report = check_model_version_compatibility(
                    staged_workspace.mdl,
                    source.domain,
                    source.name,
                    source.version,
                    target_model_ref.version,
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
                for dependent, parent_ref, is_direct in self._projection_dependents_transitive(
                    staged_workspace.mdl,
                    source_ref,
                ):
                    dependent_ref = f"{dependent[0]}.{dependent[1]}@{dependent[2]}"
                    if is_direct:
                        impact = analyze_impact(staged_workspace.mdl, report, dependent)
                        affected.append(
                            AffectedDefinition(
                                ref=dependent_ref,
                                status=impact.status,
                                reason=impact.reason or f"depends on {source_ref}",
                            )
                        )
                    else:
                        affected.append(
                            AffectedDefinition(
                                ref=dependent_ref,
                                status="affected",
                                reason=f"depends on {parent_ref}",
                            )
                        )

        rendered_sources = {path: render_mdl(documents[path].mdl) for path in sorted(changed_paths)}
        candidate_workspace = self._load_candidate_workspace(documents, rendered_sources)
        candidate_errors = [diagnostic for diagnostic in candidate_workspace.errors if diagnostic.severity == "error"]
        if candidate_errors:
            rendered = "; ".join(render_diagnostic(diagnostic) for diagnostic in candidate_errors)
            raise WorkspaceEditError(f"Proposed change set failed validation: {rendered}")

        affected_by_ref: dict[str, AffectedDefinition] = {}
        for affected_definition in affected:
            current = affected_by_ref.get(affected_definition.ref)
            if current is None or self._impact_severity(affected_definition.status) > self._impact_severity(
                current.status
            ):
                affected_by_ref[affected_definition.ref] = affected_definition
        affected = [affected_by_ref[ref] for ref in sorted(affected_by_ref)]

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

    def apply(self, pending: PendingChangeSet) -> AppliedChangeSet:
        if self._current_source_fingerprints() != pending.source_fingerprints:
            raise StaleChangeSetError("Workspace sources changed after this change set was previewed")

        restaged = self.preview(pending.plan)
        if restaged != pending:
            raise StaleChangeSetError("Change set no longer matches its deterministic preview")

        written_paths = tuple(sorted(pending.candidate_sources))
        originals: dict[Path, tuple[bool, bytes]] = {}
        temporary_paths: dict[Path, Path] = {}
        replaced_paths: list[Path] = []
        try:
            for path in written_paths:
                existed = path.exists()
                originals[path] = (existed, path.read_bytes() if existed else b"")
                temporary_paths[path] = self._write_temporary_file(
                    path,
                    pending.candidate_sources[path].encode("utf-8"),
                )

            for path in written_paths:
                os.replace(temporary_paths[path], path)
                replaced_paths.append(path)

            workspace = load_workspace(self.root)
            reload_errors = [diagnostic for diagnostic in workspace.errors if diagnostic.severity == "error"]
            if reload_errors:
                rendered = "; ".join(render_diagnostic(diagnostic) for diagnostic in reload_errors)
                raise WorkspaceApplyError(f"Reloaded workspace has validation errors: {rendered}")
        except Exception as error:
            rollback_errors = self._rollback_replacements(replaced_paths, originals)
            if rollback_errors:
                details = "; ".join(rollback_errors)
                raise WorkspaceApplyError(
                    f"Workspace apply failed and rollback was incomplete ({details}): {error}"
                ) from error
            raise WorkspaceApplyError(f"Workspace apply failed and was rolled back: {error}") from error
        finally:
            for temporary_path in temporary_paths.values():
                temporary_path.unlink(missing_ok=True)

        self.workspace = workspace
        return AppliedChangeSet(
            change_set_id=pending.change_set_id,
            written_paths=written_paths,
            changed=pending.changed,
            compatibility=pending.compatibility,
            workspace=workspace,
            focus_ref=pending.focus_ref,
        )

    def _current_source_fingerprints(self) -> dict[Path, str]:
        paths = (
            [self.root]
            if self.root.is_file() and self.root.suffix == ".mdl"
            else sorted(self.root.rglob("*.mdl"), key=lambda path: path.as_posix())
        )
        try:
            return {
                path: hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest() for path in paths
            }
        except (OSError, UnicodeError) as error:
            raise StaleChangeSetError(f"Could not verify workspace source fingerprints: {error}") from error

    @staticmethod
    def _write_temporary_file(destination: Path, content: bytes) -> Path:
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=destination.parent,
                prefix=".modelable-edit-",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
            return temporary_path
        except Exception:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise

    @classmethod
    def _rollback_replacements(
        cls,
        replaced_paths: list[Path],
        originals: dict[Path, tuple[bool, bytes]],
    ) -> list[str]:
        errors: list[str] = []
        for path in reversed(replaced_paths):
            existed, content = originals[path]
            restoration: Path | None = None
            try:
                if existed:
                    restoration = cls._write_temporary_file(path, content)
                    os.replace(restoration, path)
                else:
                    path.unlink(missing_ok=True)
            except Exception as error:
                errors.append(f"{path}: {error}")
            finally:
                if restoration is not None:
                    restoration.unlink(missing_ok=True)
        return errors

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

    def _apply_create_projection(
        self,
        documents: dict[Path, _EditableDocument],
        operation: CreateProjection,
    ) -> tuple[Path, ChangedDefinition]:
        path, domain = self._find_domain_document(documents, operation.domain)
        if (
            operation.name in domain.models
            or operation.name in domain.projections
            or any(declaration.name == operation.name for declaration in domain.semantic_types)
        ):
            raise WorkspaceEditError(f"Definition {operation.domain}.{operation.name} already exists")
        if operation.version <= 0:
            raise WorkspaceEditError("Projection version must be positive")

        fields = [self._projection_field(field) for field in operation.fields]

        version = ProjectionVersion(
            version=operation.version,
            source=SourceRef(
                model=operation.source.model,
                version=VersionExact(version=operation.source.version),
                alias=operation.source.alias,
            ),
            joins=[self._projection_join(join) for join in operation.joins],
            fields=fields,
            where=operation.where,
            group_by=list(operation.group_by),
        )
        domain.projections[operation.name] = [version]
        ref = f"{operation.domain}.{operation.name}@{operation.version}"
        return path, ChangedDefinition(ref=ref, reason="created projection")

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

    def _apply_rename_definition(
        self,
        documents: dict[Path, _EditableDocument],
        operation: RenameDefinition,
        *,
        edit_mode: str,
    ) -> tuple[Path, ChangedDefinition, tuple[str, ...]]:
        if edit_mode != "draft":
            raise WorkspaceEditError(f"Cannot rename {operation.target}; definition renames require draft mode")
        definition_ref = parse_model_ref(operation.target)
        path, domain = self._find_domain_document(documents, definition_ref.domain)
        generated_names = {
            f"{declaration.model}{suffix}"
            for declaration in domain.auto_projections
            for target in declaration.targets
            for suffix in [
                {
                    "db": "Db",
                    "request": "Request",
                    "reply": "Reply",
                    "event": "Event",
                }[target.kind]
            ]
        }
        if (
            operation.new_name in domain.models
            or operation.new_name in domain.projections
            or any(declaration.name == operation.new_name for declaration in domain.semantic_types)
            or operation.new_name in generated_names
        ):
            raise WorkspaceEditError(f"Definition {definition_ref.domain}.{operation.new_name} already exists")

        if definition_ref.name in domain.models:
            self._find_model_version_document(documents, operation.target)
            old_refs = tuple(
                f"{definition_ref.domain}.{definition_ref.name}@{version.version}"
                for version in domain.models[definition_ref.name]
            )
            domain.models[operation.new_name] = domain.models.pop(definition_ref.name)
            for index_declaration in domain.index_decls:
                if index_declaration.model == definition_ref.name:
                    index_declaration.model = operation.new_name
            for auto_projection in domain.auto_projections:
                if auto_projection.model == definition_ref.name:
                    auto_projection.model = operation.new_name
        elif definition_ref.name in domain.projections:
            self._find_projection_version_document(documents, operation.target)
            old_refs = tuple(
                f"{definition_ref.domain}.{definition_ref.name}@{version.version}"
                for version in domain.projections[definition_ref.name]
            )
            domain.projections[operation.new_name] = domain.projections.pop(definition_ref.name)
        else:
            raise WorkspaceEditError(f"Unknown model or projection version: {operation.target}")

        new_ref = f"{definition_ref.domain}.{operation.new_name}@{definition_ref.version}"
        return (
            path,
            ChangedDefinition(ref=new_ref, reason=f"renamed definition {operation.target}"),
            old_refs,
        )

    def _apply_set_projection_source(
        self,
        documents: dict[Path, _EditableDocument],
        operation: SetProjectionSource,
        *,
        edit_mode: str,
        editable_refs: set[str],
    ) -> tuple[Path, ChangedDefinition]:
        path, version = self._editable_projection(
            documents,
            operation.target,
            edit_mode=edit_mode,
            editable_refs=editable_refs,
        )
        version.source = SourceRef(
            model=operation.source.model,
            version=VersionExact(version=operation.source.version),
            alias=operation.source.alias,
        )
        return path, ChangedDefinition(ref=operation.target, reason="set projection source")

    def _apply_add_projection_field(
        self,
        documents: dict[Path, _EditableDocument],
        operation: AddProjectionField,
        *,
        edit_mode: str,
        editable_refs: set[str],
    ) -> tuple[Path, ChangedDefinition]:
        path, version = self._editable_projection(
            documents,
            operation.target,
            edit_mode=edit_mode,
            editable_refs=editable_refs,
        )
        if any(field.name == operation.field.name for field in version.fields):
            raise WorkspaceEditError(f"Field {operation.field.name} already exists on {operation.target}")
        version.fields.append(self._projection_field(operation.field))
        return path, ChangedDefinition(ref=operation.target, reason=f"added field {operation.field.name}")

    def _apply_set_projection_mapping(
        self,
        documents: dict[Path, _EditableDocument],
        operation: SetProjectionMapping,
        *,
        edit_mode: str,
        editable_refs: set[str],
    ) -> tuple[Path, ChangedDefinition]:
        path, _, field = self._editable_projection_field(
            documents,
            operation.target,
            operation.field,
            edit_mode=edit_mode,
            editable_refs=editable_refs,
        )
        field.mapping = self._projection_mapping(operation.mapping)
        return path, ChangedDefinition(ref=operation.target, reason=f"set mapping for field {operation.field}")

    def _apply_add_projection_join(
        self,
        documents: dict[Path, _EditableDocument],
        operation: AddProjectionJoin,
        *,
        edit_mode: str,
        editable_refs: set[str],
    ) -> tuple[Path, ChangedDefinition]:
        path, version = self._editable_projection(
            documents,
            operation.target,
            edit_mode=edit_mode,
            editable_refs=editable_refs,
        )
        aliases = {version.source.alias, *(join.alias for join in version.joins)}
        if operation.join.alias in aliases:
            raise WorkspaceEditError(f"Projection alias {operation.join.alias} already exists on {operation.target}")
        version.joins.append(self._projection_join(operation.join))
        return path, ChangedDefinition(ref=operation.target, reason=f"added join {operation.join.alias}")

    def _apply_set_projection_filter(
        self,
        documents: dict[Path, _EditableDocument],
        operation: SetProjectionFilter,
        *,
        edit_mode: str,
        editable_refs: set[str],
    ) -> tuple[Path, ChangedDefinition]:
        path, version = self._editable_projection(
            documents,
            operation.target,
            edit_mode=edit_mode,
            editable_refs=editable_refs,
        )
        version.where = operation.expression
        return path, ChangedDefinition(ref=operation.target, reason="set projection filter")

    def _apply_set_projection_grouping(
        self,
        documents: dict[Path, _EditableDocument],
        operation: SetProjectionGrouping,
        *,
        edit_mode: str,
        editable_refs: set[str],
    ) -> tuple[Path, ChangedDefinition]:
        path, version = self._editable_projection(
            documents,
            operation.target,
            edit_mode=edit_mode,
            editable_refs=editable_refs,
        )
        version.group_by = list(operation.fields)
        return path, ChangedDefinition(ref=operation.target, reason="set projection grouping")

    def _apply_append_projection_version(
        self,
        documents: dict[Path, _EditableDocument],
        operation: AppendProjectionVersion,
    ) -> tuple[Path, ChangedDefinition]:
        path, domain, source = self._find_projection_version_document(documents, operation.source)
        source_ref = parse_model_ref(operation.source)
        versions = domain.projections[source_ref.name]
        next_version = max(version.version for version in versions) + 1
        if operation.version != next_version:
            raise WorkspaceEditError(
                f"Projection version {operation.version} is not the next version for "
                f"{source_ref.domain}.{source_ref.name}; expected {next_version}"
            )
        appended = source.model_copy(deep=True)
        appended.version = operation.version
        appended.protobuf_reservations = None
        versions.append(appended)
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
        if self._is_projection_ref(documents, operation.target):
            path, projection, projection_field = self._editable_projection_field(
                documents,
                operation.target,
                operation.field,
                edit_mode=edit_mode,
                editable_refs=editable_refs,
            )
            if any(candidate.name == operation.new_name for candidate in projection.fields):
                raise WorkspaceEditError(f"Field {operation.new_name} already exists on {operation.target}")
            projection_field.name = operation.new_name
            return path, ChangedDefinition(
                ref=operation.target,
                reason=f"renamed field {operation.field} to {operation.new_name}",
            )
        path, model, model_field = self._editable_model_field(
            documents,
            operation.target,
            operation.field,
            edit_mode=edit_mode,
            editable_refs=editable_refs,
        )
        if any(candidate.name == operation.new_name for candidate in model.fields):
            raise WorkspaceEditError(f"Field {operation.new_name} already exists on {operation.target}")
        model_field.name = operation.new_name
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
        if self._is_projection_ref(documents, operation.target):
            path, projection, projection_field = self._editable_projection_field(
                documents,
                operation.target,
                operation.field,
                edit_mode=edit_mode,
                editable_refs=editable_refs,
            )
            projection.fields = [candidate for candidate in projection.fields if candidate is not projection_field]
            return path, ChangedDefinition(ref=operation.target, reason=f"removed field {operation.field}")
        path, model, model_field = self._editable_model_field(
            documents,
            operation.target,
            operation.field,
            edit_mode=edit_mode,
            editable_refs=editable_refs,
        )
        model.fields = [candidate for candidate in model.fields if candidate is not model_field]
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
        if self._is_projection_ref(documents, operation.target):
            path, _, projection_field = self._editable_projection_field(
                documents,
                operation.target,
                operation.field,
                edit_mode=edit_mode,
                editable_refs=editable_refs,
            )
            projection_field.annotations = [annotation.model_copy(deep=True) for annotation in operation.annotations]
            return path, ChangedDefinition(
                ref=operation.target,
                reason=f"set annotations on field {operation.field}",
            )
        path, _, model_field = self._editable_model_field(
            documents,
            operation.target,
            operation.field,
            edit_mode=edit_mode,
            editable_refs=editable_refs,
        )
        model_field.annotations = [annotation.model_copy(deep=True) for annotation in operation.annotations]
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

    def _editable_projection(
        self,
        documents: dict[Path, _EditableDocument],
        target: str,
        *,
        edit_mode: str,
        editable_refs: set[str],
    ) -> tuple[Path, ProjectionVersion]:
        if edit_mode != "draft" and target not in editable_refs:
            raise WorkspaceEditError(
                f"Cannot edit existing projection version {target}; append a new version or use draft mode"
            )
        path, _, version = self._find_projection_version_document(documents, target)
        return path, version

    def _editable_projection_field(
        self,
        documents: dict[Path, _EditableDocument],
        target: str,
        field_name: str,
        *,
        edit_mode: str,
        editable_refs: set[str],
    ) -> tuple[Path, ProjectionVersion, ProjectionField]:
        path, version = self._editable_projection(
            documents,
            target,
            edit_mode=edit_mode,
            editable_refs=editable_refs,
        )
        field = next((candidate for candidate in version.fields if candidate.name == field_name), None)
        if field is None:
            raise WorkspaceEditError(f"Unknown field {field_name} on {target}")
        return path, version, field

    @staticmethod
    def _projection_mapping(mapping: ProjectionMappingSpec) -> DirectMapping | ComputedMapping:
        if isinstance(mapping, DirectMappingSpec):
            return DirectMapping(source_alias=mapping.source_alias, source_field=mapping.source_field)
        if isinstance(mapping, ComputedMappingSpec):
            return ComputedMapping(expression=mapping.expression)
        raise WorkspaceEditError(f"Unsupported projection mapping: {mapping.kind}")

    @classmethod
    def _projection_field(cls, field: ProjectionFieldSpec) -> ProjectionField:
        return ProjectionField(
            name=field.name,
            mapping=cls._projection_mapping(field.mapping),
            annotations=[annotation.model_copy(deep=True) for annotation in field.annotations],
        )

    @staticmethod
    def _projection_join(join: ProjectionJoinSpec) -> JoinRef:
        return JoinRef(
            model=join.model,
            version=VersionExact(version=join.version),
            alias=join.alias,
            on=join.on,
            join_kind=join.join_kind,
            cardinality=join.cardinality,
            annotations=[annotation.model_copy(deep=True) for annotation in join.annotations],
        )

    @staticmethod
    def _is_projection_ref(documents: dict[Path, _EditableDocument], ref: str) -> bool:
        try:
            parsed = parse_model_ref(ref)
        except (TypeError, ValueError) as error:
            raise WorkspaceEditError(str(error)) from error
        return any(
            version.version == parsed.version
            for document in documents.values()
            for domain in document.mdl.domains
            if domain.name == parsed.domain
            for version in domain.projections.get(parsed.name, [])
        )

    @staticmethod
    def _resolve_renamed_ref(ref: str, renamed_refs: dict[str, str]) -> str:
        resolved = ref
        visited: set[str] = set()
        while resolved in renamed_refs and resolved not in visited:
            visited.add(resolved)
            resolved = renamed_refs[resolved]
        if "@" not in resolved:
            return resolved
        definition, version = resolved.rsplit("@", 1)
        visited.clear()
        while definition in renamed_refs and definition not in visited:
            visited.add(definition)
            definition = renamed_refs[definition]
        resolved = f"{definition}@{version}"
        return resolved

    @classmethod
    def _remap_operation_refs(
        cls,
        operation: Operation,
        renamed_refs: dict[str, str],
    ) -> Operation:
        if not renamed_refs:
            return operation
        if hasattr(operation, "target"):
            target = cls._resolve_renamed_ref(operation.target, renamed_refs)
            if target != operation.target:
                operation = operation.model_copy(update={"target": target})
        if isinstance(operation, (AppendModelVersion, AppendProjectionVersion)):
            source_ref = cls._resolve_renamed_ref(operation.source, renamed_refs)
            return operation.model_copy(update={"source": source_ref})
        if isinstance(operation, (CreateProjection, SetProjectionSource)):
            source_spec = operation.source.model_copy(
                update={"model": cls._resolve_renamed_ref(operation.source.model, renamed_refs)}
            )
            update: dict[str, object] = {"source": source_spec}
            if isinstance(operation, CreateProjection):
                update["joins"] = [
                    join.model_copy(update={"model": cls._resolve_renamed_ref(join.model, renamed_refs)})
                    for join in operation.joins
                ]
            return operation.model_copy(update=update)
        if isinstance(operation, AddProjectionJoin):
            join = operation.join.model_copy(
                update={"model": cls._resolve_renamed_ref(operation.join.model, renamed_refs)}
            )
            return operation.model_copy(update={"join": join})
        return operation

    @staticmethod
    def _impact_severity(status: str) -> int:
        return {
            "compatible": 1,
            "affected": 2,
            "broken": 3,
            "breaking": 3,
        }.get(status, 0)

    @staticmethod
    def _projection_dependents_transitive(
        mdl: MdlFile,
        root_ref: str,
    ) -> list[tuple[tuple[str, str, int], str, bool]]:
        queue = [(dependent, root_ref, True) for dependent in find_projection_dependents(mdl, root_ref)]
        results: list[tuple[tuple[str, str, int], str, bool]] = []
        seen: set[str] = set()
        while queue:
            dependent, parent_ref, is_direct = queue.pop(0)
            dependent_ref = f"{dependent[0]}.{dependent[1]}@{dependent[2]}"
            if dependent_ref in seen:
                continue
            seen.add(dependent_ref)
            results.append((dependent, parent_ref, is_direct))
            queue.extend((child, dependent_ref, False) for child in find_projection_dependents(mdl, dependent_ref))
        return results

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
    def _find_projection_version_document(
        documents: dict[Path, _EditableDocument],
        ref: str,
    ) -> tuple[Path, DomainDef, ProjectionVersion]:
        try:
            projection_ref = parse_model_ref(ref)
        except (TypeError, ValueError) as error:
            raise WorkspaceEditError(str(error)) from error
        matches: list[tuple[Path, DomainDef, ProjectionVersion]] = []
        for path, document in documents.items():
            for domain in document.mdl.domains:
                if domain.name != projection_ref.domain:
                    continue
                for version in domain.projections.get(projection_ref.name, []):
                    if version.version == projection_ref.version:
                        matches.append((path, domain, version))
        if not matches:
            raise WorkspaceEditError(f"Unknown projection version: {ref}")
        if len(matches) > 1:
            raise WorkspaceEditError(f"Projection version {ref} is defined in multiple source files")
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
