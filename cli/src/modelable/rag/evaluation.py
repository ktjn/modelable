from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import yaml

from modelable.rag.retriever import RetrievedChunk, SearchMode


@dataclass(slots=True, frozen=True)
class EvaluationCase:
    question: str
    relevant_chunk_ids: tuple[str, ...]
    category: str = "challenge"


@dataclass(slots=True, frozen=True)
class EvaluationFailure:
    question: str
    category: str
    relevant_chunk_ids: tuple[str, ...]
    returned_chunk_ids: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class EvaluationMetrics:
    category: str
    case_count: int
    recall_at_5: float
    recall_at_10: float
    mean_reciprocal_rank: float
    ndcg_at_10: float
    zero_result_rate: float
    duplicate_source_rate: float


@dataclass(slots=True, frozen=True)
class EvaluationReport:
    case_count: int
    recall_at_5: float
    recall_at_10: float
    mean_reciprocal_rank: float
    ndcg_at_10: float
    zero_result_rate: float
    duplicate_source_rate: float
    category_reports: tuple[EvaluationMetrics, ...] = ()
    failures: tuple[EvaluationFailure, ...] = ()


class _Retriever(Protocol):
    def search(self, query: str, *, limit: int, mode: SearchMode = "lexical") -> list[RetrievedChunk]: ...


def evaluate_retrieval(
    retriever: _Retriever,
    cases: Sequence[EvaluationCase],
    *,
    limit: int = 10,
    mode: SearchMode = "lexical",
) -> EvaluationReport:
    if limit < 10:
        raise ValueError("limit must be at least 10 for the standard metrics")

    results = [(case, retriever.search(case.question, limit=limit, mode=mode)) for case in cases]
    overall = _summarize("overall", results, limit=limit)
    category_reports = tuple(
        _summarize(
            category,
            [(case, hits) for case, hits in results if case.category == category],
            limit=limit,
        )
        for category in sorted({case.category for case in cases})
    )
    failures = tuple(
        EvaluationFailure(
            question=case.question,
            category=case.category,
            relevant_chunk_ids=case.relevant_chunk_ids,
            returned_chunk_ids=tuple(hit.external_id for hit in hits[:limit]),
        )
        for case, hits in results
        if not any(hit.external_id in set(case.relevant_chunk_ids) for hit in hits[:10])
    )
    return EvaluationReport(
        case_count=overall.case_count,
        recall_at_5=overall.recall_at_5,
        recall_at_10=overall.recall_at_10,
        mean_reciprocal_rank=overall.mean_reciprocal_rank,
        ndcg_at_10=overall.ndcg_at_10,
        zero_result_rate=overall.zero_result_rate,
        duplicate_source_rate=overall.duplicate_source_rate,
        category_reports=category_reports,
        failures=failures,
    )


def evaluate_retrieval_modes(
    retriever: _Retriever,
    cases: Sequence[EvaluationCase],
    *,
    modes: Sequence[SearchMode] = ("lexical", "vector", "hybrid"),
    limit: int = 10,
) -> dict[str, EvaluationReport]:
    """Evaluate identical cases independently for each requested retrieval mode."""
    return {mode: evaluate_retrieval(retriever, cases, limit=limit, mode=mode) for mode in modes}


def _summarize(
    category: str,
    results: Sequence[tuple[EvaluationCase, list[RetrievedChunk]]],
    *,
    limit: int,
) -> EvaluationMetrics:
    if not results:
        return EvaluationMetrics(category, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    recall_at_5 = 0
    recall_at_10 = 0
    reciprocal_ranks: list[float] = []
    ndcg_scores: list[float] = []
    zero_results = 0
    duplicate_fractions: list[float] = []
    for case, hits in results:
        relevant_ids = set(case.relevant_chunk_ids)
        hit_ids = [hit.external_id for hit in hits]
        recall_at_5 += int(any(hit_id in relevant_ids for hit_id in hit_ids[:5]))
        recall_at_10 += int(any(hit_id in relevant_ids for hit_id in hit_ids[:10]))
        first_relevant_rank = next(
            (rank for rank, hit_id in enumerate(hit_ids, start=1) if hit_id in relevant_ids),
            None,
        )
        reciprocal_ranks.append(1.0 / first_relevant_rank if first_relevant_rank is not None else 0.0)
        ndcg_scores.append(_ndcg_at_10(hit_ids, relevant_ids))
        if not hits:
            zero_results += 1
            duplicate_fractions.append(0.0)
            continue
        seen_sources: set[str] = set()
        duplicate_count = 0
        for hit in hits[:limit]:
            duplicate_count += int(hit.source_path in seen_sources)
            seen_sources.add(hit.source_path)
        duplicate_fractions.append(duplicate_count / len(hits[:limit]))

    case_count = len(results)
    return EvaluationMetrics(
        category=category,
        case_count=case_count,
        recall_at_5=recall_at_5 / case_count,
        recall_at_10=recall_at_10 / case_count,
        mean_reciprocal_rank=sum(reciprocal_ranks) / case_count,
        ndcg_at_10=sum(ndcg_scores) / case_count,
        zero_result_rate=zero_results / case_count,
        duplicate_source_rate=sum(duplicate_fractions) / case_count,
    )


def _ndcg_at_10(hit_ids: list[str], relevant_ids: set[str]) -> float:
    ranked_relevance = [int(hit_id in relevant_ids) for hit_id in hit_ids[:10]]
    dcg = sum(relevance / math.log2(rank + 2) for rank, relevance in enumerate(ranked_relevance))
    ideal_count = min(len(relevant_ids), 10)
    ideal_dcg = sum(1.0 / math.log2(rank + 2) for rank in range(ideal_count))
    return dcg / ideal_dcg if ideal_dcg else 0.0


def load_evaluation_cases(path: Path) -> list[EvaluationCase]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ValueError(f"could not load evaluation corpus {path}: {error}") from error

    if not isinstance(raw, dict) or not isinstance(raw.get("cases"), list):
        raise ValueError(f"evaluation corpus {path} must contain a cases list")
    if not raw["cases"]:
        raise ValueError(f"evaluation corpus {path} must contain at least one evaluation case")

    cases: list[EvaluationCase] = []
    for index, item in enumerate(raw["cases"]):
        if not isinstance(item, dict):
            raise ValueError(f"evaluation case {index} must be an object")
        question = item.get("question")
        relevant_chunks = item.get("relevant_chunks")
        category = item.get("category", "challenge")
        if not isinstance(question, str) or not question.strip():
            raise ValueError(f"evaluation case {index} question must be non-empty")
        if not isinstance(category, str) or not category.strip():
            raise ValueError(f"evaluation case {index} category must be non-empty")
        if (
            not isinstance(relevant_chunks, list)
            or not relevant_chunks
            or not all(isinstance(chunk_id, str) and chunk_id.strip() for chunk_id in relevant_chunks)
        ):
            raise ValueError(f"evaluation case {index} relevant_chunks must be non-empty strings")
        cases.append(EvaluationCase(question.strip(), tuple(relevant_chunks), category.strip()))
    return cases
