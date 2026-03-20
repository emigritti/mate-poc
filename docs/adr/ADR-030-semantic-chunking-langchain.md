# ADR-030 — Semantic Chunking with LangChain RecursiveCharacterTextSplitter

| Field        | Value                                              |
|--------------|----------------------------------------------------|
| **Status**   | Accepted                                           |
| **Date**     | 2026-03-20                                         |
| **Tags**     | chunking, langchain, kb, document-parser, phase2   |

## Context
Fixed-size character splitting (1000 chars, 200 overlap) cuts through headings, paragraphs,
and sentences arbitrarily. Chunks containing incomplete thoughts degrade RAG retrieval quality.

## Decision
Add `semantic_chunk()` using `langchain-text-splitters` `RecursiveCharacterTextSplitter`
with separator priority: `["\n## ", "\n### ", "\n\n", "\n", ". ", " "]`.
The chunker attempts to split at heading boundaries first, then paragraph breaks, then
sentences, before falling back to character-level. Parameters (chunk_size, chunk_overlap)
remain identical to `chunk_text()` so no config changes are needed.

`chunk_text()` is preserved unchanged for backward compatibility.
Existing KB documents are not re-chunked; only new uploads use semantic chunking.

## Dependency
`langchain-text-splitters==0.3.8` — lightweight sub-package (no LLM deps).
BM25Plus used instead of BM25Okapi due to IDF collapse on small corpora (all-term overlap → zero scores with Okapi; smoothed IDF in Plus avoids this).

## Validation Plan
- Unit tests: `tests/test_semantic_chunk.py` — 7 tests covering heading boundaries, paragraph boundaries, empty input, backward compat

## Rollback
Revert `routers/kb.py` to call `chunk_text()`. No data migration needed.
