# 1. RAG Retrieval Baseline Hardening Design

## Scope

Improve the Phase 6 lexical baseline without adding embeddings, prompts, or
LLM calls. The evaluation corpus will distinguish controlled lexical queries
from paraphrase challenges, and reports will expose category metrics and failed
queries. The retriever will normalize ordinary natural-language punctuation so
Searchable field-query syntax is not triggered accidentally.

## Evaluation diagnostics

`EvaluationCase` gains a category, defaulting to `challenge` for backwards
compatibility. The report gains per-category metrics and failed-query records
containing the question, category, relevant IDs, and returned IDs. The CLI
prints category summaries and the first ten failures; JSON includes the full
structured data.

The committed corpus contains 25 `lexical` cases using controlled terms and 25
`challenge` cases using natural-language paraphrases. This makes lexical
retrieval quality measurable without disguising its limits on semantic
paraphrase.

## Query normalization

`DocumentationRetriever.search` replaces punctuation with spaces and collapses
whitespace before passing ordinary queries to Searchable. This prevents a colon
or question mark from changing Searchable's query grammar while preserving
word and hyphen characters.

## ADR applicability

No ADR is needed: this is a measurement and input-normalization refinement of
the approved lexical retriever.
