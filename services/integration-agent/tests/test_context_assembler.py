"""
Unit tests for ContextAssembler (R10 / ADR-029).

Covers:
  - Chunks from all sources are included (approved, kb_file, kb_url)
  - Output respects max_chars budget
  - Higher-scored chunks appear first
  - Source sections formatted with correct headers
  - Empty inputs return empty string
  - Backward compat: build_rag_context() unchanged
"""


def _make_chunk(text: str, score: float, source: str, tags=None):
    from services.retriever import ScoredChunk
    return ScoredChunk(text=text, score=score, source_label=source, tags=tags or [])


def test_context_assembler_empty_inputs_returns_empty():
    from services.rag_service import ContextAssembler
    ca = ContextAssembler()
    result = ca.assemble([], [], [], max_chars=5000)
    assert result == ""


def test_context_assembler_approved_section_present():
    from services.rag_service import ContextAssembler
    ca = ContextAssembler()
    chunks = [_make_chunk("approved doc content", 0.9, "approved")]
    result = ca.assemble(chunks, [], [], max_chars=5000)
    assert "PAST APPROVED EXAMPLES" in result
    assert "approved doc content" in result


def test_context_assembler_kb_section_present():
    from services.rag_service import ContextAssembler
    ca = ContextAssembler()
    chunks = [_make_chunk("best practice chunk", 0.8, "kb_file")]
    result = ca.assemble([], chunks, [], max_chars=5000)
    assert "BEST PRACTICE PATTERNS" in result
    assert "best practice chunk" in result


def test_context_assembler_url_section_present():
    from services.rag_service import ContextAssembler
    ca = ContextAssembler()
    chunks = [_make_chunk("url content fetched", 0.7, "kb_url")]
    result = ca.assemble([], [], chunks, max_chars=5000)
    assert "url content fetched" in result


def test_context_assembler_respects_max_chars_budget():
    from services.rag_service import ContextAssembler
    ca = ContextAssembler()
    chunks = [_make_chunk("A" * 1000, 0.9, "approved")] * 10
    result = ca.assemble(chunks, [], [], max_chars=500)
    assert len(result) <= 600   # some header overhead allowed


def test_context_assembler_orders_by_score():
    from services.rag_service import ContextAssembler
    ca = ContextAssembler()
    low  = _make_chunk("low relevance content",  0.3, "approved")
    high = _make_chunk("high relevance content", 0.9, "approved")
    result = ca.assemble([low, high], [], [], max_chars=5000)
    # Higher score should appear first
    assert result.index("high relevance content") < result.index("low relevance content")


def test_build_rag_context_still_works():
    """Backward compat: build_rag_context() must remain unchanged."""
    from services.rag_service import build_rag_context
    result = build_rag_context(["doc A", "doc B"])
    assert "doc A" in result
    assert "doc B" in result


def test_context_assembler_both_sections_present():
    """Both approved and KB sections appear when both source types provided."""
    from services.rag_service import ContextAssembler
    ca = ContextAssembler()
    approved = [_make_chunk("approved integration example", 0.9, "approved")]
    kb = [_make_chunk("best practice document", 0.8, "kb_file")]
    result = ca.assemble(approved, kb, [], max_chars=5000)
    assert "PAST APPROVED EXAMPLES" in result
    assert "BEST PRACTICE PATTERNS" in result
    assert "approved integration example" in result
    assert "best practice document" in result
