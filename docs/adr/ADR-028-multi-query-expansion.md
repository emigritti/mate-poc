# ADR-028 — Multi-Query Expansion: 2 Template + 2 LLM Variants

| Field        | Value                                          |
|--------------|------------------------------------------------|
| **Status**   | Accepted                                       |
| **Date**     | 2026-03-20                                     |
| **Tags**     | rag, query-expansion, llm, phase2              |

## Context
A single query over requirement descriptions misses semantically related content.
Multi-query retrieval (2-3 variants) consistently improves recall in RAG literature.

## Decision
Generate 4 query variants per integration: (1) original query text, (2) structured
template "{source} to {target} {category} integration pattern", (3+4) two LLM-generated
rephrasings (technical + business perspective) via a single lightweight Ollama call
(tag_llm settings: low timeout, low num_predict).

LLM variants are optional — if the call fails, only the 2 deterministic templates are
used. This ensures no pipeline dependency on LLM availability for retrieval.

## Validation Plan
- Unit tests: `test_expand_queries_always_has_two_templates`, `test_expand_queries_adds_llm_variants_on_success`, `test_expand_queries_fallback_on_llm_failure`

## Rollback
Revert `_expand_queries` to return `[query_text]` only. No data changes.
