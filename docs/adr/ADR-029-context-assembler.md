# ADR-029 — ContextAssembler: Unified Context Fusion with Token Budget

| Field        | Value                                           |
|--------------|-------------------------------------------------|
| **Status**   | Accepted                                        |
| **Date**     | 2026-03-20                                      |
| **Tags**     | rag, context, prompt-engineering, phase2        |

## Context
The previous pipeline concatenated approved docs, KB chunks, and URL content as raw
strings with no structure. The LLM could not distinguish pattern types or prioritise
by relevance. Context regularly exceeded the token budget, causing truncation at an
arbitrary character boundary.

## Decision
`ContextAssembler.assemble()` takes scored chunks from all sources, sorts by relevance,
respects `ollama_rag_max_chars` budget, and formats output with explicit section headers:
"PAST APPROVED EXAMPLES" (style reference) and "BEST PRACTICE PATTERNS" (follow these).
Each chunk carries its score in the header for transparency.

## Validation Plan
- Unit tests: `tests/test_context_assembler.py` — 8 tests covering all assembly scenarios

## Rollback
Revert `run_agentic_rag_flow` to use `build_rag_context()` + `query_kb_context()`.
No data changes.
