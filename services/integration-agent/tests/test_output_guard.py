"""
Unit tests — output_guard module
ADR-015 / CLAUDE.md §7: Security guard tests are highest priority.

Coverage:
  - Structural guard (LLM output must start with '# Integration Functional Design')
  - XSS prevention via bleach allowlist
  - Truncation at max chars
  - Empty / None input handling
  - sanitize_human_content (lenient mode, no structural guard)
"""

import pytest

from output_guard import (
    LLMOutputValidationError,
    assess_quality,
    sanitize_human_content,
    sanitize_llm_output,
)

_VALID_PREFIX = "# Integration Functional Design"


class TestSanitizeLlmOutput:
    def test_valid_output_passes(self):
        raw = f"{_VALID_PREFIX}\n\n## 1. Business Context\nSome content."
        result = sanitize_llm_output(raw)
        assert result.startswith(_VALID_PREFIX)

    def test_preamble_stripped_when_heading_found_in_body(self):
        """
        When the LLM prepends a courtesy intro before the required heading, the guard
        must strip the preamble and return content starting from '# Integration
        Functional Design' — NOT raise an error (ADR-015 §Fallback).

        Fix F-01: the previous assertion expected LLMOutputValidationError, but ADR-015
        deliberately handles small-model preambles via the fallback stripping path.
        """
        preamble = "Here is your spec:\n\n"
        raw = f"{preamble}{_VALID_PREFIX}\n\n## Content."
        result = sanitize_llm_output(raw)
        assert result.startswith(_VALID_PREFIX)
        assert "Here is your spec" not in result

    def test_heading_absent_raises(self):
        """Output that contains NO '# Functional Specification' heading must be rejected."""
        with pytest.raises(LLMOutputValidationError):
            sanitize_llm_output("I'm sorry, I cannot help with that request.")

    def test_empty_string_raises(self):
        with pytest.raises(LLMOutputValidationError):
            sanitize_llm_output("")

    def test_none_raises(self):
        with pytest.raises(LLMOutputValidationError):
            sanitize_llm_output(None)  # type: ignore[arg-type]

    def test_script_tag_stripped(self):
        """XSS via <script> must be removed (OWASP A03).

        bleach.clean(strip=True) removes the HTML tag wrappers but preserves
        the text content between them.  The JS text is inert without <script>;
        the browser will not execute it.  Only the tag itself is asserted absent.
        """
        raw = f"{_VALID_PREFIX}\n\n<script>alert('xss')</script>\n\nContent."
        result = sanitize_llm_output(raw)
        assert "<script>" not in result
        assert "</script>" not in result

    def test_iframe_stripped(self):
        raw = f"{_VALID_PREFIX}\n\n<iframe src='evil.com'></iframe>"
        result = sanitize_llm_output(raw)
        assert "<iframe" not in result

    def test_allowed_markdown_elements_preserved(self):
        """Standard markdown elements must survive bleach."""
        raw = (
            f"{_VALID_PREFIX}\n\n"
            "## Section\n\n"
            "- item one\n"
            "- item two\n\n"
            "`inline code`"
        )
        result = sanitize_llm_output(raw)
        assert "Section" in result
        assert "item one" in result

    def test_output_truncated_at_max_chars(self):
        raw = f"{_VALID_PREFIX}\n\n" + "x" * 60_000
        result = sanitize_llm_output(raw)
        assert len(result) <= 50_000

    def test_output_within_limit_not_truncated(self):
        raw = f"{_VALID_PREFIX}\n\nShort content."
        result = sanitize_llm_output(raw)
        assert "Short content." in result


class TestSanitizeHumanContent:
    def test_no_structural_guard_applied(self):
        """Human content does NOT need to start with the required heading."""
        result = sanitize_human_content("Updated spec without the standard prefix.")
        assert "Updated spec" in result

    def test_xss_stripped_in_human_content(self):
        """XSS in reviewer clipboard paste must still be stripped.

        Same bleach behaviour: tag wrappers removed, text content kept but inert.
        """
        raw = "Good content.<script>steal()</script> More text."
        result = sanitize_human_content(raw)
        assert "<script>" not in result
        assert "</script>" not in result

    def test_empty_returns_empty(self):
        assert sanitize_human_content("") == ""

    def test_truncation_applied(self):
        raw = "A" * 60_000
        result = sanitize_human_content(raw)
        assert len(result) <= 50_000


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_doc(sections: int = 7, na_per_section: bool = False) -> str:
    """Helper: build a minimal functional design doc."""
    lines = ["# Integration Functional Design\n"]
    for i in range(1, sections + 1):
        lines.append(f"## {i}. Section Title\n")
        lines.append(
            "This section contains meaningful integration details covering data mapping, "
            "error handling, transformation rules, and the business logic required for this process.\n"
            if not na_per_section else "n/a\n"
        )
    return "\n".join(lines)


class TestAssessQuality:
    def test_good_document_passes(self):
        report = assess_quality(_make_doc(sections=7))
        assert report.passed is True
        assert report.issues == []

    def test_too_few_sections_fails(self):
        doc = "# Integration Functional Design\n\n## 1. Only\n\nContent here."
        report = assess_quality(doc)
        assert report.passed is False
        assert any("section" in i.lower() for i in report.issues)

    def test_high_na_ratio_fails(self):
        report = assess_quality(_make_doc(sections=7, na_per_section=True))
        assert report.passed is False
        assert any("n/a" in i.lower() for i in report.issues)

    def test_too_short_fails(self):
        report = assess_quality("# Integration Functional Design\n\n## 1. S\n\nTiny.")
        assert report.passed is False
        assert any("short" in i.lower() or "word" in i.lower() for i in report.issues)

    def test_quality_score_range(self):
        report = assess_quality(_make_doc(sections=7))
        assert 0.0 <= report.quality_score <= 1.0

    def test_report_fields_present(self):
        report = assess_quality(_make_doc())
        for field in ("section_count", "na_ratio", "word_count", "quality_score", "passed", "issues"):
            assert hasattr(report, field)

    def test_section_count_matches_headings(self):
        doc = _make_doc(sections=5)
        assert assess_quality(doc).section_count == 5
