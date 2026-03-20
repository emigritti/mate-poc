# Phase 3 — Generation Quality & Frontend State Management

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement R14 (output quality checker), R16 (feedback loop / regenerate), R2 (TanStack Query), R5 (custom hooks). R17 (KB structured prompt) is already done in Phase 2 via ContextAssembler — skip.

**Architecture:**
- R14 adds `assess_quality()` + `QualityReport` to `output_guard.py`, wired in `agent.py` after sanitize.
- R16 adds `reviewer_feedback` param to `build_prompt()`, extracts `generate_integration_doc()` to new `services/agent_service.py`, and adds `POST /api/v1/approvals/{id}/regenerate`.
- R2+R5 install `@tanstack/react-query`, add `QueryClientProvider` in `App.jsx`, and create pilot hooks for `ApprovalsPage` and `AgentWorkspacePage`.

**Tech Stack:** Python 3.13, FastAPI, dataclasses, pytest, React 18, @tanstack/react-query v5, Vite

---

## Notes Before Starting

- **R17 SKIP**: `ContextAssembler.assemble()` already outputs `## PAST APPROVED EXAMPLES` and `## BEST PRACTICE PATTERNS` in `rag_context`. No changes needed.
- **ADRs needed**: ADR-031 (quality checker), ADR-032 (feedback loop), ADR-033 (TanStack Query)
- **Test command**: `cd services/integration-agent && python -m pytest tests/ -v`
- **Frontend package dir**: `services/web-dashboard/`
- **Current test count**: 247 (will grow to ~267 after Phase 3)

---

## PART A — R14: Output Quality Checker

### Task 1: Write failing tests for assess_quality()

**Files:**
- Modify: `services/integration-agent/tests/test_output_guard.py`

**Step 1: Append tests to test_output_guard.py**

```python
# ── R14: Quality assessment tests ──────────────────────────────────────────────
from output_guard import assess_quality  # add to existing import at top of file


def _make_doc(sections: int = 7, na_per_section: bool = False) -> str:
    """Helper: build a minimal functional design doc."""
    lines = ["# Integration Functional Design\n"]
    for i in range(1, sections + 1):
        lines.append(f"## {i}. Section Title\n")
        lines.append("n/a\n" if na_per_section else "Meaningful content here with real information.\n")
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
```

**Step 2: Run tests — expect ImportError (assess_quality not yet defined)**

```bash
cd services/integration-agent && python -m pytest tests/test_output_guard.py::TestAssessQuality -v
```
Expected: 7 ERRORS — `ImportError: cannot import name 'assess_quality'`

**Step 3: Commit failing tests**

```bash
git add services/integration-agent/tests/test_output_guard.py
git commit -m "test(r14): add failing tests for assess_quality quality checker"
```

---

### Task 2: Implement QualityReport + assess_quality() in output_guard.py

**Files:**
- Modify: `services/integration-agent/output_guard.py`

**Step 1: Add dataclass import and constants at top of file (after `import bleach`)**

```python
from dataclasses import dataclass, field
import re

# ── Quality thresholds (R14) ────────────────────────────────────────────────────
_MIN_SECTION_COUNT: int = 5    # at least 5 ## headings expected
_MAX_NA_RATIO: float = 0.5     # max 50% sections can be n/a
_MIN_WORD_COUNT: int = 100     # minimum meaningful content
```

**Step 2: Add QualityReport dataclass and assess_quality() — append to file after sanitize_human_content()**

```python
# ── Quality Assessment (R14) ────────────────────────────────────────────────────

@dataclass
class QualityReport:
    """Non-destructive quality assessment of an LLM-generated document."""
    section_count: int
    na_ratio: float
    word_count: int
    quality_score: float
    passed: bool
    issues: list[str] = field(default_factory=list)


def assess_quality(content: str) -> QualityReport:
    """
    Assess LLM output quality without modifying content.

    Signals checked:
      1. section_count  — number of ## level-2 headings (min: _MIN_SECTION_COUNT)
      2. na_ratio       — fraction of sections containing only n/a (max: _MAX_NA_RATIO)
      3. word_count     — total word count (min: _MIN_WORD_COUNT)

    Call AFTER sanitize_llm_output() — content is already stripped of HTML.
    """
    issues: list[str] = []

    section_count = len(re.findall(r"^## ", content, re.MULTILINE))
    na_count = len(re.findall(r"\bn/a\b", content, re.IGNORECASE))
    na_ratio = (na_count / section_count) if section_count > 0 else 1.0
    word_count = len(content.split())

    if section_count < _MIN_SECTION_COUNT:
        issues.append(
            f"Too few sections: {section_count} (expected ≥ {_MIN_SECTION_COUNT})."
        )
    if na_ratio > _MAX_NA_RATIO:
        issues.append(
            f"High n/a ratio: {na_ratio:.0%} of sections lack real content."
        )
    if word_count < _MIN_WORD_COUNT:
        issues.append(
            f"Document too short: {word_count} words (expected ≥ {_MIN_WORD_COUNT})."
        )

    section_score = min(1.0, section_count / _MIN_SECTION_COUNT)
    na_score = max(0.0, 1.0 - na_ratio / _MAX_NA_RATIO) if _MAX_NA_RATIO > 0 else 0.0
    word_score = min(1.0, word_count / _MIN_WORD_COUNT)
    quality_score = round((section_score + na_score + word_score) / 3, 2)

    return QualityReport(
        section_count=section_count,
        na_ratio=round(na_ratio, 2),
        word_count=word_count,
        quality_score=quality_score,
        passed=len(issues) == 0,
        issues=issues,
    )
```

**Step 3: Run tests — expect all pass**

```bash
cd services/integration-agent && python -m pytest tests/test_output_guard.py -v
```
Expected: all passing (including the 12 existing tests)

**Step 4: Commit**

```bash
git add services/integration-agent/output_guard.py
git commit -m "feat(r14): add QualityReport + assess_quality() to output_guard"
```

---

### Task 3: Wire assess_quality into agent.py

**Files:**
- Modify: `services/integration-agent/routers/agent.py` line 21 (import) and after line 116

**Step 1: Update import in agent.py**

```python
# Change line 21 from:
from output_guard import LLMOutputValidationError, sanitize_llm_output
# To:
from output_guard import LLMOutputValidationError, QualityReport, sanitize_llm_output, assess_quality
```

**Step 2: Add quality check after line 118 (after `log_agent(f"[LLM] Spec generated and sanitized...")`)**

```python
            # R14: quality check — log warning if score is low
            quality = assess_quality(func_content)
            if not quality.passed:
                log_agent(
                    f"[QUALITY] Low quality score {quality.quality_score:.2f} for {entry.id} "
                    f"— {'; '.join(quality.issues)}"
                )
            else:
                log_agent(f"[QUALITY] Quality score {quality.quality_score:.2f} ✓ for {entry.id}")
```

**Step 3: Run full test suite — no regressions**

```bash
cd services/integration-agent && python -m pytest tests/ -v
```
Expected: 254 passed (247 + 7 new)

**Step 4: Commit**

```bash
git add services/integration-agent/routers/agent.py
git commit -m "feat(r14): wire assess_quality() into agent flow — log quality score per entry"
```

---

## PART B — R16: Feedback Loop / Regenerate

### Task 4: Write failing tests for build_prompt reviewer_feedback param

**Files:**
- Modify: `services/integration-agent/tests/test_prompt_builder.py`

**Step 1: Append 3 tests to TestBuildPrompt class**

```python
    def test_reviewer_feedback_injected_when_provided(self):
        prompt = build_prompt(
            "PLM", "PIM", "Sync data",
            reviewer_feedback="Missing data mapping table and error handling."
        )
        assert "Missing data mapping table" in prompt
        assert "PREVIOUS REJECTION FEEDBACK" in prompt

    def test_reviewer_feedback_absent_when_empty(self):
        prompt = build_prompt("PLM", "PIM", "Sync data")
        assert "PREVIOUS REJECTION FEEDBACK" not in prompt

    def test_reviewer_feedback_absent_when_whitespace_only(self):
        prompt = build_prompt("PLM", "PIM", "Sync data", reviewer_feedback="   \n  ")
        assert "PREVIOUS REJECTION FEEDBACK" not in prompt
```

**Step 2: Run — expect 3 FAIL (parameter not yet added)**

```bash
cd services/integration-agent && python -m pytest tests/test_prompt_builder.py -v -k "feedback"
```
Expected: 3 FAILED — `TypeError: build_prompt() got an unexpected keyword argument 'reviewer_feedback'`

**Step 3: Commit failing tests**

```bash
git add services/integration-agent/tests/test_prompt_builder.py
git commit -m "test(r16): add failing tests for reviewer_feedback in build_prompt"
```

---

### Task 5: Add reviewer_feedback param to build_prompt()

**Files:**
- Modify: `services/integration-agent/prompt_builder.py`

**Step 1: Update function signature — add `reviewer_feedback: str = ""`**

```python
def build_prompt(
    source_system: str,
    target_system: str,
    formatted_requirements: str,
    rag_context: str = "",
    kb_context: str = "",
    reviewer_feedback: str = "",          # R16: injected on regeneration
) -> str:
```

**Step 2: Add feedback_block and prepend to rag_block (before the existing `rag_block =` line)**

```python
    # R16: reviewer feedback block — injected before RAG context when regenerating
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
    # Prepend feedback before RAG examples so LLM sees it first
    combined_context = f"{feedback_block}{rag_block}" if feedback_block else rag_block
```

**Step 3: Update the replacement line to use combined_context**

```python
    result = result.replace("{rag_context}", combined_context)
```

**Step 4: Run tests — all pass**

```bash
cd services/integration-agent && python -m pytest tests/test_prompt_builder.py -v
```
Expected: all passing (13 original + 3 new = 16 tests)

**Step 5: Commit**

```bash
git add services/integration-agent/prompt_builder.py
git commit -m "feat(r16): add reviewer_feedback param to build_prompt() for regeneration flow"
```

---

### Task 6: Create services/agent_service.py with generate_integration_doc()

**Files:**
- Create: `services/integration-agent/services/agent_service.py`
- Modify: `services/integration-agent/routers/agent.py` (replace inline generation with helper call)

**Background:** The generation logic (steps 1-4 in `run_agentic_rag_flow`) needs to be callable from the regenerate endpoint too. Extract it to `services/agent_service.py` to avoid circular imports between routers.

**Step 1: Create services/agent_service.py**

```python
"""
Agent Service — core document generation logic.
ADR-026 (R15): extracted from main.py; shared by agent router and approvals router.

Exposes:
  generate_integration_doc() — full RAG + LLM pipeline for one catalog entry.
"""

import logging
from typing import Callable

from config import settings
from output_guard import sanitize_llm_output
from prompt_builder import build_prompt
from services.llm_service import generate_with_retry
from services.rag_service import ContextAssembler, fetch_url_kb_context
from services.retriever import ScoredChunk, hybrid_retriever
import state

logger = logging.getLogger(__name__)


async def generate_integration_doc(
    entry,                                      # CatalogEntry (avoid circular import)
    requirements: list,                         # list[Requirement]
    reviewer_feedback: str = "",
    log_fn: Callable[[str], None] | None = None,
) -> str:
    """
    Run the full RAG + LLM pipeline for a single catalog entry.

    Returns:
        Sanitized markdown string (from sanitize_llm_output).

    Raises:
        LLMOutputValidationError: if guard rejects the output.
        httpx.*: on LLM connectivity errors (caller handles these).
    """
    _log = log_fn or logger.info

    source = entry.source.get("system", "Unknown")
    target = entry.target.get("system", "Unknown")
    query_text = " ".join(r.description for r in requirements)
    category = entry.tags[0] if entry.tags else ""

    _log(f"[RAG] Hybrid retrieval for {entry.id} (tags={entry.tags})...")
    approved_chunks = await hybrid_retriever.retrieve(
        query_text, entry.tags, state.collection,
        source=source, target=target, category=category, log_fn=_log,
    )
    kb_scored_chunks = await hybrid_retriever.retrieve(
        query_text, entry.tags, state.kb_collection,
        source=source, target=target, category=category, log_fn=_log,
    )
    url_raw = await fetch_url_kb_context(entry.tags, state.kb_docs, log_fn=_log)
    url_chunks = ([ScoredChunk(text=url_raw, score=0.5, source_label="kb_url")]
                  if url_raw else [])

    assembler = ContextAssembler()
    rag_context = assembler.assemble(
        approved_chunks, kb_scored_chunks, url_chunks,
        max_chars=settings.ollama_rag_max_chars,
    )
    _log(f"[RAG] Assembled context: {len(rag_context)} chars")

    prompt = build_prompt(
        source_system=source,
        target_system=target,
        formatted_requirements=query_text,
        rag_context=rag_context,
        reviewer_feedback=reviewer_feedback,
    )
    _log(
        f"[LLM] Prompt ready for {entry.id} — {len(prompt)} chars"
        + (f" [with feedback: {len(reviewer_feedback)} chars]" if reviewer_feedback else "")
    )

    raw = await generate_with_retry(prompt, log_fn=_log)
    return sanitize_llm_output(raw)
```

**Step 2: Refactor routers/agent.py to use generate_integration_doc()**

Import:
```python
from services.agent_service import generate_integration_doc
```

Replace lines 61–120 (the inline RAG + LLM block) with:
```python
        # 1–4. RAG retrieval + LLM generation (extracted to agent_service.py — R16 reuse)
        try:
            func_content = await generate_integration_doc(
                entry=entry,
                requirements=reqs,
                reviewer_feedback="",
                log_fn=log_agent,
            )
            log_agent(
                f"[LLM] Spec generated and sanitized for {entry.id} — "
                f"{len(func_content)} chars."
            )
            # R14: quality check
            quality = assess_quality(func_content)
            if not quality.passed:
                log_agent(
                    f"[QUALITY] Low quality score {quality.quality_score:.2f} for {entry.id} "
                    f"— {'; '.join(quality.issues)}"
                )
            else:
                log_agent(f"[QUALITY] Quality score {quality.quality_score:.2f} ✓ for {entry.id}")
        except LLMOutputValidationError as exc:
            log_agent(f"[GUARD] Output rejected for {entry.id}: {exc}")
            func_content = "[LLM_OUTPUT_REJECTED: structural guard failed -- see agent logs]"
        except Exception as exc:
            # ... (keep existing exception handling as-is)
```

**Step 3: Run full test suite — no regressions**

```bash
cd services/integration-agent && python -m pytest tests/ -v
```
Expected: all passing

**Step 4: Commit**

```bash
git add services/integration-agent/services/agent_service.py services/integration-agent/routers/agent.py
git commit -m "refactor(r16): extract generate_integration_doc() to services/agent_service.py"
```

---

### Task 7: Write failing tests for regenerate endpoint

**Files:**
- Create: `services/integration-agent/tests/test_approvals_regenerate.py`

**Step 1: Create test file**

```python
"""
Unit tests — POST /api/v1/approvals/{id}/regenerate
R16: Feedback loop — regenerate document with reviewer feedback injected into prompt.
"""

import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

import state
from main import app
from schemas import Approval, CatalogEntry

client = TestClient(app)


def _inject_rejected(app_id: str, integration_id: str, feedback: str) -> None:
    """Put a REJECTED approval and its catalog entry into state."""
    entry = CatalogEntry(
        id=integration_id,
        name="PLM→PIM",
        source={"system": "PLM"},
        target={"system": "PIM"},
        requirements=[],
        tags=["Data Sync"],
        status="DONE",
    )
    state.catalog[integration_id] = entry

    approval = Approval(
        id=app_id,
        integration_id=integration_id,
        doc_type="functional",
        content="[REJECTED_CONTENT]",
        status="REJECTED",
        generated_at="2026-03-20T00:00:00+00:00",
        feedback=feedback,
    )
    state.approvals[app_id] = approval


def _mock_generate():
    """Return a valid-looking functional design doc."""
    return (
        "# Integration Functional Design\n\n"
        "## 1. Overview\n\nReal content here.\n\n"
        "## 2. Scope\n\nFull scope description.\n\n"
        "## 3. Actors\n\nPLM and PIM systems.\n\n"
        "## 4. Process\n\nThe process works as follows.\n\n"
        "## 5. Data\n\nFields mapped correctly.\n\n"
        "## 6. Non-Functional\n\nPerformance criteria.\n"
    )


class TestRegenerateEndpoint:
    def setup_method(self):
        state.approvals.clear()
        state.catalog.clear()

    def test_regenerate_404_unknown(self):
        res = client.post("/api/v1/approvals/UNKNOWN/regenerate")
        assert res.status_code == 404

    def test_regenerate_409_if_pending(self):
        state.approvals["APP-P"] = Approval(
            id="APP-P", integration_id="X", doc_type="functional",
            content="...", status="PENDING", generated_at="2026-01-01T00:00:00+00:00",
        )
        res = client.post("/api/v1/approvals/APP-P/regenerate")
        assert res.status_code == 409

    def test_regenerate_409_if_already_approved(self):
        state.approvals["APP-A"] = Approval(
            id="APP-A", integration_id="X", doc_type="functional",
            content="...", status="APPROVED", generated_at="2026-01-01T00:00:00+00:00",
        )
        res = client.post("/api/v1/approvals/APP-A/regenerate")
        assert res.status_code == 409

    def test_regenerate_409_if_no_feedback(self):
        _inject_rejected("APP-R1", "INT-001", feedback="")
        state.approvals["APP-R1"].feedback = None
        res = client.post("/api/v1/approvals/APP-R1/regenerate")
        assert res.status_code == 409

    def test_regenerate_creates_new_pending_approval(self):
        _inject_rejected("APP-R2", "INT-002", feedback="Missing error section.")
        with patch(
            "routers.approvals.generate_integration_doc",
            new_callable=AsyncMock,
            return_value=_mock_generate(),
        ):
            res = client.post("/api/v1/approvals/APP-R2/regenerate")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        new_id = data["data"]["new_approval_id"]
        assert new_id in state.approvals
        assert state.approvals[new_id].status == "PENDING"

    def test_regenerate_passes_feedback_to_generator(self):
        _inject_rejected("APP-R3", "INT-003", feedback="Add data mapping table.")
        with patch(
            "routers.approvals.generate_integration_doc",
            new_callable=AsyncMock,
            return_value=_mock_generate(),
        ) as mock_gen:
            client.post("/api/v1/approvals/APP-R3/regenerate")
        call_kwargs = mock_gen.call_args.kwargs
        assert "Add data mapping table." in call_kwargs.get("reviewer_feedback", "")
```

**Step 2: Run — expect import/attribute errors**

```bash
cd services/integration-agent && python -m pytest tests/test_approvals_regenerate.py -v
```
Expected: ERRORS — endpoint doesn't exist yet

**Step 3: Commit failing tests**

```bash
git add services/integration-agent/tests/test_approvals_regenerate.py
git commit -m "test(r16): add failing tests for regenerate endpoint"
```

---

### Task 8: Implement POST /api/v1/approvals/{id}/regenerate

**Files:**
- Modify: `services/integration-agent/routers/approvals.py`

**Step 1: Add import at top of approvals.py**

```python
import uuid
from services.agent_service import generate_integration_doc
```

**Step 2: Add regenerate endpoint (append after reject_doc)**

```python
@router.post("/approvals/{id}/regenerate")
async def regenerate_doc(
    id: str,
    _token: str = Depends(require_token),
) -> dict:
    """
    Regenerate a REJECTED document with reviewer feedback injected into the prompt.

    R16: Creates a new PENDING Approval for the same integration, with the rejection
    feedback from the previous attempt prepended to the prompt context.
    """
    if id not in state.approvals:
        raise HTTPException(status_code=404, detail="Approval not found.")

    app_entry = state.approvals[id]
    if app_entry.status != "REJECTED":
        raise HTTPException(
            status_code=409,
            detail=f"Only REJECTED approvals can be regenerated (current: {app_entry.status}).",
        )
    if not app_entry.feedback:
        raise HTTPException(
            status_code=409,
            detail="Cannot regenerate without rejection feedback.",
        )

    # Look up catalog entry and requirements
    entry = state.catalog.get(app_entry.integration_id)
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail=f"Catalog entry '{app_entry.integration_id}' not found — cannot regenerate.",
        )
    requirements = [r for r in state.parsed_requirements if r.req_id in entry.requirements]

    # Generate new document with feedback injected
    from output_guard import LLMOutputValidationError
    import httpx as _httpx

    try:
        new_content = await generate_integration_doc(
            entry=entry,
            requirements=requirements,
            reviewer_feedback=app_entry.feedback,
            log_fn=logger.info,
        )
    except LLMOutputValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Regenerated output failed structural guard: {exc}",
        )
    except (_httpx.TimeoutException, _httpx.ConnectError) as exc:
        raise HTTPException(
            status_code=503,
            detail=f"LLM unavailable during regeneration: {exc}",
        )

    # Create new PENDING approval
    new_id = f"APP-{uuid.uuid4().hex[:6].upper()}"
    from schemas import Approval as _Approval
    new_approval = _Approval(
        id=new_id,
        integration_id=app_entry.integration_id,
        doc_type=app_entry.doc_type,
        content=new_content,
        status="PENDING",
        generated_at=_now_iso(),
    )
    state.approvals[new_id] = new_approval
    if db.approvals_col is not None:
        await db.approvals_col.replace_one(
            {"id": new_id}, new_approval.model_dump(), upsert=True
        )

    logger.info(
        "[REGEN] New approval %s created from rejected %s (feedback: %d chars)",
        new_id, id, len(app_entry.feedback),
    )
    return {
        "status": "success",
        "message": f"Regenerated from feedback. New approval {new_id} is PENDING.",
        "data": {"new_approval_id": new_id, "previous_approval_id": id},
    }
```

**Step 3: Run tests — expect all pass**

```bash
cd services/integration-agent && python -m pytest tests/test_approvals_regenerate.py -v
```
Expected: 6 PASSED

**Step 4: Full suite**

```bash
cd services/integration-agent && python -m pytest tests/ -v
```
Expected: 260 passed (254 + 6 new)

**Step 5: Commit**

```bash
git add services/integration-agent/routers/approvals.py
git commit -m "feat(r16): add POST /api/v1/approvals/{id}/regenerate endpoint"
```

---

### Task 9: Frontend — API method + Rejected approvals list + Regenerate button

**Files:**
- Modify: `services/web-dashboard/src/api.js`
- Modify: `services/web-dashboard/src/components/pages/ApprovalsPage.jsx`

**Step 1: Add regenerate API method in api.js (in `approvals` object)**

```javascript
regenerate: (id) =>
  fetch(`${AGENT}/api/v1/approvals/${id}/regenerate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  }),
```

**Step 2: In ApprovalsPage.jsx — add state for rejected list and regenerate handler**

Add after existing `const [successMsg, ...` state declarations:
```jsx
const [rejected, setRejected] = useState([]);   // rejected approvals for regeneration
const [regenerating, setRegenerating] = useState(null);  // id being regenerated
```

**Step 3: Update loadApprovals to also load rejected**

```jsx
const loadApprovals = async () => {
  setLoading(true);
  try {
    const res = await API.approvals.pending();
    const data = await res.json();
    setApprovals(data.data || []);
    // Also load rejected (from same endpoint filtered client-side, or add GET /rejected)
    // For now, keep rejected list populated from handleReject callback
  } catch {
    setError('Failed to load pending approvals');
  } finally {
    setLoading(false);
  }
};
```

**Step 4: Update handleReject to add to rejected list**

```jsx
setRejected(prev => [...prev, { ...approvals.find(a => a.id === selectedId), feedback }]);
```

**Step 5: Add handleRegenerate handler**

```jsx
const handleRegenerate = async (approvalId) => {
  setRegenerating(approvalId);
  setError(null);
  try {
    const res = await API.approvals.regenerate(approvalId);
    if (!res.ok) {
      const d = await res.json().catch(() => ({}));
      throw new Error(d.detail || `Regeneration failed (${res.status})`);
    }
    const data = await res.json();
    setSuccessMsg(`Regenerated → new approval ${data.data?.new_approval_id} is PENDING.`);
    setRejected(prev => prev.filter(a => a.id !== approvalId));
    await loadApprovals();  // refresh pending list
  } catch (e) {
    setError(e.message || 'Regeneration failed');
  } finally {
    setRegenerating(null);
  }
};
```

**Step 6: Add rejected list panel below the pending list in JSX**

```jsx
{/* Rejected — available for regeneration */}
{rejected.length > 0 && (
  <div className="mt-4 border-t border-slate-200 pt-4">
    <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">
      Rejected ({rejected.length})
    </p>
    {rejected.map(a => (
      <div key={a.id} className="p-2 rounded-lg bg-rose-50 border border-rose-100 mb-2 text-xs">
        <p className="font-medium text-slate-700 truncate">{a.name || a.id}</p>
        <button
          onClick={() => handleRegenerate(a.id)}
          disabled={regenerating === a.id}
          className="mt-1 w-full py-1 bg-rose-600 text-white rounded text-xs font-medium hover:bg-rose-700 disabled:opacity-50"
        >
          {regenerating === a.id ? 'Regenerating…' : 'Regenerate with Feedback'}
        </button>
      </div>
    ))}
  </div>
)}
```

**Step 7: Commit**

```bash
git add services/web-dashboard/src/api.js services/web-dashboard/src/components/pages/ApprovalsPage.jsx
git commit -m "feat(r16): add regenerate API method and Rejected panel in ApprovalsPage"
```

---

## PART C — R2+R5: TanStack Query + Custom Hooks (Pilot)

### Task 10: Install @tanstack/react-query and setup QueryClientProvider

**Files:**
- Modify: `services/web-dashboard/package.json` (via npm)
- Modify: `services/web-dashboard/src/App.jsx`

**Step 1: Install package**

```bash
cd services/web-dashboard && npm install @tanstack/react-query
```

**Step 2: Add QueryClient setup in App.jsx — add imports at top**

```jsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,          // 30s before refetch
      retry: 1,
      refetchOnWindowFocus: true,
    },
  },
});
```

**Step 3: Wrap App return with QueryClientProvider**

```jsx
return (
  <QueryClientProvider client={queryClient}>
    {/* ... existing JSX ... */}
  </QueryClientProvider>
);
```

**Step 4: Commit**

```bash
git add services/web-dashboard/package.json services/web-dashboard/package-lock.json services/web-dashboard/src/App.jsx
git commit -m "feat(r2): install @tanstack/react-query and add QueryClientProvider"
```

---

### Task 11: Create hooks/useApprovals.js

**Files:**
- Create: `services/web-dashboard/src/hooks/useApprovals.js`

**Step 1: Create hooks directory and useApprovals.js**

```javascript
/**
 * useApprovals — TanStack Query hook for HITL approval state.
 * R2: Replaces manual useState + loadApprovals() in ApprovalsPage.
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import API from '../api';

const QUERY_KEY = ['approvals', 'pending'];

async function fetchPending() {
  const res = await API.approvals.pending();
  if (!res.ok) throw new Error(`Failed to load approvals (${res.status})`);
  const data = await res.json();
  return data.data || [];
}

export function useApprovals() {
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: QUERY_KEY,
    queryFn: fetchPending,
    refetchInterval: 15_000,   // poll every 15s (matches current service health check)
  });

  const approveMutation = useMutation({
    mutationFn: ({ id, content }) => API.approvals.approve(id, content),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: QUERY_KEY }),
  });

  const rejectMutation = useMutation({
    mutationFn: ({ id, feedback }) => API.approvals.reject(id, feedback),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: QUERY_KEY }),
  });

  const regenerateMutation = useMutation({
    mutationFn: ({ id }) => API.approvals.regenerate(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: QUERY_KEY }),
  });

  return {
    approvals: query.data ?? [],
    isLoading: query.isLoading,
    error: query.error?.message ?? null,
    approve: approveMutation.mutate,
    reject: rejectMutation.mutate,
    regenerate: regenerateMutation.mutate,
    isApproving: approveMutation.isPending,
    isRejecting: rejectMutation.isPending,
    isRegenerating: regenerateMutation.isPending,
    approveError: approveMutation.error?.message ?? null,
    rejectError: rejectMutation.error?.message ?? null,
  };
}
```

**Step 2: Commit**

```bash
git add services/web-dashboard/src/hooks/useApprovals.js
git commit -m "feat(r5): add useApprovals custom hook with TanStack Query"
```

---

### Task 12: Refactor ApprovalsPage.jsx to use useApprovals hook

**Files:**
- Modify: `services/web-dashboard/src/components/pages/ApprovalsPage.jsx`

**Step 1: Add import at top**

```jsx
import { useApprovals } from '../../hooks/useApprovals';
```

**Step 2: Replace all useState declarations and loadApprovals with hook**

Remove:
- `const [approvals, setApprovals]`
- `const [loading, setLoading]`
- `const [submitting, setSubmitting]`
- `const [error, setError]` (for load errors)
- `const loadApprovals = async () => ...`
- `useEffect(() => { loadApprovals(); }, [])` (hook handles this)

Replace with:
```jsx
const {
  approvals,
  isLoading,
  error: loadError,
  approve,
  reject,
  regenerate,
  isApproving,
  isRejecting,
  isRegenerating,
  approveError,
  rejectError,
} = useApprovals();
```

**Step 3: Update handleApprove to use mutation**

```jsx
const handleApprove = () => {
  approve(
    { id: selectedId, content },
    {
      onSuccess: () => {
        setSuccessMsg('Document staged. Use the Documents page to promote to Knowledge Base.');
        setSelectedId(null);
      },
      onError: (e) => setError(e.message || 'Approval failed'),
    }
  );
};
```

**Step 4: Update handleReject to use mutation**

```jsx
const handleReject = () => {
  if (!feedback.trim()) {
    setError('Please provide rejection feedback before submitting');
    return;
  }
  reject(
    { id: selectedId, feedback },
    {
      onSuccess: () => {
        setSuccessMsg('Document rejected — use Regenerate with Feedback to retry.');
        setRejected(prev => [...prev, { ...approvals.find(a => a.id === selectedId), feedback }]);
        setSelectedId(null);
        setRejectMode(false);
        setFeedback('');
      },
      onError: (e) => setError(e.message || 'Rejection failed'),
    }
  );
};
```

**Step 5: Update refresh button to use query.refetch**

```jsx
// The hook's refetchInterval handles polling; expose manual refresh if needed:
import { useQueryClient } from '@tanstack/react-query';
const queryClient = useQueryClient();
const handleRefresh = () => queryClient.invalidateQueries({ queryKey: ['approvals', 'pending'] });
```

**Step 6: Verify the page still renders correctly — run dev server if available**

```bash
cd services/web-dashboard && npm run dev
```

**Step 7: Commit**

```bash
git add services/web-dashboard/src/components/pages/ApprovalsPage.jsx
git commit -m "refactor(r5): refactor ApprovalsPage to use useApprovals hook"
```

---

### Task 13: Create hooks/useAgentLogs.js + refactor AgentWorkspacePage

**Files:**
- Create: `services/web-dashboard/src/hooks/useAgentLogs.js`
- Modify: `services/web-dashboard/src/components/pages/AgentWorkspacePage.jsx`

**Step 1: Create useAgentLogs.js**

```javascript
/**
 * useAgentLogs — TanStack Query hook for agent log polling.
 * R2: Replaces manual setInterval + useState in AgentWorkspacePage.
 * Polls every 3s while agent is running; slows to 15s when idle.
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import API from '../api';

const LOGS_KEY = ['agent', 'logs'];

async function fetchLogs() {
  const res = await API.agent.logs();
  if (!res.ok) throw new Error(`Failed to fetch logs (${res.status})`);
  const data = await res.json();
  return data.data || { logs: [], running: false };
}

export function useAgentLogs() {
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: LOGS_KEY,
    queryFn: fetchLogs,
    refetchInterval: (data) => {
      // Poll fast while running, slow when idle
      return data?.running ? 3_000 : 15_000;
    },
  });

  const triggerMutation = useMutation({
    mutationFn: () => API.agent.trigger(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: LOGS_KEY }),
  });

  const cancelMutation = useMutation({
    mutationFn: () => API.agent.cancel(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: LOGS_KEY }),
  });

  return {
    logs: query.data?.logs ?? [],
    isRunning: query.data?.running ?? false,
    isLoading: query.isLoading,
    error: query.error?.message ?? null,
    trigger: triggerMutation.mutate,
    cancel: cancelMutation.mutate,
    isTriggering: triggerMutation.isPending,
    isCancelling: cancelMutation.isPending,
    triggerError: triggerMutation.error?.message ?? null,
  };
}
```

**Step 2: Update AgentWorkspacePage.jsx — add import**

```jsx
import { useAgentLogs } from '../../hooks/useAgentLogs';
```

**Step 3: Replace polling useState/useEffect block with hook**

Remove the manual `useEffect` that calls `setInterval` for log polling and replace:
```jsx
const {
  logs,
  isRunning,
  isLoading,
  error,
  trigger,
  cancel,
  isTriggering,
  isCancelling,
  triggerError,
} = useAgentLogs();
```

**Step 4: Update trigger/cancel button handlers to use mutations**

```jsx
const handleTrigger = () => trigger(undefined, {
  onError: (e) => setLocalError(e.message || 'Trigger failed'),
});

const handleCancel = () => cancel(undefined, {
  onError: (e) => setLocalError(e.message || 'Cancel failed'),
});
```

**Step 5: Commit**

```bash
git add services/web-dashboard/src/hooks/useAgentLogs.js services/web-dashboard/src/components/pages/AgentWorkspacePage.jsx
git commit -m "feat(r5): add useAgentLogs hook and refactor AgentWorkspacePage"
```

---

## PART D — ADRs and Documentation

### Task 14: Create ADR-031 (Quality Checker), ADR-032 (Feedback Loop), ADR-033 (TanStack Query)

**Files:**
- Create: `docs/adr/ADR-031-output-quality-checker.md`
- Create: `docs/adr/ADR-032-feedback-loop-regenerate.md`
- Create: `docs/adr/ADR-033-tanstack-query-frontend.md`
- Modify: `services/integration-agent/routers/admin.py` (add to DOCS_MANIFEST)

Use `docs/adr/ADR-000-template.md` as base for each.

**ADR-031 summary:**
- Context: Output guard only validates structure; completeness not checked
- Decision: `assess_quality()` in output_guard.py with 3 signals (section_count, na_ratio, word_count)
- Alternatives considered: LLM-as-judge (too slow/costly), regex-per-section (too brittle)
- Consequence: warning only — no automatic retry (keeps latency predictable)

**ADR-032 summary:**
- Context: Rejected documents are dead-ends; reviewer feedback is unused
- Decision: `POST /api/v1/approvals/{id}/regenerate` endpoint + feedback injected via `build_prompt(reviewer_feedback=...)`
- Alternatives: auto-retry on reject (loses HITL control), stored-procedure replay (too complex)
- Consequence: Human controls retry timing; closes the feedback loop in the HITL flow

**ADR-033 summary:**
- Context: All pages do independent fetch + useState; no caching, no polling management
- Decision: TanStack Query v5 for async state management; pilot on ApprovalsPage + AgentWorkspacePage
- Alternatives: Zustand (global state, overkill for server-state), SWR (less features), Redux Toolkit Query (too heavy)
- Consequence: Automatic refetch, deduplication, stale-while-revalidate; future pages use same pattern

**After creating ADRs, add to DOCS_MANIFEST in admin.py:**

```python
{"path": "adr/ADR-031-output-quality-checker.md", "name": "ADR-031 Output Quality Checker", "category": "ADR", "description": "Quality assessment gate after LLM generation."},
{"path": "adr/ADR-032-feedback-loop-regenerate.md", "name": "ADR-032 Feedback Loop Regenerate", "category": "ADR", "description": "HITL feedback loop: regenerate rejected documents."},
{"path": "adr/ADR-033-tanstack-query-frontend.md", "name": "ADR-033 TanStack Query Frontend", "category": "ADR", "description": "React Query for server-state management."},
```

**Commit:**

```bash
git add docs/adr/ADR-031-*.md docs/adr/ADR-032-*.md docs/adr/ADR-033-*.md services/integration-agent/routers/admin.py
git commit -m "docs(adr): add ADR-031 quality checker, ADR-032 feedback loop, ADR-033 TanStack Query"
```

---

### Task 15: Update architecture_specification.md and functional-guide.md

**Files:**
- Modify: `docs/architecture_specification.md`
- Modify: `docs/functional-guide.md`

**architecture_specification.md changes:**
1. §7 workflow: update agent flow row — add quality check step after LLM generation
2. §7 (new subsection): Regenerate Flow — sequence diagram for HITL feedback loop
3. §9 in-memory state: no new state (rejected approvals already in `state.approvals`)
4. §18 ADR index: add ADR-031, ADR-032, ADR-033
5. Version bump: v3.0.0 → v3.1.0

**functional-guide.md changes:**
1. §7 (generation section): add quality checker mention (3 signals, warning-only gate)
2. New §9.2 (or §9.3): Feedback Loop — explain the regenerate endpoint flow
3. §11: update test count 247 → ~267
4. §7.5 (backend table): add `services/agent_service.py` row

**Commit:**

```bash
git add docs/architecture_specification.md docs/functional-guide.md
git commit -m "docs: update architecture spec and functional guide for Phase 3"
```

---

## Critical Files

| File | Role | Change |
|------|------|--------|
| `services/integration-agent/output_guard.py` | Quality gate | Add `QualityReport` + `assess_quality()` |
| `services/integration-agent/prompt_builder.py` | Prompt building | Add `reviewer_feedback` param |
| `services/integration-agent/services/agent_service.py` | NEW — generation helper | Extract `generate_integration_doc()` |
| `services/integration-agent/routers/agent.py` | Agent flow | Use `generate_integration_doc()` |
| `services/integration-agent/routers/approvals.py` | HITL endpoints | Add `regenerate_doc()` endpoint |
| `services/web-dashboard/src/api.js` | API client | Add `approvals.regenerate()` |
| `services/web-dashboard/src/hooks/useApprovals.js` | NEW — React hook | Approval state via TanStack Query |
| `services/web-dashboard/src/hooks/useAgentLogs.js` | NEW — React hook | Agent log polling via TanStack Query |
| `services/web-dashboard/src/App.jsx` | App root | Add QueryClientProvider |

---

## Verification

**Backend tests:**

```bash
cd services/integration-agent && python -m pytest tests/ -v
```
Expected: ~267 passed (247 + 7 quality checker + 3 prompt feedback + 6 regenerate + ~4 agent_service)

**Frontend check:**

```bash
cd services/web-dashboard && npm run build
```
Expected: build succeeds with no type errors

**Manual flow for R16 (once docker-compose is running):**
1. Upload requirements CSV → trigger agent → get PENDING approval
2. Reject with feedback "Add data mapping table"
3. Click "Regenerate with Feedback" button in ApprovalsPage
4. Verify new PENDING approval appears in the list with improved content
