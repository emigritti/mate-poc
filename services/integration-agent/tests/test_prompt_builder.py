"""
Unit tests — prompt_builder module
ADR-014: Prompt construction from reusable-meta-prompt.md.

Coverage:
  - Source and target appear in the built prompt
  - Requirements text is injected
  - RAG context block present/absent based on input
  - Fallback template used gracefully when file is missing
  - Prompt has minimum useful length
"""

import pytest

from prompt_builder import build_prompt, _FALLBACK_TEMPLATE


class TestBuildPrompt:
    def test_source_in_prompt(self):
        prompt = build_prompt("PLM", "PIM", "Sync product data", "")
        assert "PLM" in prompt

    def test_target_in_prompt(self):
        prompt = build_prompt("PLM", "PIM", "Sync product data", "")
        assert "PIM" in prompt

    def test_requirements_in_prompt(self):
        reqs = "Sync product master data daily at midnight"
        prompt = build_prompt("PLM", "PIM", reqs, "")
        assert reqs in prompt

    def test_rag_context_section_present_when_provided(self):
        """The RAG block header 'PAST APPROVED EXAMPLES:\n' must appear when context is given."""
        prompt = build_prompt("PLM", "PIM", "req text", "PAST EXAMPLE: something")
        assert "PAST APPROVED EXAMPLES:\n" in prompt

    def test_rag_context_section_absent_when_empty(self):
        """Empty RAG context must not inject the 'PAST APPROVED EXAMPLES:' block.

        Note: the meta-prompt template contains 'PAST APPROVED EXAMPLES' in its
        static instruction text (step 4).  We therefore check for the *dynamic*
        block header ('PAST APPROVED EXAMPLES:\\n' with colon+newline, as produced
        by rag_block = f'PAST APPROVED EXAMPLES:\\n{rag_context}'), which is only
        present when rag_context is non-empty.
        """
        prompt = build_prompt("PLM", "PIM", "req text", "")
        assert "PAST APPROVED EXAMPLES:\n" not in prompt

    def test_rag_context_section_absent_when_whitespace(self):
        """Whitespace-only RAG context must not inject the block."""
        prompt = build_prompt("PLM", "PIM", "req text", "   ")
        assert "PAST APPROVED EXAMPLES:\n" not in prompt

    def test_prompt_has_minimum_length(self):
        """A useful prompt must contain substantial instructions."""
        prompt = build_prompt("SRC", "TGT", "some req", "")
        assert len(prompt) > 100

    def test_fallback_template_has_required_slots(self):
        """Fallback template must define all four expected slots."""
        for slot in ("{source_system}", "{target_system}", "{formatted_requirements}", "{rag_context}"):
            assert slot in _FALLBACK_TEMPLATE

    def test_system_names_with_hyphens(self):
        """System names like 'Azure-AD' or 'SAP-ERP' must not break the prompt."""
        prompt = build_prompt("Azure-AD", "SAP-ERP", "Sync users", "")
        assert "Azure-AD" in prompt
        assert "SAP-ERP" in prompt

    def test_system_name_with_format_specifiers_does_not_raise(self):
        """
        System names containing '{...}' patterns (e.g. '{PLM}') must not cause
        a KeyError or ValueError in build_prompt (F-09 / CLAUDE.md §10).

        Previously str.format() was used, which would raise on unknown keys.
        Now sequential str.replace() handles this safely.
        """
        # Must not raise KeyError or ValueError
        prompt = build_prompt("{source_system}", "{target_system}", "req", "")
        assert isinstance(prompt, str)
        assert len(prompt) > 10
