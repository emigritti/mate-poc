"""
Unit tests — output_guard module
ADR-015 / CLAUDE.md §7: Security guard tests are highest priority.

Coverage:
  - Structural guard (LLM output must start with '# Integration Design')
  - XSS prevention via bleach allowlist
  - Truncation at max chars
  - Empty / None input handling
  - sanitize_human_content (lenient mode, no structural guard)
  - assess_quality: 6 signals (sections, n/a ratio, word count, Mermaid, tables, placeholders)
  - enforce_quality_gate: block mode raises, warn mode logs only
"""

import pytest

from output_guard import (
    LLMOutputValidationError,
    QualityGateError,
    assess_quality,
    enforce_quality_gate,
    sanitize_human_content,
    sanitize_llm_output,
)

_VALID_PREFIX = "# Integration Design"

# ── Document builder ───────────────────────────────────────────────────────────

_MERMAID_BLOCK = """
```mermaid
sequenceDiagram
    PLM->>SAP: Send product data
    SAP-->>PLM: Acknowledge
```
"""

_MAPPING_TABLE = """
| Source Field | Target Field | Transformation |
| --- | --- | --- |
| product_id | MATNR | direct |
| description | MAKTX | trim(255) |
"""

_SECTION_BODY = (
    "This section covers the integration details for data exchange between systems. "
    "It includes field mappings, transformation rules, error handling strategies, "
    "retry policies, and the business logic governing the synchronisation process. "
    "Data validation is applied at every boundary crossing."
)


def _make_doc(
    sections: int = 12,
    na_per_section: bool = False,
    include_mermaid: bool = True,
    include_table: bool = True,
    placeholders: str = "",
) -> str:
    """Build a synthetic integration design document for tests."""
    lines = [f"{_VALID_PREFIX}\n"]
    for i in range(1, sections + 1):
        lines.append(f"## {i}. Section Title {i}\n")
        lines.append("n/a\n" if na_per_section else f"{_SECTION_BODY}\n")
    if include_mermaid:
        lines.append(_MERMAID_BLOCK)
    if include_table:
        lines.append(_MAPPING_TABLE)
    if placeholders:
        lines.append(f"\n{placeholders}\n")
    return "\n".join(lines)


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


class TestAssessQuality:
    def test_good_document_passes(self):
        report = assess_quality(_make_doc(sections=12))
        assert report.passed is True
        assert report.issues == []

    def test_too_few_sections_fails(self):
        doc = "# Integration Design\n\n## 1. Only\n\nContent here."
        report = assess_quality(doc)
        assert report.passed is False
        assert any("section" in i.lower() for i in report.issues)

    def test_high_na_ratio_fails(self):
        # 12 sections all n/a → ratio = 1.0 > 0.30 threshold
        report = assess_quality(_make_doc(sections=12, na_per_section=True))
        assert report.passed is False
        assert any("n/a" in i.lower() for i in report.issues)

    def test_too_short_fails(self):
        # Just headings and "n/a" — far below 300 words
        doc = "# Integration Design\n\n" + "\n".join(
            f"## {i}. S\n\nn/a" for i in range(1, 13)
        )
        report = assess_quality(doc)
        assert report.passed is False
        assert any("short" in i.lower() or "word" in i.lower() for i in report.issues)

    def test_missing_mermaid_fails(self):
        doc = _make_doc(sections=12, include_mermaid=False)
        report = assess_quality(doc)
        assert report.passed is False
        assert report.has_mermaid_diagram is False
        assert any("mermaid" in i.lower() for i in report.issues)

    def test_mermaid_present_detected(self):
        doc = _make_doc(sections=12, include_mermaid=True)
        report = assess_quality(doc)
        assert report.has_mermaid_diagram is True

    def test_missing_mapping_table_fails(self):
        doc = _make_doc(sections=12, include_table=False)
        report = assess_quality(doc)
        assert report.passed is False
        assert report.mapping_table_count == 0
        assert any("table" in i.lower() for i in report.issues)

    def test_mapping_table_present_detected(self):
        doc = _make_doc(sections=12, include_table=True)
        report = assess_quality(doc)
        assert report.mapping_table_count >= 1

    def test_placeholder_todo_fails(self):
        doc = _make_doc(sections=12, placeholders="[TODO] fill this in")
        report = assess_quality(doc)
        assert report.passed is False
        assert report.placeholder_count >= 1
        assert any("placeholder" in i.lower() for i in report.issues)

    def test_placeholder_tbd_fails(self):
        doc = _make_doc(sections=12, placeholders="[TBD]")
        report = assess_quality(doc)
        assert report.placeholder_count >= 1

    def test_placeholder_insert_fails(self):
        doc = _make_doc(sections=12, placeholders="[INSERT mapping here]")
        report = assess_quality(doc)
        assert report.placeholder_count >= 1

    def test_no_placeholders_clean_doc(self):
        doc = _make_doc(sections=12)
        report = assess_quality(doc)
        assert report.placeholder_count == 0

    def test_quality_score_range(self):
        report = assess_quality(_make_doc(sections=12))
        assert 0.0 <= report.quality_score <= 1.0

    def test_quality_score_good_doc_near_one(self):
        report = assess_quality(_make_doc(sections=16))
        assert report.quality_score >= 0.9

    def test_report_fields_present(self):
        report = assess_quality(_make_doc())
        for f in (
            "section_count", "na_ratio", "word_count",
            "has_mermaid_diagram", "mapping_table_count", "placeholder_count",
            "quality_score", "passed", "issues",
        ):
            assert hasattr(report, f)

    def test_section_count_matches_headings(self):
        doc = _make_doc(sections=12)
        assert assess_quality(doc).section_count == 12


class TestEnforceQualityGate:
    def _passing_report(self):
        return assess_quality(_make_doc(sections=12))

    def _failing_report(self):
        # Too few sections, no Mermaid, no table → definitely fails
        return assess_quality("# Integration Design\n\n## 1. S\n\nTiny.")

    def test_passing_doc_does_not_raise_in_block_mode(self):
        report = self._passing_report()
        assert report.passed is True
        enforce_quality_gate(report, mode="block")  # should not raise

    def test_failing_doc_raises_in_block_mode(self):
        report = self._failing_report()
        assert report.passed is False
        with pytest.raises(QualityGateError):
            enforce_quality_gate(report, mode="block")

    def test_failing_doc_does_not_raise_in_warn_mode(self):
        report = self._failing_report()
        enforce_quality_gate(report, mode="warn")  # must NOT raise

    def test_score_below_min_raises_in_block_mode(self):
        report = self._passing_report()
        # Force gate failure via unreachably high min_score
        with pytest.raises(QualityGateError):
            enforce_quality_gate(report, min_score=1.01, mode="block")

    def test_error_message_contains_score(self):
        report = self._failing_report()
        with pytest.raises(QualityGateError, match=r"score="):
            enforce_quality_gate(report, mode="block")
