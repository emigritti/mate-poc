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


# ── DOCUMENT SUMMARIES section (ADR-032 — RAPTOR-lite) ───────────────────────

def test_context_assembler_summary_chunks_add_document_summaries_section():
    """assemble() with summary_chunks adds a '## DOCUMENT SUMMARIES' section first."""
    from services.rag_service import ContextAssembler
    ca = ContextAssembler()
    summaries = [_make_chunk("Field mapping: PLM product_id → PIM sku.", 0.91, "summary")]

    result = ca.assemble([], [], [], max_chars=5000, summary_chunks=summaries)

    assert "DOCUMENT SUMMARIES" in result
    assert "Field mapping: PLM product_id" in result


def test_context_assembler_summary_section_appears_before_approved():
    """DOCUMENT SUMMARIES section appears before PAST APPROVED EXAMPLES."""
    from services.rag_service import ContextAssembler
    ca = ContextAssembler()
    summaries = [_make_chunk("Section summary text.", 0.91, "summary")]
    approved  = [_make_chunk("Approved example.", 0.85, "approved")]

    result = ca.assemble(approved, [], [], max_chars=5000, summary_chunks=summaries)

    assert result.index("DOCUMENT SUMMARIES") < result.index("PAST APPROVED EXAMPLES")


def test_context_assembler_no_summary_section_when_summary_chunks_empty():
    """No DOCUMENT SUMMARIES section when summary_chunks is empty or absent."""
    from services.rag_service import ContextAssembler
    ca = ContextAssembler()
    approved = [_make_chunk("Approved example.", 0.85, "approved")]

    result_no_kwarg  = ca.assemble(approved, [], [], max_chars=5000)
    result_empty_arg = ca.assemble(approved, [], [], max_chars=5000, summary_chunks=[])

    assert "DOCUMENT SUMMARIES" not in result_no_kwarg
    assert "DOCUMENT SUMMARIES" not in result_empty_arg


def test_context_assembler_summary_section_respects_summary_budget():
    """DOCUMENT SUMMARIES section stops adding chunks when summary budget exceeded."""
    from services.rag_service import ContextAssembler
    ca = ContextAssembler()
    # 3 summaries of 200 chars each; budget of 250 chars → only first fits
    summaries = [
        _make_chunk("A" * 200 + f" summary_{i}", 0.9 - i * 0.1, "summary")
        for i in range(3)
    ]

    result = ca.assemble([], [], [], max_chars=5000, summary_chunks=summaries, summary_max_chars=250)

    # Count how many "A" * 200 blocks appear
    summary_section = result.split("## PAST")[0] if "## PAST" in result else result
    assert summary_section.count("summary_0") == 1   # first fits
    assert summary_section.count("summary_2") == 0   # third doesn't fit


# ── PINNED REFERENCES tests ────────────────────────────────────────────────────

def test_pinned_section_present():
    """PINNED REFERENCES section is added when pinned_chunks is provided."""
    from services.rag_service import ContextAssembler
    pinned = [_make_chunk("Architecture diagram: PLM→PIM sync flow", 1.0, "pinned")]
    result = ContextAssembler().assemble([], [], [], max_chars=2000, pinned_chunks=pinned)
    assert "PINNED REFERENCES" in result


def test_pinned_section_before_summaries_and_kb():
    """PINNED REFERENCES appears before DOCUMENT SUMMARIES and BEST PRACTICE PATTERNS."""
    from services.rag_service import ContextAssembler
    pinned    = [_make_chunk("Pinned content", 1.0, "pinned")]
    summaries = [_make_chunk("Summary content", 0.9, "summary")]
    kb        = [_make_chunk("KB content", 0.8, "kb_file")]
    result = ContextAssembler().assemble(
        [], kb, [], max_chars=2000,
        summary_chunks=summaries,
        pinned_chunks=pinned,
    )
    assert result.index("PINNED REFERENCES") < result.index("DOCUMENT SUMMARIES")
    assert result.index("DOCUMENT SUMMARIES") < result.index("BEST PRACTICE PATTERNS")


def test_empty_pinned_produces_no_section():
    """Empty or None pinned_chunks must not produce a PINNED REFERENCES section."""
    from services.rag_service import ContextAssembler
    kb = [_make_chunk("Some KB content", 0.8, "kb_file")]
    for pinned in ([], None):
        result = ContextAssembler().assemble([], kb, [], max_chars=2000, pinned_chunks=pinned)
        assert "PINNED REFERENCES" not in result


def test_pinned_respects_budget():
    """Pinned text is truncated per-chunk so total stays within pinned_max_chars."""
    from services.rag_service import ContextAssembler
    long_text = "X" * 2000
    pinned = [_make_chunk(long_text, 1.0, "pinned")] * 3
    result = ContextAssembler().assemble(
        [], [], [], max_chars=2000,
        pinned_chunks=pinned,
        pinned_max_chars=500,
    )
    assert "PINNED REFERENCES" in result
    # Per-chunk cap = 500 // 3 ≈ 166 chars; no 600-char block of X's should appear
    assert "X" * 600 not in result
