from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import yaml

from modelable.rag.retriever import RetrievedChunk


@dataclass(slots=True, frozen=True)
class EvaluationCase:
    question: str
    relevant_chunk_ids: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class EvaluationReport:
    case_count: int
    recall_at_5: float
    recall_at_10: float
    mean_reciprocal_rank: float
    ndcg_at_10: float
    zero_result_rate: float
    duplicate_source_rate: float


class _Retriever(Protocol):
    def search(self, query: str, *, limit: int) -> list[RetrievedChunk]: ...


def evaluate_retrieval(
    retriever: _Retriever,
    cases: Sequence[EvaluationCase],
    *,
    limit: int = 10,
) -> EvaluationReport:
    if limit < 10:
        raise ValueError("limit must be at least 10 for the standard metrics")

    if not cases:
        return EvaluationReport(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    recall_at_5 = 0
    recall_at_10 = 0
    reciprocal_ranks: list[float] = []
    ndcg_scores: list[float] = []
    zero_results = 0
    duplicate_fractions: list[float] = []

    for case in cases:
        hits = retriever.search(case.question, limit=limit)
        relevant_ids = set(case.relevant_chunk_ids)
        hit_ids = [hit.external_id for hit in hits]
        if any(hit_id in relevant_ids for hit_id in hit_ids[:5]):
            recall_at_5 += 1
        if any(hit_id in relevant_ids for hit_id in hit_ids[:10]):
            recall_at_10 += 1

        first_relevant_rank = next(
            (rank for rank, hit_id in enumerate(hit_ids, start=1) if hit_id in relevant_ids),
            None,
        )
        reciprocal_ranks.append(1.0 / first_relevant_rank if first_relevant_rank is not None else 0.0)
        ndcg_scores.append(_ndcg_at_10(hit_ids, relevant_ids))

        if not hits:
            zero_results += 1
            duplicate_fractions.append(0.0)
        else:
            seen_sources: set[str] = set()
            duplicate_count = 0
            for hit in hits[:limit]:
                if hit.source_path in seen_sources:
                    duplicate_count += 1
                seen_sources.add(hit.source_path)
            duplicate_fractions.append(duplicate_count / len(hits[:limit]))

    case_count = len(cases)
    return EvaluationReport(
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
        if not isinstance(question, str) or not question.strip():
            raise ValueError(f"evaluation case {index} question must be non-empty")
        if (
            not isinstance(relevant_chunks, list)
            or not relevant_chunks
            or not all(isinstance(chunk_id, str) and chunk_id.strip() for chunk_id in relevant_chunks)
        ):
            raise ValueError(f"evaluation case {index} relevant_chunks must be non-empty strings")
        cases.append(EvaluationCase(question.strip(), tuple(relevant_chunks)))
    return cases
