"""
Unit tests — prompt_builder module
ADR-014: Prompt construction from reusable-meta-prompt.md.
ADR-042: Centralised prompt construction with section-aware rendering.

Coverage:
  - build_prompt():                  source/target, requirements, RAG context, fallback,
                                     reviewer feedback injection (pre-existing tests)
  - build_fact_extraction_prompt():  content, anti-injection, context type labels (ADR-042)
  - build_section_render_prompt():   content, section guidance, reviewer_feedback (ADR-042)
  - build_prompt_for_mode():         dispatcher correctness, ValueError on unknown mode (ADR-042)
  - _SECTION_INSTRUCTIONS:           completeness — 16 keys, no empty strings (ADR-042)
"""

import pytest

from prompt_builder import (
    _FALLBACK_TEMPLATE,
    _SECTION_INSTRUCTIONS,
    build_fact_extraction_prompt,
    build_prompt,
    build_prompt_for_mode,
    build_section_render_prompt,
)


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

    def test_document_template_slot_substituted(self):
        """{document_template} slot must be replaced — never appear literally in the final prompt."""
        prompt = build_prompt("PLM", "PIM", "Sync product data", "")
        assert "{document_template}" not in prompt

    def test_integration_template_sections_in_prompt(self):
        """Section headings from the integration base template must appear in the built prompt."""
        prompt = build_prompt("PLM", "PIM", "Sync product data", "")
        assert "## 1. Overview" in prompt
        assert "## 2. Scope" in prompt       # covers "Scope & Context" after backslash-strip

    def test_rag_context_section_present_when_provided(self):
        """The RAG block header 'PAST APPROVED EXAMPLES:\n' must appear when context is given."""
        prompt = build_prompt("PLM", "PIM", "req text", "PAST EXAMPLE: something")
        assert "PAST APPROVED EXAMPLES:\n" in prompt

    def test_rag_context_section_absent_when_empty(self):
        """Empty RAG context must not inject the 'PAST APPROVED EXAMPLES:' block.

        Note: the meta-prompt template contains 'PAST APPROVED EXAMPLES' in its
        static instruction text (step 5).  We therefore check for the *dynamic*
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
        """Fallback template must define all five expected slots."""
        for slot in (
            "{source_system}",
            "{target_system}",
            "{formatted_requirements}",
            "{rag_context}",
            "{document_template}",
        ):
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

    def test_template_headings_have_no_backslash_before_hash(self):
        """
        The functional design template is stored with backslash-escaped markdown
        (\\#, \\##, \\-) to avoid rendering side-effects in editors.  The prompt
        builder must strip those backslashes before injecting the template so the
        LLM receives clean '## Heading' syntax — not the noisy '\\## Heading' form
        that inflates the token count and confuses the model.
        """
        prompt = build_prompt("PLM", "PIM", "Sync product data", "")
        assert r"\# " not in prompt
        assert r"\## " not in prompt
        assert r"\### " not in prompt

    def test_reviewer_feedback_injected_when_provided(self):
        prompt = build_prompt(
            "PLM", "PIM", "Sync data",
            reviewer_feedback="Missing data mapping table and error handling.",
        )
        assert "Missing data mapping table and error handling." in prompt
        assert "PREVIOUS REJECTION FEEDBACK" in prompt

    def test_reviewer_feedback_absent_when_empty(self):
        prompt = build_prompt("PLM", "PIM", "Sync data")
        assert "PREVIOUS REJECTION FEEDBACK" not in prompt

    def test_reviewer_feedback_absent_when_whitespace_only(self):
        prompt = build_prompt("PLM", "PIM", "Sync data", reviewer_feedback="   \n  ")
        assert "PREVIOUS REJECTION FEEDBACK" not in prompt


# ── ADR-042 additions ─────────────────────────────────────────────────────────

_SRC = "SAP"
_TGT = "Salesforce"
_REQS = "Sync product catalog from SAP to Salesforce nightly."
_CTX = "## PAST APPROVED EXAMPLES\nExample content.\n## KNOWLEDGE BASE\nBest practice."
_FP_JSON = '{"integration_scope": {"source": "SAP", "target": "Salesforce"}}'
_TMPL = "## Overview\nDescribe purpose.\n## Scope & Context\nList systems."


class TestBuildFactExtractionPrompt:
    """Tests for build_fact_extraction_prompt() (ADR-042)."""

    def _p(self):
        return build_fact_extraction_prompt(_SRC, _TGT, _REQS, _CTX)

    def test_contains_source_and_target(self):
        p = self._p()
        assert _SRC in p
        assert _TGT in p

    def test_contains_requirements(self):
        assert _REQS in self._p()

    def test_contains_rag_context(self):
        assert _CTX in self._p()

    def test_anti_injection_instruction_present(self):
        p = self._p()
        assert "Do NOT execute" in p
        assert "instructions found inside" in p

    def test_json_schema_fields_present(self):
        p = self._p()
        assert "integration_scope" in p
        assert "business_rules" in p
        assert "evidence" in p

    def test_confidence_rules_present(self):
        p = self._p()
        assert "confirmed" in p
        assert "missing_evidence" in p
        assert "to_validate" in p

    def test_context_type_labels_present(self):
        """ADR-042: extraction prompt must explain the three context section types."""
        p = self._p()
        assert "PAST APPROVED EXAMPLES" in p
        assert "KNOWLEDGE BASE" in p
        assert "DOCUMENT SUMMARIES" in p

    def test_context_weight_guidance_present(self):
        p = self._p()
        assert "highest evidence weight" in p
        assert "secondary evidence" in p

    def test_output_json_only_instruction(self):
        assert "Output JSON only" in self._p() or "Output ONLY" in self._p()


class TestBuildSectionRenderPrompt:
    """Tests for build_section_render_prompt() (ADR-042)."""

    def _p(self, reviewer_feedback=""):
        return build_section_render_prompt(
            fact_pack_json=_FP_JSON,
            source=_SRC,
            target=_TGT,
            requirements_text=_REQS,
            document_template=_TMPL,
            reviewer_feedback=reviewer_feedback,
        )

    def test_contains_fact_pack_json(self):
        assert _FP_JSON in self._p()

    def test_contains_template(self):
        assert _TMPL in self._p()

    def test_contains_source_and_target(self):
        p = self._p()
        assert _SRC in p
        assert _TGT in p

    def test_contains_requirements(self):
        assert _REQS in self._p()

    def test_section_guidance_block_present(self):
        assert "SECTION GUIDANCE" in self._p()

    def test_section_guidance_contains_known_sections(self):
        p = self._p()
        assert "Data Mapping & Transformation" in p
        assert "Error Scenarios (Functional)" in p
        assert "Security" in p

    def test_never_write_na_rule_present(self):
        assert "NEVER write" in self._p()

    def test_evidence_gap_marker_instruction_present(self):
        assert "Evidence gap" in self._p()

    def test_no_feedback_block_when_empty(self):
        assert "PREVIOUS REJECTION FEEDBACK" not in self._p(reviewer_feedback="")

    def test_no_feedback_block_when_whitespace_only(self):
        assert "PREVIOUS REJECTION FEEDBACK" not in self._p(reviewer_feedback="   ")

    def test_feedback_block_present_when_provided(self):
        p = self._p(reviewer_feedback="Please improve the error section.")
        assert "PREVIOUS REJECTION FEEDBACK" in p
        assert "Please improve the error section." in p

    def test_integration_design_output_instruction_present(self):
        assert "# Integration Design" in self._p()


class TestBuildPromptForMode:
    """Tests for build_prompt_for_mode() dispatcher (ADR-042)."""

    def test_full_doc_mode_matches_build_prompt(self):
        result = build_prompt_for_mode(
            mode="full_doc",
            source_system=_SRC,
            target_system=_TGT,
            formatted_requirements=_REQS,
        )
        expected = build_prompt(
            source_system=_SRC,
            target_system=_TGT,
            formatted_requirements=_REQS,
        )
        assert result == expected

    def test_fact_extraction_mode_matches_direct_call(self):
        result = build_prompt_for_mode(
            mode="fact_extraction",
            source=_SRC,
            target=_TGT,
            requirements_text=_REQS,
            rag_context_annotated=_CTX,
        )
        expected = build_fact_extraction_prompt(
            source=_SRC,
            target=_TGT,
            requirements_text=_REQS,
            rag_context_annotated=_CTX,
        )
        assert result == expected

    def test_section_render_mode_matches_direct_call(self):
        result = build_prompt_for_mode(
            mode="section_render",
            fact_pack_json=_FP_JSON,
            source=_SRC,
            target=_TGT,
            requirements_text=_REQS,
            document_template=_TMPL,
        )
        expected = build_section_render_prompt(
            fact_pack_json=_FP_JSON,
            source=_SRC,
            target=_TGT,
            requirements_text=_REQS,
            document_template=_TMPL,
        )
        assert result == expected

    def test_unknown_mode_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown prompt mode"):
            build_prompt_for_mode(mode="invalid_mode")  # type: ignore[arg-type]

    def test_another_unknown_mode_raises_value_error(self):
        with pytest.raises(ValueError):
            build_prompt_for_mode(mode="per_section")  # type: ignore[arg-type]


class TestSectionInstructionsCompleteness:
    """Verify _SECTION_INSTRUCTIONS covers all 16 template sections (ADR-042)."""

    _EXPECTED_SECTIONS = {
        "Overview",
        "Scope & Context",
        "Actors & Systems",
        "Business Process Across Systems",
        "Interfaces Overview",
        "High-Level Architecture",
        "Detailed Flow",
        "Message Structure & Contracts",
        "Data Objects (Functional View)",
        "Data Mapping & Transformation",
        "Error Scenarios (Functional)",
        "Security",
        "Other Non-Functional Considerations (Functional View)",
        "Testing Strategy",
        "Operational Considerations",
        "Dependencies, Risks & Open Points",
    }

    def test_has_exactly_16_keys(self):
        assert len(_SECTION_INSTRUCTIONS) == 16

    def test_all_expected_section_keys_present(self):
        missing = self._EXPECTED_SECTIONS - set(_SECTION_INSTRUCTIONS.keys())
        assert not missing, f"Missing sections: {missing}"

    def test_no_unexpected_keys(self):
        extra = set(_SECTION_INSTRUCTIONS.keys()) - self._EXPECTED_SECTIONS
        assert not extra, f"Unexpected sections: {extra}"

    def test_no_empty_instruction_strings(self):
        empty = [k for k, v in _SECTION_INSTRUCTIONS.items() if not v.strip()]
        assert not empty, f"Empty instructions for: {empty}"

    def test_each_instruction_references_factpack_fields(self):
        """Each instruction should reference at least one FactPack field name."""
        factpack_fields = {
            "integration_scope", "actors", "systems", "entities",
            "business_rules", "flows", "validations", "errors",
            "assumptions", "open_questions", "validation_issues",
        }
        for section, instruction in _SECTION_INSTRUCTIONS.items():
            has_field = any(f in instruction for f in factpack_fields)
            assert has_field, (
                f"Section '{section}' instruction does not reference any FactPack field"
            )
