"""
Unit tests — agent_service module (ADR-041).

Coverage:
  - generate_integration_doc(): FactPack two-step path
  - generate_integration_doc(): single-pass fallback path (fact_pack=None)
  - generate_integration_doc(): kill-switch (settings.fact_pack_enabled=False)
  - _build_section_reports(): confidence scoring per section
  - GenerationReport: new FactPack fields populated correctly

All external I/O is mocked. The function signature of generate_integration_doc()
is unchanged — existing callers are verified via backward-compat assertions.
"""

import re
from collections import Counter
from typing import Callable
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from schemas import ClaimReport, GenerationReport, SectionReport
from services.agent_service import _build_section_reports, generate_integration_doc
from services.fact_pack_service import EvidenceClaim, FactPack


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_entry(source: str = "SAP", target: str = "Salesforce", tags: list | None = None):
    entry = MagicMock()
    entry.id = "TEST-0001"
    entry.source = {"system": source}
    entry.target = {"system": target}
    entry.tags = tags or ["catalog", "erp"]
    return entry


def _make_requirements(descriptions: list[str] | None = None):
    descriptions = descriptions or ["Sync product data", "Handle errors gracefully"]
    reqs = []
    for desc in descriptions:
        r = MagicMock()
        r.description = desc
        reqs.append(r)
    return reqs


def _minimal_fact_pack(source: str = "SAP", target: str = "Salesforce") -> FactPack:
    return FactPack(
        integration_scope={"source": source, "target": target, "direction": "unidirectional"},
        actors=[],
        systems=[{"id": "SYS-01", "name": source, "role": "source", "protocol": "REST"}],
        entities=[],
        business_rules=[{"id": "BR-01", "statement": "Only PUBLISHED products are synced", "source": "explicit"}],
        flows=[{"id": "FLW-01", "name": "Product Sync", "trigger": "schedule", "steps": [], "outcome": "synced"}],
        validations=[],
        errors=[],
        assumptions=[],
        open_questions=[],
        evidence=[
            EvidenceClaim("BR-01", "Only PUBLISHED products synced", ["KB-001-chunk-0"], "confirmed", "confirmed"),
            EvidenceClaim("OQ-01", "SLA for error handling", [], "missing_evidence", "missing_evidence"),
        ],
        extraction_model="claude-sonnet-4-6",
        extraction_chars=5000,
    )


_VALID_DOC = (
    "# Integration Design\n\n"
    "## 1. Overview\n\nSome content about PUBLISHED products and error handling.\n\n"
    "## 2. Scope & Context\n\nIn-scope: product sync.\n\n"
    "## 3. Actors & Systems\n\nSAP and Salesforce.\n\n"
    "## 4. Business Process\n\nNightly sync flow.\n\n"
    "## 5. Interfaces\n\nREST API.\n\n"
)


def _patch_all_external(
    *,
    fact_pack: FactPack | None,
    rendered_doc: str = _VALID_DOC,
    single_pass_doc: str = _VALID_DOC,
    enrich_return: str | None = None,
):
    """
    Return a context manager that patches all external I/O for agent_service.

    Patches:
      - hybrid_retriever.retrieve → empty ScoredChunk lists
      - hybrid_retriever.retrieve_summaries → empty list
      - fetch_url_kb_context → empty string (no URL chunks)
      - ContextAssembler.assemble → "mocked rag context"
      - extract_fact_pack → fact_pack (or None)
      - validate_fact_pack → identity (pass-through)
      - render_document_sections → rendered_doc
      - build_prompt → "mocked prompt"
      - generate_with_retry → single_pass_doc
      - _enrich_with_claude → enrich_return or single_pass_doc (unchanged)
      - sanitize_llm_output → identity pass-through
      - assess_quality → minimal QualityReport
    """
    from unittest.mock import patch as _patch

    enrich_doc = enrich_return if enrich_return is not None else single_pass_doc

    class _Ctx:
        def __enter__(self):
            self._patches = [
                _patch("services.agent_service.hybrid_retriever.retrieve", new=AsyncMock(return_value=[])),
                _patch("services.agent_service.hybrid_retriever.retrieve_summaries", new=AsyncMock(return_value=[])),
                _patch("services.agent_service.fetch_url_kb_context", new=AsyncMock(return_value="")),
                _patch("services.agent_service.ContextAssembler") ,
                _patch("services.agent_service.extract_fact_pack", new=AsyncMock(return_value=fact_pack)),
                _patch("services.agent_service.validate_fact_pack", side_effect=lambda fp, s, t: fp),
                _patch("services.agent_service.render_document_sections", new=AsyncMock(return_value=rendered_doc)),
                _patch("services.agent_service.build_prompt", return_value="mocked prompt"),
                _patch("services.agent_service.generate_with_retry", new=AsyncMock(return_value=single_pass_doc)),
                _patch("services.agent_service._enrich_with_claude", new=AsyncMock(return_value=enrich_doc)),
                _patch("services.agent_service.sanitize_llm_output", side_effect=lambda raw, doc_type="integration": raw),
                _patch("services.agent_service.assess_quality", return_value=_mock_quality()),
            ]
            self._started = [p.start() for p in self._patches]
            # Configure ContextAssembler mock
            assembler_instance = self._started[3].return_value
            assembler_instance.assemble.return_value = "mocked rag context"
            return self._started

        def __exit__(self, *args):
            for p in self._patches:
                p.stop()

    return _Ctx()


def _mock_quality():
    q = MagicMock()
    q.section_count = 5
    q.na_ratio = 0.0
    q.word_count = 200
    q.quality_score = 0.85
    q.passed = True
    q.issues = []
    return q


# ── _build_section_reports ────────────────────────────────────────────────────

class TestBuildSectionReports:
    def test_returns_section_and_claim_reports(self):
        fp = _minimal_fact_pack()
        content = (
            "# Integration Design\n\n"
            "## 1. Overview\n\nOnly PUBLISHED products synced nightly.\n\n"
            "## 2. Scope\n\nSome scope.\n"
        )
        sections, claims = _build_section_reports(fp, content)
        assert len(claims) == len(fp.evidence)
        assert len(sections) == 2

    def test_claim_reports_match_evidence(self):
        fp = _minimal_fact_pack()
        _, claims = _build_section_reports(fp, _VALID_DOC)
        claim_ids = {c.claim_id for c in claims}
        evidence_ids = {e.claim_id for e in fp.evidence}
        assert claim_ids == evidence_ids

    def test_confirmed_claim_gives_high_confidence(self):
        fp = FactPack(
            integration_scope={"source": "A", "target": "B", "direction": "unidirectional"},
            actors=[], systems=[{"id": "S1", "name": "A", "role": "source", "protocol": "REST"}],
            entities=[], business_rules=[{"id": "BR-01", "statement": "x", "source": "explicit"}],
            flows=[{"id": "FLW-01", "name": "f", "trigger": "t", "steps": [], "outcome": "o"}],
            validations=[], errors=[], assumptions=[], open_questions=[],
            evidence=[EvidenceClaim("BR-01", "Only PUBLISHED items synced", ["doc-1"], "confirmed", "confirmed")],
        )
        content = "# Integration Design\n\n## 1. Overview\n\nOnly PUBLISHED items synced nightly.\n"
        sections, _ = _build_section_reports(fp, content)
        assert sections[0].confidence == 1.0

    def test_missing_evidence_claim_gives_low_confidence(self):
        fp = FactPack(
            integration_scope={"source": "A", "target": "B", "direction": "unidirectional"},
            actors=[], systems=[{"id": "S1", "name": "A", "role": "source", "protocol": "REST"}],
            entities=[], business_rules=[{"id": "BR-01", "statement": "x", "source": "explicit"}],
            flows=[{"id": "FLW-01", "name": "f", "trigger": "t", "steps": [], "outcome": "o"}],
            validations=[], errors=[], assumptions=[], open_questions=[],
            evidence=[EvidenceClaim("OQ-01", "SLA requirement unknown undefined", [], "missing_evidence", "missing_evidence")],
        )
        content = "# Integration Design\n\n## 16. Risks\n\nSLA requirement unknown undefined here.\n"
        sections, _ = _build_section_reports(fp, content)
        assert sections[0].confidence <= 0.3
        assert "missing_evidence" in sections[0].issues

    def test_section_with_no_matched_claims_is_unverified(self):
        fp = _minimal_fact_pack()
        # Section with content unrelated to any claim statement
        content = "# Integration Design\n\n## 14. Testing\n\nQualitative assessment only.\n"
        sections, _ = _build_section_reports(fp, content)
        assert sections[0].confidence == 0.5
        assert "unverified" in sections[0].issues

    def test_claim_source_chunk_count(self):
        fp = _minimal_fact_pack()
        _, claims = _build_section_reports(fp, _VALID_DOC)
        br01 = next(c for c in claims if c.claim_id == "BR-01")
        assert br01.source_chunk_count == 1
        oq01 = next(c for c in claims if c.claim_id == "OQ-01")
        assert oq01.source_chunk_count == 0


# ── generate_integration_doc — FactPack two-step path ────────────────────────

class TestFactPackPath:
    @pytest.mark.asyncio
    async def test_fact_pack_used_true_in_report(self):
        entry = _make_entry()
        reqs = _make_requirements()
        fp = _minimal_fact_pack()

        with patch("services.agent_service.settings") as mock_settings:
            mock_settings.fact_pack_enabled = True
            mock_settings.ollama_rag_max_chars = 5000
            mock_settings.ollama_model = "qwen2.5:14b"
            with _patch_all_external(fact_pack=fp):
                _, report = await generate_integration_doc(entry, reqs)

        assert report.fact_pack_used is True

    @pytest.mark.asyncio
    async def test_extraction_model_in_report(self):
        entry = _make_entry()
        reqs = _make_requirements()
        fp = _minimal_fact_pack()
        fp.extraction_model = "claude-sonnet-4-6"

        with patch("services.agent_service.settings") as mock_settings:
            mock_settings.fact_pack_enabled = True
            mock_settings.ollama_rag_max_chars = 5000
            mock_settings.ollama_model = "qwen2.5:14b"
            with _patch_all_external(fact_pack=fp):
                _, report = await generate_integration_doc(entry, reqs)

        assert report.fact_pack_extraction_model == "claude-sonnet-4-6"

    @pytest.mark.asyncio
    async def test_render_called_not_build_prompt(self):
        entry = _make_entry()
        reqs = _make_requirements()
        fp = _minimal_fact_pack()

        with patch("services.agent_service.settings") as mock_settings:
            mock_settings.fact_pack_enabled = True
            mock_settings.ollama_rag_max_chars = 5000
            mock_settings.ollama_model = "qwen2.5:14b"
            with _patch_all_external(fact_pack=fp) as mocks:
                render_mock = mocks[6]  # render_document_sections
                build_prompt_mock = mocks[7]  # build_prompt
                await generate_integration_doc(entry, reqs)

        render_mock.assert_awaited_once()
        build_prompt_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_enrich_not_called_in_fact_pack_path(self):
        entry = _make_entry()
        reqs = _make_requirements()
        fp = _minimal_fact_pack()

        with patch("services.agent_service.settings") as mock_settings:
            mock_settings.fact_pack_enabled = True
            mock_settings.ollama_rag_max_chars = 5000
            mock_settings.ollama_model = "qwen2.5:14b"
            with _patch_all_external(fact_pack=fp) as mocks:
                enrich_mock = mocks[9]  # _enrich_with_claude
                await generate_integration_doc(entry, reqs)

        enrich_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_confirmed_count_in_report(self):
        entry = _make_entry()
        reqs = _make_requirements()
        fp = _minimal_fact_pack()
        # evidence: 1 confirmed + 1 missing_evidence (from _minimal_fact_pack)

        with patch("services.agent_service.settings") as mock_settings:
            mock_settings.fact_pack_enabled = True
            mock_settings.ollama_rag_max_chars = 5000
            mock_settings.ollama_model = "qwen2.5:14b"
            with _patch_all_external(fact_pack=fp):
                _, report = await generate_integration_doc(entry, reqs)

        assert report.confirmed_claim_count == 1
        assert report.missing_evidence_count == 1
        assert report.inferred_claim_count == 0
        assert report.to_validate_count == 0

    @pytest.mark.asyncio
    async def test_section_reports_populated(self):
        entry = _make_entry()
        reqs = _make_requirements()
        fp = _minimal_fact_pack()

        with patch("services.agent_service.settings") as mock_settings:
            mock_settings.fact_pack_enabled = True
            mock_settings.ollama_rag_max_chars = 5000
            mock_settings.ollama_model = "qwen2.5:14b"
            with _patch_all_external(fact_pack=fp):
                _, report = await generate_integration_doc(entry, reqs)

        # _VALID_DOC has 5 ## sections
        assert len(report.section_reports) == 5
        assert all(isinstance(s, SectionReport) for s in report.section_reports)

    @pytest.mark.asyncio
    async def test_claim_reports_populated(self):
        entry = _make_entry()
        reqs = _make_requirements()
        fp = _minimal_fact_pack()

        with patch("services.agent_service.settings") as mock_settings:
            mock_settings.fact_pack_enabled = True
            mock_settings.ollama_rag_max_chars = 5000
            mock_settings.ollama_model = "qwen2.5:14b"
            with _patch_all_external(fact_pack=fp):
                _, report = await generate_integration_doc(entry, reqs)

        assert len(report.claim_reports) == len(fp.evidence)
        assert all(isinstance(c, ClaimReport) for c in report.claim_reports)


# ── generate_integration_doc — single-pass fallback ──────────────────────────

class TestFallbackPath:
    @pytest.mark.asyncio
    async def test_fact_pack_used_false_when_extract_returns_none(self):
        entry = _make_entry()
        reqs = _make_requirements()

        with patch("services.agent_service.settings") as mock_settings:
            mock_settings.fact_pack_enabled = True
            mock_settings.ollama_rag_max_chars = 5000
            mock_settings.ollama_model = "qwen2.5:14b"
            with _patch_all_external(fact_pack=None):
                _, report = await generate_integration_doc(entry, reqs)

        assert report.fact_pack_used is False

    @pytest.mark.asyncio
    async def test_build_prompt_called_in_fallback(self):
        entry = _make_entry()
        reqs = _make_requirements()

        with patch("services.agent_service.settings") as mock_settings:
            mock_settings.fact_pack_enabled = True
            mock_settings.ollama_rag_max_chars = 5000
            mock_settings.ollama_model = "qwen2.5:14b"
            with _patch_all_external(fact_pack=None) as mocks:
                build_prompt_mock = mocks[7]
                await generate_integration_doc(entry, reqs)

        build_prompt_mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_enrich_called_in_fallback(self):
        entry = _make_entry()
        reqs = _make_requirements()

        with patch("services.agent_service.settings") as mock_settings:
            mock_settings.fact_pack_enabled = True
            mock_settings.ollama_rag_max_chars = 5000
            mock_settings.ollama_model = "qwen2.5:14b"
            with _patch_all_external(fact_pack=None) as mocks:
                enrich_mock = mocks[9]
                await generate_integration_doc(entry, reqs)

        enrich_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_render_not_called_in_fallback(self):
        entry = _make_entry()
        reqs = _make_requirements()

        with patch("services.agent_service.settings") as mock_settings:
            mock_settings.fact_pack_enabled = True
            mock_settings.ollama_rag_max_chars = 5000
            mock_settings.ollama_model = "qwen2.5:14b"
            with _patch_all_external(fact_pack=None) as mocks:
                render_mock = mocks[6]
                await generate_integration_doc(entry, reqs)

        render_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_section_reports_empty_in_fallback(self):
        entry = _make_entry()
        reqs = _make_requirements()

        with patch("services.agent_service.settings") as mock_settings:
            mock_settings.fact_pack_enabled = True
            mock_settings.ollama_rag_max_chars = 5000
            mock_settings.ollama_model = "qwen2.5:14b"
            with _patch_all_external(fact_pack=None):
                _, report = await generate_integration_doc(entry, reqs)

        assert report.section_reports == []
        assert report.claim_reports == []

    @pytest.mark.asyncio
    async def test_claude_enriched_flag_set_when_content_changed(self):
        entry = _make_entry()
        reqs = _make_requirements()
        enriched_doc = _VALID_DOC + "\n## 6. Extra\nExtra content."

        with patch("services.agent_service.settings") as mock_settings:
            mock_settings.fact_pack_enabled = True
            mock_settings.ollama_rag_max_chars = 5000
            mock_settings.ollama_model = "qwen2.5:14b"
            with _patch_all_external(fact_pack=None, enrich_return=enriched_doc):
                _, report = await generate_integration_doc(entry, reqs)

        assert report.claude_enriched is True

    @pytest.mark.asyncio
    async def test_claude_enriched_false_when_content_unchanged(self):
        entry = _make_entry()
        reqs = _make_requirements()

        with patch("services.agent_service.settings") as mock_settings:
            mock_settings.fact_pack_enabled = True
            mock_settings.ollama_rag_max_chars = 5000
            mock_settings.ollama_model = "qwen2.5:14b"
            # enrich_return=None → returns the same content as single_pass_doc
            with _patch_all_external(fact_pack=None, enrich_return=None):
                _, report = await generate_integration_doc(entry, reqs)

        assert report.claude_enriched is False


# ── generate_integration_doc — kill-switch ────────────────────────────────────

class TestKillSwitch:
    @pytest.mark.asyncio
    async def test_fact_pack_disabled_extract_never_called(self):
        entry = _make_entry()
        reqs = _make_requirements()

        with patch("services.agent_service.settings") as mock_settings:
            mock_settings.fact_pack_enabled = False
            mock_settings.ollama_rag_max_chars = 5000
            mock_settings.ollama_model = "qwen2.5:14b"
            with _patch_all_external(fact_pack=None) as mocks:
                extract_mock = mocks[4]  # extract_fact_pack
                _, report = await generate_integration_doc(entry, reqs)

        extract_mock.assert_not_awaited()
        assert report.fact_pack_used is False

    @pytest.mark.asyncio
    async def test_fact_pack_disabled_uses_single_pass(self):
        entry = _make_entry()
        reqs = _make_requirements()

        with patch("services.agent_service.settings") as mock_settings:
            mock_settings.fact_pack_enabled = False
            mock_settings.ollama_rag_max_chars = 5000
            mock_settings.ollama_model = "qwen2.5:14b"
            with _patch_all_external(fact_pack=None) as mocks:
                build_prompt_mock = mocks[7]
                await generate_integration_doc(entry, reqs)

        build_prompt_mock.assert_called_once()


# ── GenerationReport backward compatibility ───────────────────────────────────

class TestGenerationReportBackwardCompat:
    def test_defaults_for_new_fields(self):
        """GenerationReport created without FactPack fields uses safe defaults."""
        report = GenerationReport(
            model="llama3.1:8b",
            prompt_chars=5000,
            context_chars=3000,
            sources=[],
            sections_count=12,
            na_count=2,
            quality_score=0.75,
            quality_issues=[],
            claude_enriched=False,
        )
        assert report.fact_pack_used is False
        assert report.fact_pack_extraction_model == ""
        assert report.section_reports == []
        assert report.claim_reports == []
        assert report.confirmed_claim_count == 0
        assert report.inferred_claim_count == 0
        assert report.missing_evidence_count == 0
        assert report.to_validate_count == 0

    def test_existing_fields_unchanged(self):
        """Ensure the types and names of pre-ADR-041 fields are not altered."""
        report = GenerationReport(
            model="test-model",
            prompt_chars=100,
            context_chars=50,
            sources=[],
            sections_count=5,
            na_count=0,
            quality_score=1.0,
            quality_issues=["one"],
            claude_enriched=True,
        )
        assert report.model == "test-model"
        assert report.prompt_chars == 100
        assert report.context_chars == 50
        assert report.sections_count == 5
        assert report.na_count == 0
        assert report.quality_score == 1.0
        assert report.quality_issues == ["one"]
        assert report.claude_enriched is True
