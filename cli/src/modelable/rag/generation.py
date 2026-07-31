"""Evidence-grounded answer generation for documentation retrieval."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from modelable.llm.provider_types import LLMProvider, LLMRequest
from modelable.rag.retriever import RetrievedChunk

RAG_SYSTEM_PROMPT = """You answer questions only from the supplied documentation evidence.
Cite every factual claim with one or more source labels such as [S1].
If the evidence is insufficient, say so rather than guessing.
"""
INSUFFICIENT_EVIDENCE = "I don't have enough documentation evidence to answer that."


@dataclass(frozen=True, slots=True)
class RagCitation:
    """A source citation attached to a generated answer."""

    label: str
    external_id: str
    url: str
    title: str
    heading: str | None
    score: float


@dataclass(frozen=True, slots=True)
class RagAnswer:
    """Generated answer plus the sources selected for its evidence context."""

    answer: str
    citations: tuple[RagCitation, ...]
    insufficient_evidence: bool


class _Retriever(Protocol):
    def search(self, query: str, *, limit: int = 8) -> list[RetrievedChunk]: ...


def build_evidence_prompt(
    question: str,
    chunks: Sequence[RetrievedChunk],
    *,
    max_context_words: int = 3000,
) -> tuple[str, tuple[RetrievedChunk, ...]]:
    """Build an evidence prompt while admitting only complete chunks."""
    if not question.strip():
        raise ValueError("question must not be blank")
    if max_context_words <= 0:
        raise ValueError("max_context_words must be positive")

    selected: list[RetrievedChunk] = []
    used_words = 0
    for candidate in chunks:
        word_count = len(candidate.content.split())
        if used_words + word_count > max_context_words:
            continue
        selected.append(candidate)
        used_words += word_count

    evidence_sections: list[str] = []
    for index, candidate in enumerate(selected, start=1):
        heading = f" — {candidate.heading}" if candidate.heading else ""
        evidence_sections.append(
            f"[S{index}] {candidate.title}{heading}\n"
            f"URL: {candidate.url}\n"
            f"External ID: {candidate.external_id}\n"
            f"Content:\n{candidate.content}"
        )

    prompt = f"Question:\n{question.strip()}\n\nDocumentation evidence:\n" + (
        "\n\n".join(evidence_sections) if evidence_sections else "(none)"
    )
    return prompt, tuple(selected)


def answer_with_retrieval(
    retriever: _Retriever,
    provider: LLMProvider | None,
    question: str,
    *,
    limit: int = 8,
    max_context_words: int = 3000,
) -> RagAnswer:
    """Retrieve evidence and generate an answer constrained to that evidence."""
    if not question.strip():
        raise ValueError("question must not be blank")
    if limit <= 0:
        raise ValueError("limit must be positive")
    if max_context_words <= 0:
        raise ValueError("max_context_words must be positive")

    chunks = retriever.search(question, limit=limit)
    prompt, selected = build_evidence_prompt(
        question,
        chunks,
        max_context_words=max_context_words,
    )
    if not selected:
        return RagAnswer(INSUFFICIENT_EVIDENCE, (), True)
    if provider is None:
        raise ValueError("LLM provider is required when evidence is available")

    response = provider.complete(LLMRequest(system=RAG_SYSTEM_PROMPT, user=prompt, temperature=0.2))
    answer = response.content.strip() or "No response returned."
    citations = tuple(
        RagCitation(
            label=f"S{index}",
            external_id=chunk.external_id,
            url=chunk.url,
            title=chunk.title,
            heading=chunk.heading,
            score=chunk.score,
        )
        for index, chunk in enumerate(selected, start=1)
    )
    source_lines = [f"- [{citation.label}] {citation.external_id} ({citation.url})" for citation in citations]
    return RagAnswer(f"{answer}\n\nSources:\n" + "\n".join(source_lines), citations, False)
