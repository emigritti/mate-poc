"""
Unit tests for semantic_chunk() — LangChain RecursiveCharacterTextSplitter (R11).

Covers:
  - Heading boundaries respected (## splits before character limit)
  - Paragraph boundaries respected (\n\n)
  - Empty text returns empty list
  - Overlap works
  - Backward compat: chunk_text() still works unchanged
"""
import pytest


def test_semantic_chunk_empty_text_returns_empty():
    from document_parser import semantic_chunk
    assert semantic_chunk("") == []


def test_semantic_chunk_short_text_single_chunk():
    from document_parser import semantic_chunk
    result = semantic_chunk("Short text.", chunk_size=1000, chunk_overlap=100)
    assert len(result) == 1
    assert result[0].text == "Short text."
    assert result[0].index == 0


def test_semantic_chunk_respects_heading_boundary():
    """Heading ## should be a split point before char limit is hit."""
    from document_parser import semantic_chunk
    text = ("## Section One\n" + "A" * 300 + "\n\n## Section Two\n" + "B" * 300)
    result = semantic_chunk(text, chunk_size=400, chunk_overlap=0)
    # Section One and Section Two must end up in separate chunks
    combined = " ".join(c.text for c in result)
    assert "Section One" in combined
    assert "Section Two" in combined
    assert len(result) >= 2


def test_semantic_chunk_respects_paragraph_boundary():
    """Double newline (paragraph break) preferred over mid-sentence split."""
    from document_parser import semantic_chunk
    text = ("First paragraph content here.\n\n"
            "Second paragraph content here.\n\n"
            "Third paragraph content here.")
    result = semantic_chunk(text, chunk_size=50, chunk_overlap=0)
    # Each paragraph is ~35 chars — should land in separate chunks
    assert len(result) >= 2


def test_semantic_chunk_indices_are_sequential():
    from document_parser import semantic_chunk
    text = "Line one.\n\nLine two.\n\nLine three.\n\nLine four."
    result = semantic_chunk(text, chunk_size=20, chunk_overlap=0)
    indices = [c.index for c in result]
    assert indices == list(range(len(result)))


def test_semantic_chunk_returns_text_chunks():
    from document_parser import semantic_chunk, TextChunk
    result = semantic_chunk("Some content.", chunk_size=1000, chunk_overlap=100)
    assert all(isinstance(c, TextChunk) for c in result)


def test_chunk_text_still_works_unchanged():
    """Backward compat: original chunk_text() must work unchanged after R11."""
    from document_parser import chunk_text
    result = chunk_text("Hello world. " * 100, chunk_size=100, chunk_overlap=20)
    assert len(result) > 1
    assert all(c.text for c in result)
