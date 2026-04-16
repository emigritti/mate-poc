"""
Unit tests — fact_pack_service module (ADR-041).

Coverage:
  - _extract_json_from_llm_response: all four input shapes (pure unit, no mocks)
  - validate_fact_pack: all validation rules (pure unit, no mocks)
  - extract_fact_pack: Claude API path + Ollama fallback path
  - render_document_sections: prompt content and Ollama call
"""

import json
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.fact_pack_service import (
    EvidenceClaim,
    FactPack,
    _extract_json_from_llm_response,
    extract_fact_pack,
    render_document_sections,
    validate_fact_pack,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _minimal_fact_pack(source: str = "SAP", target: str = "Salesforce") -> FactPack:
    """Return a minimal but valid FactPack for use as test input."""
    return FactPack(
        integration_scope={"source": source, "target": target, "direction": "unidirectional"},
        actors=[{"id": "ACT-01", "name": "ERP Operator", "role": "initiator"}],
        systems=[{"id": "SYS-01", "name": source, "role": "source", "protocol": "REST"}],
        entities=[{"name": "Product", "description": "Product master data", "system_of_record": source}],
        business_rules=[{"id": "BR-01", "statement": "Only PUBLISHED products are synced", "source": "explicit"}],
        flows=[{"id": "FLW-01", "name": "Product Sync", "trigger": "schedule", "steps": ["fetch", "push"], "outcome": "data synced"}],
        validations=[{"id": "VAL-01", "field": "product_id", "rule": "not null", "error_code": "400"}],
        errors=[{"id": "ERR-01", "type": "network", "description": "timeout", "handling": "retry"}],
        assumptions=[{"id": "ASM-01", "statement": "Both systems are available 24/7"}],
        open_questions=[],
        evidence=[
            EvidenceClaim("BR-01", "Only PUBLISHED products are synced", ["KB-001-chunk-0"], "confirmed", "confirmed"),
            EvidenceClaim("FLW-01", "Nightly batch sync", ["approved-1"], "inferred", "inferred"),
        ],
    )


def _minimal_json_dict(source: str = "SAP", target: str = "Salesforce") -> dict:
    """Return a dict matching the FactPack JSON schema."""
    return {
        "integration_scope": {"source": source, "target": target, "direction": "unidirectional"},
        "actors": [{"id": "ACT-01", "name": "Operator", "role": "sender"}],
        "systems": [{"id": "SYS-01", "name": source, "role": "source", "protocol": "REST"}],
        "entities": [{"name": "Order", "description": "Sales order", "system_of_record": source}],
        "business_rules": [{"id": "BR-01", "statement": "Only approved orders", "source": "explicit"}],
        "flows": [{"id": "FLW-01", "name": "Order Sync", "trigger": "webhook", "steps": ["receive", "map"], "outcome": "stored"}],
        "validations": [],
        "errors": [],
        "assumptions": [],
        "open_questions": [],
        "evidence": [
            {
                "claim_id": "BR-01",
                "statement": "Only approved orders are synchronized",
                "source_chunks": ["doc-id-1"],
                "confidence": "confirmed",
                "classification": "confirmed",
            }
        ],
    }


# ── _extract_json_from_llm_response (pure unit) ───────────────────────────────

class TestExtractJsonFromLlmResponse:
    def test_plain_json_object(self):
        raw = '{"key": "value", "num": 42}'
        result = _extract_json_from_llm_response(raw)
        assert result == {"key": "value", "num": 42}

    def test_json_with_leading_prose(self):
        raw = 'Here is the JSON:\n{"key": "value"}\nDone.'
        result = _extract_json_from_llm_response(raw)
        assert result == {"key": "value"}

    def test_json_with_markdown_fences(self):
        raw = '```json\n{"key": "value"}\n```'
        result = _extract_json_from_llm_response(raw)
        assert result == {"key": "value"}

    def test_json_with_plain_fences(self):
        raw = '```\n{"key": "value"}\n```'
        result = _extract_json_from_llm_response(raw)
        assert result == {"key": "value"}

    def test_garbage_raises_value_error(self):
        with pytest.raises(ValueError, match="No valid JSON"):
            _extract_json_from_llm_response("This is not JSON at all, sorry.")

    def test_nested_json_extracted(self):
        raw = '{"outer": {"inner": [1, 2, 3]}}'
        result = _extract_json_from_llm_response(raw)
        assert result["outer"]["inner"] == [1, 2, 3]

    def test_whitespace_only_raises_value_error(self):
        with pytest.raises(ValueError):
            _extract_json_from_llm_response("   ")


# ── validate_fact_pack (pure unit) ───────────────────────────────────────────

class TestValidateFactPack:
    def test_valid_pack_has_no_issues(self):
        fp = _minimal_fact_pack("SAP", "Salesforce")
        result = validate_fact_pack(fp, "SAP", "Salesforce")
        assert result.validation_issues == []

    def test_wrong_source_appends_issue(self):
        fp = _minimal_fact_pack("SAP", "Salesforce")
        fp.integration_scope["source"] = "Oracle"
        result = validate_fact_pack(fp, "SAP", "Salesforce")
        assert any("source" in issue.lower() for issue in result.validation_issues)

    def test_wrong_target_appends_issue(self):
        fp = _minimal_fact_pack("SAP", "Salesforce")
        fp.integration_scope["target"] = "HubSpot"
        result = validate_fact_pack(fp, "SAP", "Salesforce")
        assert any("target" in issue.lower() for issue in result.validation_issues)

    def test_empty_flows_appends_issue(self):
        fp = _minimal_fact_pack("SAP", "Salesforce")
        fp.flows = []
        result = validate_fact_pack(fp, "SAP", "Salesforce")
        assert any("flows" in issue for issue in result.validation_issues)

    def test_empty_business_rules_appends_issue(self):
        fp = _minimal_fact_pack("SAP", "Salesforce")
        fp.business_rules = []
        result = validate_fact_pack(fp, "SAP", "Salesforce")
        assert any("business_rules" in issue for issue in result.validation_issues)

    def test_empty_systems_appends_issue(self):
        fp = _minimal_fact_pack("SAP", "Salesforce")
        fp.systems = []
        result = validate_fact_pack(fp, "SAP", "Salesforce")
        assert any("systems" in issue for issue in result.validation_issues)

    def test_duplicate_claim_ids_appends_issue(self):
        fp = _minimal_fact_pack("SAP", "Salesforce")
        fp.evidence.append(
            EvidenceClaim("BR-01", "Duplicate", [], "confirmed", "confirmed")
        )
        result = validate_fact_pack(fp, "SAP", "Salesforce")
        assert any("Duplicate" in issue or "duplicate" in issue.lower() for issue in result.validation_issues)

    def test_invalid_confidence_literal_appends_issue(self):
        fp = _minimal_fact_pack("SAP", "Salesforce")
        # Bypass __init__ type by mutating after construction
        fp.evidence[0].confidence = "invented_state"  # type: ignore[assignment]
        result = validate_fact_pack(fp, "SAP", "Salesforce")
        assert any("confidence" in issue.lower() or "Invalid" in issue for issue in result.validation_issues)

    def test_high_missing_evidence_ratio_appends_advisory(self):
        fp = _minimal_fact_pack("SAP", "Salesforce")
        # Replace all evidence with missing_evidence claims
        fp.evidence = [
            EvidenceClaim(f"OQ-{i:02d}", "Unknown", [], "missing_evidence", "missing_evidence")
            for i in range(10)
        ]
        result = validate_fact_pack(fp, "SAP", "Salesforce")
        assert any("missing_evidence" in issue for issue in result.validation_issues)

    def test_case_insensitive_scope_match(self):
        fp = _minimal_fact_pack("sap", "salesforce")
        # Validation should be case-insensitive
        result = validate_fact_pack(fp, "SAP", "Salesforce")
        scope_issues = [i for i in result.validation_issues if "scope" in i.lower()]
        assert scope_issues == []

    def test_returns_mutated_fact_pack(self):
        fp = _minimal_fact_pack("SAP", "Salesforce")
        returned = validate_fact_pack(fp, "SAP", "Salesforce")
        assert returned is fp  # same object, mutated in place


# ── extract_fact_pack — Claude API path ──────────────────────────────────────

class TestExtractFactPackClaude:
    @pytest.mark.asyncio
    async def test_valid_json_returns_fact_pack(self):
        raw_json = json.dumps(_minimal_json_dict())
        mock_client = _make_mock_claude_client(raw_json)

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            with patch("builtins.__import__", side_effect=_make_anthropic_import(mock_client, raw_json)):
                result = await extract_fact_pack(
                    rag_context="Some context",
                    source="SAP",
                    target="Salesforce",
                    requirements_text="Sync products",
                )
        assert result is not None
        assert result.extraction_model == "claude-sonnet-4-6"
        assert len(result.evidence) == 1
        assert result.evidence[0].claim_id == "BR-01"

    @pytest.mark.asyncio
    async def test_malformed_json_returns_none(self):
        mock_client = _make_mock_claude_client("this is not json")
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            with patch("builtins.__import__", side_effect=_make_anthropic_import(mock_client, "not json")):
                result = await extract_fact_pack("ctx", "SAP", "SF", "reqs")
        assert result is None

    @pytest.mark.asyncio
    async def test_api_error_returns_none(self):
        """Any exception from the Claude API must be caught — returns None."""
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            with patch("builtins.__import__", side_effect=_make_anthropic_import_raises(RuntimeError("API down"))):
                result = await extract_fact_pack("ctx", "SAP", "SF", "reqs")
        assert result is None

    @pytest.mark.asyncio
    async def test_no_api_key_skips_claude_path(self):
        """Without ANTHROPIC_API_KEY the Claude path must not be attempted."""
        with patch.dict("os.environ", {}, clear=False):
            os_env_without_key = {k: v for k, v in __import__("os").environ.items() if k != "ANTHROPIC_API_KEY"}
        with patch("os.environ", os_env_without_key):
            with patch("services.fact_pack_service.generate_with_retry", new_callable=AsyncMock) as mock_gen:
                mock_gen.return_value = "not json"
                result = await extract_fact_pack("ctx", "SAP", "SF", "reqs")
        # Claude was never called (no API key), Ollama attempted but failed JSON parse → None
        assert result is None


# ── extract_fact_pack — Ollama fallback path ─────────────────────────────────

class TestExtractFactPackOllama:
    @pytest.mark.asyncio
    async def test_valid_raw_json_returns_fact_pack(self):
        raw_json = json.dumps(_minimal_json_dict("SAP", "Salesforce"))
        with patch.dict("os.environ", {}, clear=False):
            env = {k: v for k, v in __import__("os").environ.items() if k != "ANTHROPIC_API_KEY"}
        with patch("os.environ", env):
            with patch("services.fact_pack_service.generate_with_retry", new_callable=AsyncMock) as mock_gen:
                mock_gen.return_value = raw_json
                result = await extract_fact_pack("context", "SAP", "Salesforce", "reqs")
        assert result is not None
        assert "ollama" in result.extraction_model
        assert len(result.evidence) >= 1

    @pytest.mark.asyncio
    async def test_json_with_markdown_fences_is_parsed(self):
        data = _minimal_json_dict()
        raw = f"```json\n{json.dumps(data)}\n```"
        with patch.dict("os.environ", {}, clear=False):
            env = {k: v for k, v in __import__("os").environ.items() if k != "ANTHROPIC_API_KEY"}
        with patch("os.environ", env):
            with patch("services.fact_pack_service.generate_with_retry", new_callable=AsyncMock) as mock_gen:
                mock_gen.return_value = raw
                result = await extract_fact_pack("ctx", "SAP", "Salesforce", "reqs")
        assert result is not None

    @pytest.mark.asyncio
    async def test_all_attempts_fail_returns_none(self):
        """When both Ollama attempts return unparseable output, returns None."""
        with patch.dict("os.environ", {}, clear=False):
            env = {k: v for k, v in __import__("os").environ.items() if k != "ANTHROPIC_API_KEY"}
        with patch("os.environ", env):
            with patch("services.fact_pack_service.generate_with_retry", new_callable=AsyncMock) as mock_gen:
                mock_gen.return_value = "I cannot output JSON, sorry."
                result = await extract_fact_pack("ctx", "SAP", "SF", "reqs")
        assert result is None

    @pytest.mark.asyncio
    async def test_temperature_forced_to_zero(self):
        """extract_fact_pack must always call generate_with_retry with temperature=0.0."""
        raw_json = json.dumps(_minimal_json_dict())
        with patch.dict("os.environ", {}, clear=False):
            env = {k: v for k, v in __import__("os").environ.items() if k != "ANTHROPIC_API_KEY"}
        with patch("os.environ", env):
            with patch("services.fact_pack_service.generate_with_retry", new_callable=AsyncMock) as mock_gen:
                mock_gen.return_value = raw_json
                await extract_fact_pack("ctx", "SAP", "Salesforce", "reqs")
                call_kwargs = mock_gen.call_args[1]
                assert call_kwargs.get("temperature") == 0.0

    @pytest.mark.asyncio
    async def test_ollama_exception_returns_none(self):
        with patch.dict("os.environ", {}, clear=False):
            env = {k: v for k, v in __import__("os").environ.items() if k != "ANTHROPIC_API_KEY"}
        with patch("os.environ", env):
            with patch("services.fact_pack_service.generate_with_retry", new_callable=AsyncMock) as mock_gen:
                mock_gen.side_effect = RuntimeError("Ollama down")
                result = await extract_fact_pack("ctx", "SAP", "SF", "reqs")
        assert result is None


# ── render_document_sections ─────────────────────────────────────────────────

class TestRenderDocumentSections:
    @pytest.mark.asyncio
    async def test_returns_llm_output(self):
        fp = _minimal_fact_pack()
        expected = "# Integration Design\n\n## 1. Overview\n\nSome content."
        with patch("services.fact_pack_service.generate_with_retry", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = expected
            result = await render_document_sections(fp, "SAP", "Salesforce", "sync products", "template")
        assert result == expected

    @pytest.mark.asyncio
    async def test_fact_pack_json_in_prompt(self):
        fp = _minimal_fact_pack()
        captured_prompt: list[str] = []

        async def capture(prompt, **kwargs):
            captured_prompt.append(prompt)
            return "# Integration Design\n"

        with patch("services.fact_pack_service.generate_with_retry", side_effect=capture):
            await render_document_sections(fp, "SAP", "Salesforce", "sync products", "## template")

        assert len(captured_prompt) == 1
        prompt = captured_prompt[0]
        # FactPack JSON content is in the prompt
        assert "BR-01" in prompt
        assert "Product Sync" in prompt or "FLW-01" in prompt

    @pytest.mark.asyncio
    async def test_document_template_in_prompt(self):
        fp = _minimal_fact_pack()
        template = "## UNIQUE_TEMPLATE_MARKER_XYZ"
        captured: list[str] = []

        async def capture(prompt, **kwargs):
            captured.append(prompt)
            return "# Integration Design\n"

        with patch("services.fact_pack_service.generate_with_retry", side_effect=capture):
            await render_document_sections(fp, "SAP", "Salesforce", "reqs", template)

        assert "UNIQUE_TEMPLATE_MARKER_XYZ" in captured[0]

    @pytest.mark.asyncio
    async def test_source_and_target_in_prompt(self):
        fp = _minimal_fact_pack("MyERP", "MyCRM")
        captured: list[str] = []

        async def capture(prompt, **kwargs):
            captured.append(prompt)
            return "# Integration Design\n"

        with patch("services.fact_pack_service.generate_with_retry", side_effect=capture):
            await render_document_sections(fp, "MyERP", "MyCRM", "reqs", "template")

        assert "MyERP" in captured[0]
        assert "MyCRM" in captured[0]

    @pytest.mark.asyncio
    async def test_missing_evidence_instruction_in_prompt(self):
        fp = _minimal_fact_pack()
        captured: list[str] = []

        async def capture(prompt, **kwargs):
            captured.append(prompt)
            return "# Integration Design\n"

        with patch("services.fact_pack_service.generate_with_retry", side_effect=capture):
            await render_document_sections(fp, "SAP", "SF", "reqs", "template")

        assert "Evidence gap" in captured[0]
        assert "n/a" not in captured[0].lower() or "never" in captured[0].lower()


# ── Helper factories for Claude mocking ──────────────────────────────────────

def _make_mock_claude_client(response_text: str):
    """Create a mock anthropic.Anthropic client that returns response_text."""
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text=response_text)]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_message
    return mock_client


def _make_anthropic_import(mock_client, response_text: str):
    """
    Return a side_effect for builtins.__import__ that intercepts 'anthropic'.

    We cannot use 'with patch("services.fact_pack_service.anthropic")' because
    the import happens lazily inside the function body. Instead we intercept
    __import__ for the 'anthropic' name.
    """
    import builtins
    real_import = builtins.__import__

    def _patched_import(name, *args, **kwargs):
        if name == "anthropic":
            mock_anthropic = MagicMock()
            mock_anthropic.Anthropic.return_value = mock_client
            return mock_anthropic
        return real_import(name, *args, **kwargs)

    return _patched_import


def _make_anthropic_import_raises(exc: Exception):
    """Return a side_effect for __import__ that raises exc when 'anthropic' is imported."""
    import builtins
    real_import = builtins.__import__

    def _patched_import(name, *args, **kwargs):
        if name == "anthropic":
            raise exc
        return real_import(name, *args, **kwargs)

    return _patched_import
