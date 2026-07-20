from dataclasses import dataclass

from lsprotocol import types

from modelable.language.completion import complete
from modelable.language.dto import (
    CompletionKind,
    LanguageCompletion,
    LanguagePosition,
    LanguageRange,
)
from modelable.lsp.federation import (
    mirror_domain_names,
    mirror_field_names,
    mirror_model_versions,
    mirror_reference_names,
)
from modelable.lsp.workspace import LspWorkspaceIndex

_COMPLETION_KINDS: dict[CompletionKind, types.CompletionItemKind] = {
    "keyword": types.CompletionItemKind.Keyword,
    "annotation": types.CompletionItemKind.Keyword,
    "module": types.CompletionItemKind.Module,
    "class": types.CompletionItemKind.Class,
    "property": types.CompletionItemKind.Field,
    "reference": types.CompletionItemKind.Reference,
    "value": types.CompletionItemKind.Value,
}


@dataclass(frozen=True)
class DesktopCompletionCatalog:
    index: LspWorkspaceIndex

    def domain_names(self) -> tuple[str, ...]:
        return tuple(mirror_domain_names(self.index))

    def references(self) -> tuple[tuple[str, str], ...]:
        return tuple(mirror_reference_names(self.index))

    def model_versions(self) -> tuple[tuple[str, str, int], ...]:
        return tuple(mirror_model_versions(self.index))

    def field_names(self, domain: str, name: str, version: int) -> tuple[str, ...]:
        return tuple(mirror_field_names(self.index, domain, name, version))


def complete_for_desktop(
    index: LspWorkspaceIndex,
    uri: str,
    line: int,
    character: int,
) -> types.CompletionList:
    neutral = complete(
        index.language,
        uri,
        LanguagePosition(line, character),
        DesktopCompletionCatalog(index),
    )
    return to_lsp_completion_list(neutral)


def build_completion(
    index: LspWorkspaceIndex,
    uri: str,
    line: int,
    character: int,
) -> types.CompletionList:
    return complete_for_desktop(index, uri, line, character)


def to_lsp_completion_list(
    completions: tuple[LanguageCompletion, ...],
) -> types.CompletionList:
    return types.CompletionList(
        is_incomplete=False,
        items=[_to_lsp_completion(item) for item in completions],
    )


def _to_lsp_completion(completion: LanguageCompletion) -> types.CompletionItem:
    return types.CompletionItem(
        label=completion.label,
        kind=_COMPLETION_KINDS.get(completion.kind) if completion.kind is not None else None,
        sort_text=completion.sort_text,
        detail=completion.detail,
        documentation=completion.documentation,
        insert_text=completion.label,
        filter_text=completion.label,
        text_edit=_to_lsp_text_edit(completion.label, completion.replacement),
    )


def _to_lsp_text_edit(
    label: str,
    replacement: LanguageRange | None,
) -> types.TextEdit | None:
    if replacement is None:
        return None
    return types.TextEdit(
        range=types.Range(
            start=types.Position(
                line=replacement.start.line,
                character=replacement.start.character,
            ),
            end=types.Position(
                line=replacement.end.line,
                character=replacement.end.character,
            ),
        ),
        new_text=label,
    )
