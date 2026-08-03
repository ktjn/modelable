"""Deterministic retrieval intent routing."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum

_MUTATION_VERBS = re.compile(r"\b(add|change|create|delete|remove|rename|update|generate|compile|apply|make)\b")
_AUTOMATIC_DOCUMENTATION_SIGNALS = re.compile(
    r"\b(documentation|docs|guide|reference|syntax|configure|configuration|command|option)\b"
)
# Definitional questions ("what is X", "what does X mean") ask for a term's
# meaning rather than an action on the user's own workspace, so they're safe
# to route the same as the keyword-signal questions above.
_DEFINITIONAL_QUESTION_SIGNALS = re.compile(r"\bwhat\s+(is|are|does|do)\b|\bmeaning of\b|\bdefine\b")

_EXPLICIT_DOCS_COMMAND = "/docs"
_SLASH_COMMAND_REASON = "slash_command"
_AUTOMATIC_DISABLED_REASON = "automatic_disabled"
_EXPLICIT_DOCS_REASON = "explicit_docs_command"
_BLANK_DOCS_REASON = "blank_docs_command"
_MUTATION_REASON = "mutation_like_message"
_AUTOMATIC_DOCUMENTATION_REASON = "automatic_documentation_signal"
_NO_DOCUMENTATION_SIGNAL_REASON = "no_documentation_signal"


class RetrievalRoute(StrEnum):
    NONE = "none"
    AUTOMATIC_DOCUMENTATION = "automatic_documentation"
    EXPLICIT_DOCUMENTATION = "explicit_documentation"


@dataclass(frozen=True)
class RetrievalDecision:
    route: RetrievalRoute
    reason: str
    question: str


def classify_retrieval_intent(message: str, *, automatic_enabled: bool = True) -> RetrievalDecision:
    normalized = unicodedata.normalize("NFKC", message).strip()
    if not normalized:
        return RetrievalDecision(route=RetrievalRoute.NONE, reason="blank_message", question="")

    lowered = normalized.casefold()
    explicit_question = _extract_explicit_docs_question(normalized, lowered)
    if explicit_question is not None:
        if explicit_question == "":
            return RetrievalDecision(route=RetrievalRoute.NONE, reason=_BLANK_DOCS_REASON, question="")
        return RetrievalDecision(
            route=RetrievalRoute.EXPLICIT_DOCUMENTATION,
            reason=_EXPLICIT_DOCS_REASON,
            question=explicit_question,
        )

    if lowered.startswith("/"):
        return RetrievalDecision(route=RetrievalRoute.NONE, reason=_SLASH_COMMAND_REASON, question="")

    if _MUTATION_VERBS.search(lowered):
        return RetrievalDecision(route=RetrievalRoute.NONE, reason=_MUTATION_REASON, question="")

    if not automatic_enabled:
        return RetrievalDecision(route=RetrievalRoute.NONE, reason=_AUTOMATIC_DISABLED_REASON, question="")

    if (
        _AUTOMATIC_DOCUMENTATION_SIGNALS.search(lowered)
        or _DEFINITIONAL_QUESTION_SIGNALS.search(lowered)
        or "how do i" in lowered
    ):
        return RetrievalDecision(
            route=RetrievalRoute.AUTOMATIC_DOCUMENTATION,
            reason=_AUTOMATIC_DOCUMENTATION_REASON,
            question=" ".join(normalized.split()),
        )

    return RetrievalDecision(route=RetrievalRoute.NONE, reason=_NO_DOCUMENTATION_SIGNAL_REASON, question="")


def _extract_explicit_docs_question(normalized: str, lowered: str) -> str | None:
    if not lowered.startswith(_EXPLICIT_DOCS_COMMAND):
        return None

    command_end = len(_EXPLICIT_DOCS_COMMAND)
    if lowered != _EXPLICIT_DOCS_COMMAND and not lowered[command_end : command_end + 1].isspace():
        return None

    remainder = normalized[command_end:].strip()
    return " ".join(remainder.split())
