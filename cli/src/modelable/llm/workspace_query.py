from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from modelable.compat.checker import check_model_version_compatibility, find_projection_dependents
from modelable.compiler.workspace import Workspace
from modelable.diagnostics.model import render_diagnostic
from modelable.llm.context import (
    ModelRef,
    build_model_summary,
    build_projection_summary,
    build_workspace_summary,
    parse_model_ref,
)
from modelable.llm.conversation_plan import QueryPlan
from modelable.parser.ir import DomainDef, ProjectionVersion
from modelable.planner.lineage import build_projection_lineage


@dataclass(frozen=True)
class QueryResult:
    text: str
    refs: tuple[str, ...]


class WorkspaceQueryService:
    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    def execute(self, plan: QueryPlan) -> QueryResult:
        expected_refs = {
            "summary": (0, 1, "exactly zero or one reference"),
            "ownership": (1, 1, "exactly one reference"),
            "lineage": (1, 1, "exactly one reference"),
            "dependents": (1, 1, "exactly one reference"),
            "indexes": (1, 1, "exactly one reference"),
            "compatibility": (2, 2, "exactly two references"),
            "validation": (0, 0, "exactly zero references"),
        }
        minimum, maximum, description = expected_refs[plan.query_kind]
        if not minimum <= len(plan.refs) <= maximum:
            return QueryResult(
                text=f"{plan.query_kind} queries require {description}; received {len(plan.refs)}.",
                refs=tuple(plan.refs),
            )

        handlers = {
            "summary": self._summary,
            "ownership": self._ownership,
            "lineage": self._lineage,
            "dependents": self._dependents,
            "indexes": self._indexes,
            "compatibility": self._compatibility,
            "validation": self._validation,
        }
        return QueryResult(text=handlers[plan.query_kind](plan.refs), refs=tuple(plan.refs))

    def _summary(self, refs: list[str]) -> str:
        if not refs:
            return build_workspace_summary(self.workspace) or "Workspace is empty."
        resolved = self._resolve(refs[0])
        if isinstance(resolved, str):
            return resolved
        _, _, definition_kind, _ = resolved
        if definition_kind == "model":
            return build_model_summary(self.workspace, refs[0])
        return build_projection_summary(self.workspace, refs[0])

    def _ownership(self, refs: list[str]) -> str:
        resolved = self._resolve(refs[0])
        if isinstance(resolved, str):
            return resolved
        domain, model_ref, _, _ = resolved
        owner = domain.owner or "unspecified"
        return f"{model_ref.domain}.{model_ref.name}@{model_ref.version} is owned by {owner}."

    def _lineage(self, refs: list[str]) -> str:
        resolved = self._resolve(refs[0])
        if isinstance(resolved, str):
            return resolved
        domain, model_ref, definition_kind, definition = resolved
        if definition_kind != "projection":
            return f"Lineage queries require a projection reference; received {refs[0]}."
        lineage = build_projection_lineage(
            domain.name,
            model_ref.name,
            cast(ProjectionVersion, definition),
            self.workspace.mdl,
        )
        lines = [f"{refs[0]} lineage:"]
        for field in lineage.fields:
            sources = ", ".join(field.lineage) if field.lineage else "unresolved"
            if field.expression:
                sources = f"{sources} via {field.expression}"
            lines.append(f"- {field.field_name}: {sources}")
        return "\n".join(lines)

    def _dependents(self, refs: list[str]) -> str:
        resolved = self._resolve(refs[0])
        if isinstance(resolved, str):
            return resolved
        _, _, definition_kind, _ = resolved
        if definition_kind != "model":
            return f"Dependent queries require a model reference; received {refs[0]}."
        dependents = find_projection_dependents(self.workspace.mdl, refs[0])
        if not dependents:
            return f"No projections currently depend on {refs[0]}."
        return "Dependents:\n" + "\n".join(
            f"- {domain}.{projection}@{version}" for domain, projection, version in dependents
        )

    def _indexes(self, refs: list[str]) -> str:
        resolved = self._resolve(refs[0])
        if isinstance(resolved, str):
            return resolved
        domain, model_ref, definition_kind, _ = resolved
        if definition_kind != "model":
            return f"Index queries require a model reference; received {refs[0]}."
        declaration = next(
            (
                index
                for index in domain.index_decls
                if index.model == model_ref.name and index.version == model_ref.version
            ),
            None,
        )
        if declaration is None:
            return f"No indexes are declared for {refs[0]}."
        lines = [f"{refs[0]} indexes:"]
        if declaration.primary:
            lines.append(f"- primary: {', '.join(declaration.primary)}")
        for index in declaration.secondary:
            details = [f"key: {', '.join(index.key)}"]
            if index.sort:
                details.append("sort: " + ", ".join(f"{field.field} {field.direction}" for field in index.sort))
            details.append(f"unique: {str(index.unique).lower()}")
            lines.append(f"- {index.name} ({'; '.join(details)})")
        return "\n".join(lines)

    def _compatibility(self, refs: list[str]) -> str:
        try:
            old_ref = parse_model_ref(refs[0])
            new_ref = parse_model_ref(refs[1])
        except TypeError, ValueError:
            return "Compatibility refs must use domain.Model@version syntax."
        if (old_ref.domain, old_ref.name) != (new_ref.domain, new_ref.name):
            return f"Compatibility queries require two versions of the same model; received {refs[0]} and {refs[1]}."
        old_resolution = self._resolve(refs[0], expected_kind="model")
        if isinstance(old_resolution, str):
            return old_resolution
        new_resolution = self._resolve(refs[1], expected_kind="model")
        if isinstance(new_resolution, str):
            return new_resolution
        try:
            report = check_model_version_compatibility(
                self.workspace.mdl,
                old_ref.domain,
                old_ref.name,
                old_ref.version,
                new_ref.version,
            )
        except LookupError as error:
            return str(error)
        lines = [f"{refs[0]} -> {refs[1]} compatibility: {report.status}"]
        lines.extend(f"- {finding}" for finding in report.findings)
        return "\n".join(lines)

    def _validation(self, refs: list[str]) -> str:
        if not self.workspace.errors:
            return "Workspace validation passed with no diagnostics."
        return "Workspace validation diagnostics:\n" + "\n".join(
            f"- {render_diagnostic(diagnostic)}" for diagnostic in self.workspace.errors
        )

    def _resolve(
        self,
        ref: str,
        *,
        expected_kind: str | None = None,
    ) -> tuple[DomainDef, ModelRef, str, object] | str:
        try:
            model_ref = parse_model_ref(ref)
        except TypeError, ValueError:
            return f"Invalid reference {ref!r}; expected domain.Model@version."
        domain = next(
            (candidate for candidate in self.workspace.mdl.domains if candidate.name == model_ref.domain), None
        )
        if domain is None:
            return f"Unknown model or projection reference: {ref}"
        for definition_kind, definitions in (
            ("model", domain.models),
            ("projection", domain.projections),
        ):
            if expected_kind is not None and definition_kind != expected_kind:
                continue
            versions = definitions.get(model_ref.name)
            if versions:
                definition = next(
                    (candidate for candidate in versions if candidate.version == model_ref.version),
                    None,
                )
                if definition is not None:
                    return domain, model_ref, definition_kind, definition
        return f"Unknown model or projection reference: {ref}"
