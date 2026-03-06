"""
Unit tests — output_guard module
ADR-015 / CLAUDE.md §7: Security guard tests are highest priority.

Coverage:
  - Structural guard (LLM output must start with '# Functional Specification')
  - XSS prevention via bleach allowlist
  - Truncation at max chars
  - Empty / None input handling
  - sanitize_human_content (lenient mode, no structural guard)
"""

import pytest

from output_guard import (
    LLMOutputValidationError,
    sanitize_human_content,
    sanitize_llm_output,
)

_VALID_PREFIX = "# Functional Specification"


class TestSanitizeLlmOutput:
    def test_valid_output_passes(self):
        raw = f"{_VALID_PREFIX}\n\n## 1. Business Context\nSome content."
        result = sanitize_llm_output(raw)
        assert result.startswith(_VALID_PREFIX)

    def test_missing_header_raises(self):
        """Output that doesn't start with the required heading must be rejected."""
        with pytest.raises(LLMOutputValidationError):
            sanitize_llm_output("Here is your spec:\n\n# Functional Specification")

    def test_empty_string_raises(self):
        with pytest.raises(LLMOutputValidationError):
            sanitize_llm_output("")

    def test_none_raises(self):
        with pytest.raises(LLMOutputValidationError):
            sanitize_llm_output(None)  # type: ignore[arg-type]

    def test_script_tag_stripped(self):
        """XSS via <script> must be removed (OWASP A03)."""
        raw = f"{_VALID_PREFIX}\n\n<script>alert('xss')</script>\n\nContent."
        result = sanitize_llm_output(raw)
        assert "<script>" not in result
        assert "alert" not in result

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
        """XSS in reviewer clipboard paste must still be stripped."""
        raw = "Good content.<script>steal()</script> More text."
        result = sanitize_human_content(raw)
        assert "<script>" not in result
        assert "steal" not in result

    def test_empty_returns_empty(self):
        assert sanitize_human_content("") == ""

    def test_truncation_applied(self):
        raw = "A" * 60_000
        result = sanitize_human_content(raw)
        assert len(result) <= 50_000
