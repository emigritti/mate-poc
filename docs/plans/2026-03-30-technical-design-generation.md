# Technical Design Document Generation — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** When a functional spec is HITL-approved, expose a "Genera Technical Design" button that triggers a second LLM+RAG generation phase producing a technical design document, using the same approve/reject+feedback HITL loop.

**Architecture:** Add `technical_status` field to `CatalogEntry` (None → TECH_PENDING → TECH_GENERATING → TECH_REVIEW → TECH_DONE). Reuse the entire existing pipeline (hybrid retrieval, ContextAssembler, generate_with_retry, Approval/Document models). New elements: a technical meta-prompt, a `build_technical_prompt()` function, a `generate_technical_doc()` function, and a `/agent/trigger-technical/{id}` endpoint.

**Tech Stack:** FastAPI, Pydantic, asyncio, Motor (async MongoDB), ChromaDB, BM25Plus, bleach, Ollama (llama3.1:8b)

---

## Pre-flight checks

Before starting, verify existing tests pass:
```bash
cd services/integration-agent && python -m pytest tests/ -v --tb=short -q
```
Expected: all 314 tests pass.

---

## Task 1: ADR-038

**Files:**
- Create: `docs/adr/ADR-038-technical-design-generation.md`

**Step 1: Create ADR**

```markdown
# ADR-038 — Two-Phase Document Generation: Technical Design after Functional Approval

**Status:** Accepted
**Date:** 2026-03-30
**Author:** Integration Mate Team

## Context

The Integration Mate PoC generates functional design documents via an LLM+RAG pipeline.
After functional HITL approval, architects need a technical design document.
The existing `Approval.doc_type` and `Document.doc_type` fields already support "technical".

## Decision

Add a second generation phase triggered semi-automatically after functional approval:
- `CatalogEntry.technical_status` field tracks the technical doc lifecycle independently
- A new `POST /api/v1/agent/trigger-technical/{integration_id}` endpoint runs the pipeline
- The same HITL approve/reject+feedback loop reused (doc_type="technical")
- A separate meta-prompt file (`reusable-meta-prompt-technical.md`) drives the technical LLM call
- The approved functional spec is injected as primary context alongside KB RAG

## Alternatives Considered

- **Separate pipeline/models**: More isolation, too much duplication. Rejected.
- **Generic doc-type abstraction**: Extensible but over-engineering for current need. Rejected.
- **Automatic trigger on functional approval**: No explicit user control. Rejected.

## Consequences

- `CatalogEntry` gets a new optional field `technical_status` (backward-compatible: defaults None)
- `sanitize_llm_output()` gains a `doc_type` parameter (backward-compatible: defaults "functional")
- New endpoint added; existing endpoints unchanged
- 8+ new unit tests added

## Validation Plan

1. Unit tests cover all new functions (see Task 10)
2. Manual E2E flow: approve functional → click button → approve technical → view spec
3. Reject+regenerate loop verified with feedback injection

## Rollback Strategy

- Remove `technical_status` field from `CatalogEntry` (Optional → ignored if absent in MongoDB)
- Remove new endpoint from `routers/agent.py`
- Remove new functions from `prompt_builder.py` and `agent_service.py`
- Zero impact on functional doc flow
```

**Step 2: Commit**
```bash
git add docs/adr/ADR-038-technical-design-generation.md
git commit -m "docs(adr): add ADR-038 — two-phase technical design generation"
```

---

## Task 2: Technical Meta-Prompt

**Files:**
- Create: `reusable-meta-prompt-technical.md` (repo root, same level as `reusable-meta-prompt.md`)

**Step 1: Create the technical meta-prompt**

The file must contain a fenced ` ```text ` block (same structure as `reusable-meta-prompt.md`).
The `{functional_spec}` placeholder is the key difference from the functional prompt.

```markdown
# Integration Agent — Technical Meta-Prompt
# Used by: prompt_builder.build_technical_prompt()
# ADR-038: Two-phase document generation

```text
You are a Senior Solution Architect and Integration Expert specializing in enterprise integration patterns (EIP), API design, messaging, and data transformation for PLM, PIM, DAM and Merchandising platforms.

Your task is to produce a complete Technical Design Document for an integration between {source_system} (Source) and {target_system} (Target).

## Input Context

### Requirements
{formatted_requirements}

### Approved Functional Specification
The following functional design has already been approved by the business stakeholders.
Use it as the authoritative source of truth for scope, actors, business rules, and scenarios.

{functional_spec}

### Knowledge Base Reference
{rag_context}

{kb_context}

## Instructions

1. Fill in EVERY section of the technical design template below.
2. For sections with no information, write exactly `n/a` — never leave blank.
3. Derive technical decisions from the functional spec above.
4. Specify concrete protocols, payload schemas, retry policies, and security mechanisms.
5. Preserve the exact template structure — do not add or remove sections.
6. Output ONLY valid Markdown. Do not add any preamble or explanation before the document.

## Template

{document_template}

Begin immediately with `# Integration Technical Design`. No preamble.
```
```

Note: the triple-backtick fence inside the file must be exact (` ```text ` on its own line, then ` ``` ` to close).

**Step 2: Commit**
```bash
git add reusable-meta-prompt-technical.md
git commit -m "feat(agent): add technical meta-prompt for two-phase doc generation"
```

---

## Task 3: Schema — add technical_status

**Files:**
- Modify: `services/integration-agent/schemas.py:32-42`

**Step 1: Write the failing test**

In `services/integration-agent/tests/test_technical_doc_generation.py` (create new file):

```python
"""
Unit tests for technical design document generation.
ADR-038: Two-phase doc generation — technical spec after functional approval.
"""
import pytest
from schemas import CatalogEntry


def test_catalog_entry_has_technical_status_field():
    entry = CatalogEntry(
        id="TEST-001",
        name="Test Integration",
        type="data_sync",
        source={"system": "PLM"},
        target={"system": "PIM"},
        requirements=["REQ-001"],
        status="DONE",
        created_at="2026-03-30T00:00:00Z",
    )
    assert hasattr(entry, "technical_status")
    assert entry.technical_status is None


def test_catalog_entry_technical_status_can_be_set():
    entry = CatalogEntry(
        id="TEST-001",
        name="Test Integration",
        type="data_sync",
        source={"system": "PLM"},
        target={"system": "PIM"},
        requirements=["REQ-001"],
        status="DONE",
        technical_status="TECH_PENDING",
        created_at="2026-03-30T00:00:00Z",
    )
    assert entry.technical_status == "TECH_PENDING"
```

**Step 2: Run test to verify it fails**
```bash
cd services/integration-agent && python -m pytest tests/test_technical_doc_generation.py::test_catalog_entry_has_technical_status_field -v
```
Expected: `FAILED` — `CatalogEntry has no field 'technical_status'`

**Step 3: Add field to CatalogEntry**

In `services/integration-agent/schemas.py`, add after line 42 (`created_at: str`):

```python
    technical_status: Optional[str] = None  # ADR-038: None|TECH_PENDING|TECH_GENERATING|TECH_REVIEW|TECH_DONE
```

**Step 4: Run tests to verify they pass**
```bash
cd services/integration-agent && python -m pytest tests/test_technical_doc_generation.py -v
```
Expected: 2 PASSED

**Step 5: Run full suite to check no regression**
```bash
cd services/integration-agent && python -m pytest tests/ -v --tb=short -q
```
Expected: 314 + 2 = 316 pass

**Step 6: Commit**
```bash
git add services/integration-agent/schemas.py services/integration-agent/tests/test_technical_doc_generation.py
git commit -m "feat(schema): add technical_status field to CatalogEntry (ADR-038)"
```

---

## Task 4: Output Guard — add doc_type param

**Files:**
- Modify: `services/integration-agent/output_guard.py:37,52`

**Step 1: Add tests**

In `services/integration-agent/tests/test_technical_doc_generation.py`, add:

```python
from output_guard import sanitize_llm_output, LLMOutputValidationError


def test_sanitize_llm_output_technical_valid():
    raw = "# Integration Technical Design\n\n## 1. Purpose\nTest content here with enough words to pass quality.\n"
    result = sanitize_llm_output(raw, doc_type="technical")
    assert result.startswith("# Integration Technical Design")


def test_sanitize_llm_output_technical_invalid_heading():
    raw = "# Integration Functional Design\n\n## 1. Purpose\nWrong heading for technical doc.\n"
    with pytest.raises(LLMOutputValidationError):
        sanitize_llm_output(raw, doc_type="technical")


def test_sanitize_llm_output_technical_strips_preamble():
    raw = "Here is the document:\n\n# Integration Technical Design\n\n## 1. Purpose\nContent.\n"
    result = sanitize_llm_output(raw, doc_type="technical")
    assert result.startswith("# Integration Technical Design")


def test_sanitize_llm_output_functional_unchanged():
    """Existing functional behavior must not regress."""
    raw = "# Integration Functional Design\n\n## 1. Overview\nContent here.\n"
    result = sanitize_llm_output(raw, doc_type="functional")
    assert result.startswith("# Integration Functional Design")


def test_sanitize_llm_output_default_is_functional():
    """doc_type defaults to functional — no breaking change."""
    raw = "# Integration Functional Design\n\n## 1. Overview\nContent.\n"
    result = sanitize_llm_output(raw)
    assert result.startswith("# Integration Functional Design")
```

**Step 2: Run to verify they fail**
```bash
cd services/integration-agent && python -m pytest tests/test_technical_doc_generation.py -k "sanitize" -v
```
Expected: `FAILED` — `sanitize_llm_output() got unexpected keyword argument 'doc_type'`

**Step 3: Modify output_guard.py**

Change line 37 to define the heading map, and update `sanitize_llm_output` signature:

```python
# Replace line 37:
_REQUIRED_PREFIX: str = "# Integration Functional Design"

# With:
_REQUIRED_PREFIX_BY_TYPE: dict[str, str] = {
    "functional": "# Integration Functional Design",
    "technical":  "# Integration Technical Design",
}
# Keep _REQUIRED_PREFIX as alias for backward compat (used in tests directly)
_REQUIRED_PREFIX: str = _REQUIRED_PREFIX_BY_TYPE["functional"]
```

Change `sanitize_llm_output` signature at line 52:

```python
def sanitize_llm_output(raw: str, doc_type: str = "functional") -> str:
    """
    Validate and sanitize LLM-generated markdown (strict mode).
    ...
    """
    required_prefix = _REQUIRED_PREFIX_BY_TYPE.get(doc_type, _REQUIRED_PREFIX_BY_TYPE["functional"])

    if not raw or not raw.strip():
        raise LLMOutputValidationError("LLM returned empty output.")

    text = raw.strip()

    if text.startswith(required_prefix):
        return _apply_bleach_and_truncate(text)

    idx = text.find(required_prefix)
    if idx != -1:
        logger.warning(
            "[OutputGuard] Preamble detected (%d chars stripped) before '%s'.",
            idx,
            required_prefix,
        )
        return _apply_bleach_and_truncate(text[idx:])

    raise LLMOutputValidationError(
        f"Output must contain '{required_prefix}'. "
        "Got: {!r}".format(text[:120])
    )
```

**Step 4: Run tests**
```bash
cd services/integration-agent && python -m pytest tests/test_technical_doc_generation.py -k "sanitize" -v
```
Expected: 5 PASSED

**Step 5: Full suite**
```bash
cd services/integration-agent && python -m pytest tests/ -v --tb=short -q
```
Expected: all existing + new tests pass

**Step 6: Commit**
```bash
git add services/integration-agent/output_guard.py services/integration-agent/tests/test_technical_doc_generation.py
git commit -m "feat(output-guard): add doc_type param to sanitize_llm_output (ADR-038)"
```

---

## Task 5: Prompt Builder — add build_technical_prompt

**Files:**
- Modify: `services/integration-agent/prompt_builder.py`

**Step 1: Add tests**

```python
import pathlib
from unittest.mock import patch


def test_build_technical_prompt_includes_functional_spec():
    from prompt_builder import build_technical_prompt
    result = build_technical_prompt(
        source_system="PLM",
        target_system="PIM",
        formatted_requirements="Sync product catalog every 6h",
        functional_spec="# Integration Functional Design\n\n## 1. Overview\nTest spec.",
        rag_context="",
        kb_context="",
    )
    assert "PLM" in result
    assert "PIM" in result
    assert "Sync product catalog" in result
    assert "Integration Functional Design" in result


def test_build_technical_prompt_with_feedback():
    from prompt_builder import build_technical_prompt
    result = build_technical_prompt(
        source_system="PLM",
        target_system="PIM",
        formatted_requirements="Sync products",
        functional_spec="# Integration Functional Design\nSpec content.",
        rag_context="",
        kb_context="",
        reviewer_feedback="Missing retry policy details",
    )
    assert "Missing retry policy details" in result
    assert "PREVIOUS REJECTION FEEDBACK" in result


def test_build_technical_prompt_empty_functional_spec():
    from prompt_builder import build_technical_prompt
    result = build_technical_prompt(
        source_system="PLM",
        target_system="PIM",
        formatted_requirements="Req 1",
        functional_spec="",
        rag_context="",
        kb_context="",
    )
    # Should not crash; placeholder just empty
    assert "PLM" in result
```

**Step 2: Run to verify they fail**
```bash
cd services/integration-agent && python -m pytest tests/test_technical_doc_generation.py -k "build_technical_prompt" -v
```
Expected: `FAILED` — `cannot import name 'build_technical_prompt'`

**Step 3: Add to prompt_builder.py**

After the existing imports and constants, add:

```python
# ── Technical prompt file paths ──────────────────────────────────────────────
_TECHNICAL_PROMPT_FILE = pathlib.Path(__file__).parent.parent.parent / "reusable-meta-prompt-technical.md"
_TECHNICAL_TEMPLATE_PATH = (
    pathlib.Path(__file__).parent.parent.parent
    / "template"
    / "technical"
    / "integration-technical-design.md"
)

_FALLBACK_TECHNICAL_TEMPLATE = (
    "You are a Senior Solution Architect.\n"
    "Produce a technical design for the integration between "
    "{source_system} (Source) and {target_system} (Target).\n"
    "Requirements:\n{formatted_requirements}\n\n"
    "Functional Spec:\n{functional_spec}\n\n"
    "{rag_context}\n\n{kb_context}\n\n"
    "TEMPLATE:\n{document_template}\n\n"
    "Output ONLY valid Markdown. Begin immediately with "
    "`# Integration Technical Design`."
)


def _load_technical_prompt() -> str:
    """Extract the fenced ``text`` block from the technical meta-prompt file."""
    try:
        raw = _TECHNICAL_PROMPT_FILE.read_text(encoding="utf-8")
        match = re.search(r"```text\n(.*?)```", raw, re.DOTALL)
        if match:
            logger.info("[PromptBuilder] Loaded technical meta-prompt from %s", _TECHNICAL_PROMPT_FILE)
            return match.group(1).strip()
        logger.warning(
            "[PromptBuilder] No ```text``` block in %s — using fallback.", _TECHNICAL_PROMPT_FILE
        )
    except FileNotFoundError:
        logger.warning(
            "[PromptBuilder] %s not found — using fallback.", _TECHNICAL_PROMPT_FILE
        )
    return _FALLBACK_TECHNICAL_TEMPLATE


def _load_technical_template() -> str:
    """Load and unescape the technical design template."""
    try:
        content = _TECHNICAL_TEMPLATE_PATH.read_text(encoding="utf-8")
        content = content.replace(r"\### ", "### ")
        content = content.replace(r"\## ", "## ")
        content = content.replace(r"\# ", "# ")
        content = content.replace(r"\- ", "- ")
        content = content.replace(r"\| ", "| ")
        logger.info("[PromptBuilder] Loaded technical template from %s", _TECHNICAL_TEMPLATE_PATH)
        return content
    except FileNotFoundError:
        logger.warning(
            "[PromptBuilder] %s not found — {document_template} slot will be empty.",
            _TECHNICAL_TEMPLATE_PATH,
        )
        return ""


_TECHNICAL_PROMPT: str = _load_technical_prompt()
_TECHNICAL_TEMPLATE: str = _load_technical_template()


def build_technical_prompt(
    source_system: str,
    target_system: str,
    formatted_requirements: str,
    functional_spec: str,
    rag_context: str = "",
    kb_context: str = "",
    reviewer_feedback: str = "",
) -> str:
    """
    Populate the technical meta-prompt with runtime values.

    The functional_spec (approved functional design) is injected as primary context.
    Same feedback/RAG injection pattern as build_prompt().

    Returns:
        A fully populated prompt string ready to be sent to the LLM.
    """
    feedback_block = (
        f"## PREVIOUS REJECTION FEEDBACK (address these issues in your output):\n"
        f"{reviewer_feedback.strip()}\n\n"
        if reviewer_feedback.strip()
        else ""
    )
    rag_block = (
        f"PAST APPROVED EXAMPLES:\n{rag_context}"
        if rag_context.strip()
        else ""
    )
    kb_block = (
        f"BEST PRACTICES REFERENCE:\n{kb_context}"
        if kb_context.strip()
        else ""
    )
    combined_context = f"{feedback_block}{rag_block}" if feedback_block else rag_block

    result = _TECHNICAL_PROMPT
    result = result.replace("{source_system}", source_system)
    result = result.replace("{target_system}", target_system)
    result = result.replace("{formatted_requirements}", formatted_requirements)
    result = result.replace("{functional_spec}", functional_spec)
    result = result.replace("{rag_context}", combined_context)
    result = result.replace("{kb_context}", kb_block)
    result = result.replace("{document_template}", _TECHNICAL_TEMPLATE)
    return result
```

**Step 4: Run tests**
```bash
cd services/integration-agent && python -m pytest tests/test_technical_doc_generation.py -k "build_technical_prompt" -v
```
Expected: 3 PASSED

**Step 5: Full suite**
```bash
cd services/integration-agent && python -m pytest tests/ --tb=short -q
```
Expected: all pass

**Step 6: Commit**
```bash
git add services/integration-agent/prompt_builder.py services/integration-agent/tests/test_technical_doc_generation.py
git commit -m "feat(prompt-builder): add build_technical_prompt() for technical doc generation"
```

---

## Task 6: Agent Service — add generate_technical_doc

**Files:**
- Modify: `services/integration-agent/services/agent_service.py`

**Step 1: Add tests**

```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_generate_technical_doc_calls_rag_and_llm():
    from services.agent_service import generate_technical_doc
    from schemas import CatalogEntry

    entry = CatalogEntry(
        id="PLM-001",
        name="PLM→PIM Sync",
        type="data_sync",
        source={"system": "PLM"},
        target={"system": "PIM"},
        requirements=["REQ-001"],
        status="DONE",
        tags=["plm", "pim"],
        created_at="2026-03-30T00:00:00Z",
    )
    functional_spec = "# Integration Functional Design\n\n## 1. Overview\nApproved spec."

    with patch("services.agent_service.hybrid_retriever") as mock_retriever, \
         patch("services.agent_service.generate_with_retry", new_callable=AsyncMock) as mock_llm, \
         patch("services.agent_service.state") as mock_state:

        mock_retriever.retrieve = AsyncMock(return_value=[])
        mock_retriever.retrieve_summaries = AsyncMock(return_value=[])
        mock_state.kb_collection = MagicMock()
        mock_state.kb_docs = {}
        mock_state.summaries_col = MagicMock()
        mock_llm.return_value = "# Integration Technical Design\n\n## 1. Purpose\nTest content " * 10

        result = await generate_technical_doc(entry, functional_spec)

    assert result.startswith("# Integration Technical Design")
    mock_llm.assert_called_once()


@pytest.mark.asyncio
async def test_generate_technical_doc_uses_functional_spec_in_prompt():
    """The functional spec must appear in the prompt sent to the LLM."""
    from services.agent_service import generate_technical_doc
    from schemas import CatalogEntry

    entry = CatalogEntry(
        id="PLM-001",
        name="Test",
        type="data_sync",
        source={"system": "PLM"},
        target={"system": "PIM"},
        requirements=["REQ-001"],
        status="DONE",
        tags=["plm"],
        created_at="2026-03-30T00:00:00Z",
    )
    functional_spec = "UNIQUE_FUNCTIONAL_SPEC_MARKER_12345"

    captured_prompt = []

    async def capture_prompt(prompt, **kwargs):
        captured_prompt.append(prompt)
        return "# Integration Technical Design\n\n## 1. Purpose\nContent " * 10

    with patch("services.agent_service.hybrid_retriever") as mock_retriever, \
         patch("services.agent_service.generate_with_retry", side_effect=capture_prompt), \
         patch("services.agent_service.state") as mock_state:

        mock_retriever.retrieve = AsyncMock(return_value=[])
        mock_retriever.retrieve_summaries = AsyncMock(return_value=[])
        mock_state.kb_collection = MagicMock()
        mock_state.kb_docs = {}
        mock_state.summaries_col = MagicMock()

        await generate_technical_doc(entry, functional_spec)

    assert "UNIQUE_FUNCTIONAL_SPEC_MARKER_12345" in captured_prompt[0]
```

**Step 2: Run to verify they fail**
```bash
cd services/integration-agent && python -m pytest tests/test_technical_doc_generation.py -k "generate_technical_doc" -v
```
Expected: `FAILED` — `cannot import name 'generate_technical_doc'`

**Step 3: Add generate_technical_doc to agent_service.py**

```python
# Add import at top of agent_service.py:
from prompt_builder import build_prompt, build_technical_prompt

# Add after generate_integration_doc():

async def generate_technical_doc(
    entry,                                         # CatalogEntry
    functional_spec_content: str,
    reviewer_feedback: str = "",
    log_fn: Callable[[str], None] | None = None,
) -> str:
    """
    Run the RAG + LLM pipeline to generate a technical design document.

    ADR-038: Second phase of two-phase doc generation.
    Uses the approved functional spec as primary context, plus KB RAG.

    Args:
        entry:                   CatalogEntry (source, target, tags)
        functional_spec_content: Approved functional spec markdown (primary context)
        reviewer_feedback:       Optional HITL rejection feedback for regeneration
        log_fn:                  Optional logging callback

    Returns:
        Sanitized markdown string starting with "# Integration Technical Design".

    Raises:
        LLMOutputValidationError: if output guard rejects the LLM output.
        httpx.*: on LLM connectivity errors — caller must handle these.
    """
    _log = log_fn or logger.info

    source = entry.source.get("system", "Unknown")
    target = entry.target.get("system", "Unknown")
    query_text = f"technical design {source} {target} " + " ".join(entry.tags)
    category = entry.tags[0] if entry.tags else ""

    _log(f"[RAG-TECH] KB retrieval for {entry.id} (tags={entry.tags})...")
    kb_scored_chunks = await hybrid_retriever.retrieve(
        query_text, entry.tags, state.kb_collection,
        source=source, target=target, category=category, log_fn=_log,
    )
    summary_chunks = await hybrid_retriever.retrieve_summaries(
        query_text, entry.tags, state.summaries_col,
    )
    url_raw = await fetch_url_kb_context(entry.tags, state.kb_docs, log_fn=_log)
    url_chunks = (
        [ScoredChunk(text=url_raw, score=0.5, source_label="kb_url")]
        if url_raw else []
    )

    assembler = ContextAssembler()
    rag_context = assembler.assemble(
        [], kb_scored_chunks, url_chunks,
        max_chars=settings.ollama_rag_max_chars,
        summary_chunks=summary_chunks,
    )
    _log(f"[RAG-TECH] Assembled context: {len(rag_context)} chars")

    formatted_requirements = f"{source} → {target} integration"

    prompt = build_technical_prompt(
        source_system=source,
        target_system=target,
        formatted_requirements=formatted_requirements,
        functional_spec=functional_spec_content,
        rag_context=rag_context,
        reviewer_feedback=reviewer_feedback,
    )
    _log(f"[LLM-TECH] Prompt ready for {entry.id} — {len(prompt)} chars. Calling {settings.ollama_model}...")

    raw = await generate_with_retry(prompt, log_fn=_log)
    return sanitize_llm_output(raw, doc_type="technical")
```

**Step 4: Run tests**
```bash
cd services/integration-agent && python -m pytest tests/test_technical_doc_generation.py -k "generate_technical_doc" -v
```
Expected: 2 PASSED

**Step 5: Full suite**
```bash
cd services/integration-agent && python -m pytest tests/ --tb=short -q
```
Expected: all pass

**Step 6: Commit**
```bash
git add services/integration-agent/services/agent_service.py services/integration-agent/tests/test_technical_doc_generation.py
git commit -m "feat(agent-service): add generate_technical_doc() for technical design phase"
```

---

## Task 7: Approvals Router — set TECH_PENDING on functional approval

**Files:**
- Modify: `services/integration-agent/routers/approvals.py:56-80`

**Step 1: Add test**

```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient


def test_approve_functional_sets_tech_pending():
    """When a functional approval is approved, CatalogEntry.technical_status must become TECH_PENDING."""
    from schemas import Approval, CatalogEntry

    # Setup in-memory state
    entry = CatalogEntry(
        id="PLM-001",
        name="PLM→PIM",
        type="data_sync",
        source={"system": "PLM"},
        target={"system": "PIM"},
        requirements=["REQ-001"],
        status="DONE",
        created_at="2026-03-30T00:00:00Z",
    )
    approval = Approval(
        id="APP-AAA001",
        integration_id="PLM-001",
        doc_type="functional",
        content="# Integration Functional Design\nContent",
        status="PENDING",
        generated_at="2026-03-30T00:00:00Z",
    )

    with patch("routers.approvals.state") as mock_state, \
         patch("routers.approvals.db") as mock_db:

        mock_state.approvals = {"APP-AAA001": approval}
        mock_state.catalog = {"PLM-001": entry}
        mock_state.documents = {}
        mock_db.approvals_col = None
        mock_db.documents_col = None
        mock_db.catalog_col = None

        import asyncio
        from routers.approvals import approve_doc
        from schemas import ApproveRequest

        asyncio.run(approve_doc(
            id="APP-AAA001",
            body=ApproveRequest(final_markdown="# Integration Functional Design\nApproved content"),
            _token="test",
        ))

    assert entry.technical_status == "TECH_PENDING"
```

**Step 2: Run to verify it fails**
```bash
cd services/integration-agent && python -m pytest tests/test_technical_doc_generation.py::test_approve_functional_sets_tech_pending -v
```
Expected: `FAILED` — `assert None == 'TECH_PENDING'`

**Step 3: Modify approvals.py — add after line 78 (after `record_event` call)**

In `approve_doc`, after the `await record_event(...)` line, add:

```python
    # ADR-038: when functional spec approved, unlock technical design phase
    if app_entry.doc_type == "functional":
        catalog_entry = state.catalog.get(app_entry.integration_id)
        if catalog_entry is not None:
            catalog_entry.technical_status = "TECH_PENDING"
            if db.catalog_col is not None:
                await db.catalog_col.replace_one(
                    {"id": catalog_entry.id}, catalog_entry.model_dump(), upsert=True
                )
```

Also add `import db` is already present; no new imports needed.

**Step 4: Run test**
```bash
cd services/integration-agent && python -m pytest tests/test_technical_doc_generation.py::test_approve_functional_sets_tech_pending -v
```
Expected: PASSED

**Step 5: Full suite**
```bash
cd services/integration-agent && python -m pytest tests/ --tb=short -q
```
Expected: all pass

**Step 6: Commit**
```bash
git add services/integration-agent/routers/approvals.py services/integration-agent/tests/test_technical_doc_generation.py
git commit -m "feat(approvals): set technical_status=TECH_PENDING on functional approval (ADR-038)"
```

---

## Task 8: Agent Router — trigger-technical endpoint + regenerate for technical

**Files:**
- Modify: `services/integration-agent/routers/agent.py`
- Modify: `services/integration-agent/routers/approvals.py` (regenerate endpoint)

**Step 1: Add tests**

```python
def test_trigger_technical_rejects_when_not_tech_pending():
    """Should return 409 if technical_status is not TECH_PENDING."""
    from schemas import CatalogEntry

    entry = CatalogEntry(
        id="PLM-001",
        name="PLM→PIM",
        type="data_sync",
        source={"system": "PLM"},
        target={"system": "PIM"},
        requirements=["REQ-001"],
        status="DONE",
        technical_status=None,  # not TECH_PENDING
        created_at="2026-03-30T00:00:00Z",
    )

    with patch("routers.agent.state") as mock_state:
        mock_state.catalog = {"PLM-001": entry}

        import asyncio
        from fastapi import HTTPException
        from routers.agent import trigger_technical

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(trigger_technical(integration_id="PLM-001", _token="test"))

        assert exc_info.value.status_code == 409


def test_trigger_technical_rejects_when_functional_spec_missing():
    """Should return 404 if no approved functional spec exists."""
    from schemas import CatalogEntry

    entry = CatalogEntry(
        id="PLM-001",
        name="PLM→PIM",
        type="data_sync",
        source={"system": "PLM"},
        target={"system": "PIM"},
        requirements=["REQ-001"],
        status="DONE",
        technical_status="TECH_PENDING",
        created_at="2026-03-30T00:00:00Z",
    )

    with patch("routers.agent.state") as mock_state:
        mock_state.catalog = {"PLM-001": entry}
        mock_state.documents = {}  # no functional spec

        import asyncio
        from fastapi import HTTPException
        from routers.agent import trigger_technical

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(trigger_technical(integration_id="PLM-001", _token="test"))

        assert exc_info.value.status_code == 404
```

**Step 2: Run to verify they fail**
```bash
cd services/integration-agent && python -m pytest tests/test_technical_doc_generation.py -k "trigger_technical" -v
```
Expected: `FAILED` — `cannot import name 'trigger_technical'`

**Step 3: Add trigger_technical to routers/agent.py**

Add these imports at top of agent.py:
```python
from services.agent_service import generate_integration_doc, generate_technical_doc
from output_guard import LLMOutputValidationError, assess_quality
```

Add after the existing endpoints:

```python
@router.post("/agent/trigger-technical/{integration_id}")
async def trigger_technical(
    integration_id: str,
    _token: str = Depends(require_token),
) -> dict:
    """
    Trigger technical design generation for a single integration.

    ADR-038: Second phase — only available after functional spec is approved.
    Unlike the functional agent, runs synchronously within the request
    (no separate asyncio.Lock needed — each integration is independent).

    Preconditions:
      - integration exists in catalog
      - technical_status == "TECH_PENDING"
      - functional spec exists in state.documents

    Returns:
        {"status": "success", "approval_id": "APP-XXXXXX"}
    """
    entry = state.catalog.get(integration_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Integration '{integration_id}' not found.")

    if entry.technical_status != "TECH_PENDING":
        raise HTTPException(
            status_code=409,
            detail=(
                f"Technical generation requires technical_status='TECH_PENDING'. "
                f"Current: {entry.technical_status!r}"
            ),
        )

    func_doc = state.documents.get(f"{integration_id}-functional")
    if func_doc is None:
        raise HTTPException(
            status_code=404,
            detail=f"Approved functional spec for '{integration_id}' not found. Approve functional design first.",
        )

    # Mark as generating
    entry.technical_status = "TECH_GENERATING"
    if db.catalog_col is not None:
        await db.catalog_col.replace_one({"id": entry.id}, entry.model_dump(), upsert=True)

    try:
        tech_content = await generate_technical_doc(
            entry=entry,
            functional_spec_content=func_doc.content,
            reviewer_feedback="",
            log_fn=logger.info,
        )
    except LLMOutputValidationError as exc:
        entry.technical_status = "TECH_PENDING"  # revert on failure
        if db.catalog_col is not None:
            await db.catalog_col.replace_one({"id": entry.id}, entry.model_dump(), upsert=True)
        raise HTTPException(status_code=422, detail=f"Technical output failed structural guard: {exc}")
    except Exception as exc:
        entry.technical_status = "TECH_PENDING"
        if db.catalog_col is not None:
            await db.catalog_col.replace_one({"id": entry.id}, entry.model_dump(), upsert=True)
        raise HTTPException(status_code=503, detail=f"LLM unavailable: {exc}")

    # Quality assessment (non-destructive)
    quality = assess_quality(tech_content)
    if not quality.passed:
        logger.warning(
            "[TECH-QUALITY] Low quality score %.2f for %s — %s",
            quality.quality_score, integration_id, "; ".join(quality.issues),
        )

    app_id = f"APP-{uuid.uuid4().hex[:6].upper()}"
    approval = Approval(
        id=app_id,
        integration_id=integration_id,
        doc_type="technical",
        content=tech_content,
        status="PENDING",
        generated_at=_now_iso(),
    )
    state.approvals[app_id] = approval
    if db.approvals_col is not None:
        await db.approvals_col.replace_one({"id": app_id}, approval.model_dump(), upsert=True)

    entry.technical_status = "TECH_REVIEW"
    if db.catalog_col is not None:
        await db.catalog_col.replace_one({"id": entry.id}, entry.model_dump(), upsert=True)

    logger.info("[TECH] Technical approval %s queued for HITL review (integration: %s)", app_id, integration_id)
    return {"status": "success", "approval_id": app_id}
```

**Step 4: Modify regenerate endpoint in approvals.py to support technical doc_type**

In `regenerate_doc` (approvals.py:114+), the current code calls `generate_integration_doc()` unconditionally. Add branching for technical:

```python
# Replace the generate_integration_doc call block:
    try:
        if app_entry.doc_type == "technical":
            func_doc = state.documents.get(f"{app_entry.integration_id}-functional")
            if func_doc is None:
                raise HTTPException(
                    status_code=409,
                    detail="Cannot regenerate technical doc: approved functional spec not found.",
                )
            from services.agent_service import generate_technical_doc
            new_content = await generate_technical_doc(
                entry=entry,
                functional_spec_content=func_doc.content,
                reviewer_feedback=app_entry.feedback,
                log_fn=logger.info,
            )
        else:
            new_content = await generate_integration_doc(
                entry=entry,
                requirements=requirements,
                reviewer_feedback=app_entry.feedback,
                log_fn=logger.info,
            )
```

Also update the `TECH_REVIEW` status when a technical approval is regenerated. After creating `new_approval`, add:

```python
    # ADR-038: keep technical_status in sync
    if app_entry.doc_type == "technical":
        catalog_entry = state.catalog.get(app_entry.integration_id)
        if catalog_entry is not None:
            catalog_entry.technical_status = "TECH_REVIEW"
            if db.catalog_col is not None:
                await db.catalog_col.replace_one(
                    {"id": catalog_entry.id}, catalog_entry.model_dump(), upsert=True
                )
```

**Step 5: Run tests**
```bash
cd services/integration-agent && python -m pytest tests/test_technical_doc_generation.py -k "trigger_technical" -v
```
Expected: 2 PASSED

**Step 6: Full suite**
```bash
cd services/integration-agent && python -m pytest tests/ --tb=short -q
```
Expected: all pass

**Step 7: Commit**
```bash
git add services/integration-agent/routers/agent.py services/integration-agent/routers/approvals.py services/integration-agent/tests/test_technical_doc_generation.py
git commit -m "feat(agent): add trigger-technical endpoint + technical regen support (ADR-038)"
```

---

## Task 9: Catalog Router — implement technical-spec endpoint

**Files:**
- Modify: `services/integration-agent/routers/catalog.py:76-79`

**Step 1: Replace the stub**

Replace lines 76-79:
```python
@router.get("/catalog/integrations/{id}/technical-spec")
async def get_tech_spec(id: str) -> dict:
    return {"status": "error", "message": "Technical specs generation is not yet implemented."}
```

With:
```python
@router.get("/catalog/integrations/{id}/technical-spec")
async def get_tech_spec(id: str) -> dict:
    doc = state.documents.get(f"{id}-technical")
    if not doc:
        return {"status": "error", "message": "Technical design not approved yet or not found."}
    return {"status": "success", "data": doc.model_dump()}
```

**Step 2: Also update approve_doc in approvals.py to set TECH_DONE on technical approval**

In `approve_doc`, the existing ADR-038 block only handles `doc_type == "functional"`. Add handling for `doc_type == "technical"` to set `TECH_DONE`:

```python
    # ADR-038: lifecycle tracking
    if app_entry.doc_type == "functional":
        catalog_entry = state.catalog.get(app_entry.integration_id)
        if catalog_entry is not None:
            catalog_entry.technical_status = "TECH_PENDING"
            if db.catalog_col is not None:
                await db.catalog_col.replace_one(
                    {"id": catalog_entry.id}, catalog_entry.model_dump(), upsert=True
                )
    elif app_entry.doc_type == "technical":
        catalog_entry = state.catalog.get(app_entry.integration_id)
        if catalog_entry is not None:
            catalog_entry.technical_status = "TECH_DONE"
            if db.catalog_col is not None:
                await db.catalog_col.replace_one(
                    {"id": catalog_entry.id}, catalog_entry.model_dump(), upsert=True
                )
```

**Step 3: Full suite**
```bash
cd services/integration-agent && python -m pytest tests/ --tb=short -q
```
Expected: all pass

**Step 4: Commit**
```bash
git add services/integration-agent/routers/catalog.py services/integration-agent/routers/approvals.py
git commit -m "feat(catalog): implement technical-spec endpoint + TECH_DONE on approval (ADR-038)"
```

---

## Task 10: Frontend — UI changes

**Files:**
- Modify: `services/web-dashboard/js/app.js`

The frontend needs 3 changes. Search for the existing "View Functional Spec" button logic to find the right insertion points.

**Step 1: Add "Genera Technical Design" button in Catalog tab**

Find where functional spec button is rendered in the catalog row (search for `functional-spec` or `View Functional Spec`). After that block, add:

```javascript
// After the "View Functional Spec" button block:
if (item.technical_status === 'TECH_PENDING') {
    const techBtn = document.createElement('button');
    techBtn.textContent = 'Genera Technical Design';
    techBtn.className = 'btn btn-secondary btn-sm ml-2';
    techBtn.onclick = async () => {
        techBtn.disabled = true;
        techBtn.textContent = 'Generating...';
        try {
            const res = await apiCall(`/api/v1/agent/trigger-technical/${item.id}`, { method: 'POST' });
            if (res.status === 'success') {
                showNotification(`Technical design queued: ${res.approval_id}`, 'success');
                refreshCatalog();
            } else {
                showNotification('Generation failed: ' + (res.detail || 'Unknown error'), 'error');
                techBtn.disabled = false;
                techBtn.textContent = 'Genera Technical Design';
            }
        } catch (e) {
            showNotification('Error: ' + e.message, 'error');
            techBtn.disabled = false;
            techBtn.textContent = 'Genera Technical Design';
        }
    };
    actionsCell.appendChild(techBtn);
}

if (item.technical_status === 'TECH_GENERATING' || item.technical_status === 'TECH_REVIEW') {
    const techStatus = document.createElement('span');
    techStatus.className = 'badge badge-info ml-2';
    techStatus.textContent = item.technical_status === 'TECH_GENERATING' ? '⏳ Generating Technical...' : '🔍 Technical Review Pending';
    actionsCell.appendChild(techStatus);
}

if (item.technical_status === 'TECH_DONE') {
    const techLink = document.createElement('button');
    techLink.textContent = 'View Technical Spec';
    techLink.className = 'btn btn-outline-success btn-sm ml-2';
    techLink.onclick = () => showDocumentModal(item.id, 'technical');
    actionsCell.appendChild(techLink);
}
```

**Step 2: Add technical spec modal support**

Find the existing `showDocumentModal` function (or `showFunctionalSpec` / similar). Extend it to accept a `docType` parameter and call the appropriate endpoint:

```javascript
async function showDocumentModal(integrationId, docType = 'functional') {
    const endpoint = docType === 'technical'
        ? `/api/v1/catalog/integrations/${integrationId}/technical-spec`
        : `/api/v1/catalog/integrations/${integrationId}/functional-spec`;
    // ... rest of existing modal logic using `endpoint`
}
```

**Step 3: Approvals tab already works** — the existing approvals list renders `doc_type` for each item and the approve/reject/regenerate buttons work regardless of doc_type.

**Step 4: Commit**
```bash
git add services/web-dashboard/js/app.js
git commit -m "feat(ui): add Genera Technical Design button + Technical Spec view (ADR-038)"
```

---

## Task 11: Documentation

**Files:**
- Create: `HOW-TO/07-generate-technical-design.md`
- Modify: `docs/architecture_specification.md`
- Modify: `docs/functional-guide.md`

**Step 1: Create HOW-TO guide**

```markdown
# 07 — Generare il Technical Design Document

Dopo l'approvazione della functional spec, genera automaticamente il documento tecnico.

**Flusso:** Approve Functional → click "Genera Technical Design" → HITL approve → Technical Spec nel Catalog.

---

## Prerequisiti

- Functional spec approvata (status DONE in Catalog)
- Sistema avviato: `docker compose up -d`

---

## Via Dashboard (UI)

### Step 1 — Approva la functional spec

1. Tab **Approvals** → revisiona la functional spec
2. Clicca **Approve** → status diventa `DONE` e appare il bottone **Genera Technical Design** nel Catalog

### Step 2 — Avvia la generazione tecnica

1. Tab **Catalog** → individua l'integrazione con status `DONE`
2. Clicca **Genera Technical Design**
3. Attendi il completamento (indicatore `⏳ Generating Technical...`)

### Step 3 — HITL Review del documento tecnico

1. Tab **Approvals** → cerca l'approval con `doc_type: technical`
2. Revisiona il documento tecnico generato
3. **Approve** per finalizzare → `technical_status: TECH_DONE`
4. oppure **Reject** con feedback → **Regenerate** per una nuova versione

### Step 4 — Consulta il Technical Spec

1. Tab **Catalog** → clicca **View Technical Spec**

---

## Via API (curl)

### Trigger technical generation

```bash
INTEGRATION_ID="INT-ABC123"

curl -s -X POST http://localhost:4003/api/v1/agent/trigger-technical/$INTEGRATION_ID \
  -H "Authorization: Bearer YOUR_API_KEY" \
  | python3 -m json.tool
```

**Risposta:**
```json
{"status": "success", "approval_id": "APP-XYZ123"}
```

### Approva il technical design

```bash
APPROVAL_ID="APP-XYZ123"

curl -s -X POST http://localhost:4003/api/v1/approvals/$APPROVAL_ID/approve \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"final_markdown": "# Integration Technical Design\n..."}' \
  | python3 -m json.tool
```

### Recupera il technical spec approvato

```bash
curl -s http://localhost:4003/api/v1/catalog/integrations/$INTEGRATION_ID/technical-spec \
  | python3 -m json.tool
```
```

**Step 2: Update architecture_specification.md** — add a "Two-Phase Document Generation" subsection in the Agent Pipeline section describing the technical_status state machine and new endpoints.

**Step 3: Update functional-guide.md** — add Step 6 after the functional approval step: "After functional approval, generate the technical design using the 'Genera Technical Design' button."

**Step 4: Commit**
```bash
git add HOW-TO/07-generate-technical-design.md docs/architecture_specification.md docs/functional-guide.md
git commit -m "docs: add HOW-TO-07, update arch spec + functional guide for technical doc generation"
```

---

## Task 12: Final verification

**Step 1: Run full test suite**
```bash
cd services/integration-agent && python -m pytest tests/ -v --tb=short
```
Expected: 314 + ~10 new = ~324+ tests pass, 0 fail.

**Step 2: E2E API smoke test (requires running docker compose)**
```bash
# Check technical_status appears in catalog endpoint
curl -s http://localhost:4003/api/v1/catalog/integrations | python3 -c "
import sys, json
data = json.load(sys.stdin)['data']
for i in data:
    print(i['id'], i.get('technical_status'))
"

# After approving a functional spec, verify TECH_PENDING:
curl -s http://localhost:4003/api/v1/catalog/integrations/INT-XXX | python3 -m json.tool | grep technical_status

# Trigger technical generation:
curl -s -X POST http://localhost:4003/api/v1/agent/trigger-technical/INT-XXX | python3 -m json.tool

# Verify technical approval in pending list:
curl -s http://localhost:4003/api/v1/approvals/pending | python3 -c "
import sys, json
for a in json.load(sys.stdin)['data']:
    print(a['id'], a['doc_type'], a['status'])
"
```

**Step 3: Final commit**
```bash
git add .
git commit -m "chore: finalize ADR-038 technical design generation implementation"
```
