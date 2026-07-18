from __future__ import annotations

import difflib
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from modelable.compiler.workspace import (
    Workspace,
    WorkspaceDocumentSource,
    load_workspace,
    load_workspace_from_sources,
)
from modelable.diagnostics.model import Diagnostic, render_diagnostic
from modelable.llm.conversation_plan import ChangeSetPlan, CreateModel
from modelable.llm.render import render_mdl
from modelable.parser.ir import ChangeKind, DomainDef, MdlFile, ModelKind, ModelVersion


class WorkspaceEditError(ValueError):
    pass


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

        for operation in plan.operations:
            if isinstance(operation, CreateModel):
                path, definition = self._apply_create_model(documents, operation)
                changed_paths.add(path)
                changed.append(definition)
                continue
            raise WorkspaceEditError(f"Unsupported workspace operation: {operation.kind}")

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
        return PendingChangeSet(
            change_set_id=change_set_id,
            plan=plan,
            assumptions=tuple(plan.assumptions),
            source_fingerprints=source_fingerprints,
            candidate_sources=rendered_sources,
            changed=changed,
            affected=[],
            compatibility=[],
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
