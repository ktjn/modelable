# 1. RAG Retrieval Evaluation Design

## Scope

Add the Phase 6 evaluation harness from the full Modelable RAG plan. It will
measure the existing lexical `DocumentationRetriever` against a versioned
question/relevance corpus without an LLM. This slice establishes a reproducible
baseline for later vector, hybrid, and prompt work.

## Evaluation model

`EvaluationCase` contains a question and one or more relevant stable chunk
external IDs. `evaluate_retrieval` executes cases in file order and returns an
`EvaluationReport` with case count, Recall@5, Recall@10, MRR, nDCG@10,
zero-result rate, and duplicate-source rate.

Metrics use binary relevance. Recall is the fraction of cases with at least one
relevant result in the cutoff. MRR uses the reciprocal rank of the first
relevant result, or zero. nDCG@10 uses the standard binary-gain DCG and the
ideal ranking for the case's relevant-ID count. Zero-result rate is the
fraction of cases with no returned hits. Duplicate-source rate is the mean
fraction of returned hits whose `source_path` was already seen earlier in the
same result list.

## Corpus and command

Store the initial 50-case corpus at
`cli/src/modelable/rag/evaluation_corpus.yaml`. Keep each relevant ID stable
and source-addressable. Add `modelable docs-eval INDEX CORPUS` with `--limit`
and optional `--json`; it loads the corpus, evaluates the index, and reports
the metrics without changing the index or calling an LLM.

## ADR applicability

No ADR is needed: this is a deterministic measurement layer over the already
approved retriever and introduces no deployment, storage, or security model.
