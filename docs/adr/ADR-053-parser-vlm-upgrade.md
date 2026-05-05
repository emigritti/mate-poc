# ADR-053 — Parser Upgrade: Docling 2.5 + Granite-Vision VLM (ADR-X1)

**Status:** Accepted
**Date:** 2026-05-05
**Authors:** Emiliano Gritti (AI-assisted, Claude Code)
**Supersedes:** partial enhancement to ADR-031 (Docling + LLaVA vision parser)

---

## Context

ADR-031 introduced `parse_with_docling()` with `llava:7b` as the default VLM for figure captioning. Two weaknesses were identified during the RAG pipeline modernization review:

1. **`llava:7b` is a generalist VLM** (~14 GB RAM, 25–40 s/figure on EC2 CPU). It is not tuned for enterprise documents (tables, charts, diagrams) and produces low-quality captions for structured content.
2. **Docling 2.5** introduced a native VLM captioning pipeline that integrates directly with the parsing stage, removing the current two-pass approach (Docling text + separate vision_service call).

The goal of this ADR is to upgrade the VLM to `granite3.2-vision:2b` as the primary model and restructure the fallback chain, while preserving `llava:7b` as a runtime-configurable fallback.

---

## Decision

### VLM selection

| Model | Params | RAM CPU | Latency CPU/fig | Tuning |
|---|---|---|---|---|
| `llava:7b` (previous default) | 7B | ~14 GB | 25–40 s | Generalist |
| **`granite3.2-vision:2b`** ⭐ | 2B | ~5 GB | 8–15 s | Enterprise docs, Apache-2.0 |
| `llava:13b` | 13B | ~26 GB | 50–80 s | Generalist, out of scope |

`granite3.2-vision:2b` is chosen as primary: 3–5× faster, significantly stronger on tables and charts, half the RAM footprint, IBM Apache-2.0 licence.

### Fallback chain

```
Primary:   VLM_MODEL_NAME          (default: granite3.2-vision:2b)
           ↓ on error or VLM_FORCE_FALLBACK=true
Fallback:  VLM_FALLBACK_MODEL_NAME  (default: llava:7b)
           ↓ on both failures
Sentinel:  "[FIGURE: no caption available]"
```

### New config vars

| Env var | Default | Effect |
|---|---|---|
| `VLM_MODEL_NAME` | `granite3.2-vision:2b` | Primary VLM |
| `VLM_FALLBACK_MODEL_NAME` | `llava:7b` | Fallback VLM |
| `VLM_FORCE_FALLBACK` | `false` | Skip primary, use fallback only |
| `VISION_CAPTIONING_ENABLED` | `true` | Master switch |

### Files changed

| File | Change |
|---|---|
| `services/integration-agent/services/vision_service.py` | Add primary/fallback dispatch; new `caption_figure(image_bytes, model_name)` signature |
| `services/integration-agent/document_parser.py` | Pass `settings.vlm_model_name` to `caption_figure`; catch model error → retry with fallback |
| `services/integration-agent/config.py` | Add 4 new vars above |
| `docker-compose.yml` | `ollama-init` pulls `granite3.2-vision:2b` |

---

## Consequences

### Positive
- 3–5× faster figure captioning on CPU-only EC2 instance
- Significantly better quality on enterprise document tables and charts
- Half the RAM footprint frees memory for cross-encoder (ADR-055)
- Instant rollback via `VLM_FORCE_FALLBACK=true`

### Negative / Risks

| Risk | Severity | Mitigation |
|---|---|---|
| `granite3.2-vision:2b` not available on Ollama for dev (Mac/Windows) | Medium | 30-min availability spike before merge; fallback to `llava:7b` via env var |
| KB re-ingestion required (figure captions change) | Low | Accepted; documented in `HOW-TO/how-to-rag-pipeline-modernized.md` |
| Granite-Vision caption quality regression on natural-language images | Low | Eval harness caption-quality delta run (Claude judge opt-in) |

---

## Validation plan

- Unit: `test_vision_service.py::test_falls_back_to_llava_on_granite_error` — mock primary failure, assert fallback invoked
- Unit: `test_document_parser.py::test_parse_with_docling_passes_vlm_model_name` — verify correct model name propagated
- Eval: caption-quality delta on 5 figure-heavy PDFs using Claude judge (`LLM_JUDGE_ENABLED=true`)
- Full suite regression: `pytest tests/ -q`

---

## Rollback

```bash
# Instant runtime rollback — no redeploy needed
export VLM_FORCE_FALLBACK=true

# Or revert to llava permanently
export VLM_MODEL_NAME=llava:7b
```

Git tag `pre-adr-x1-merge` on `main` before merge.

---

## Compliance (CLAUDE.md)

- Figure bytes are sent to **local Ollama only** — no external API call → §1 data boundary satisfied
- VLM output is treated as untrusted input (prompt injection surface) — captions are stored as-is in chunk metadata, not executed
- Aligns with §11 (AI/Agentic Security): model allow-list enforced via config, no arbitrary model injection
