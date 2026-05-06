# Different LLMs and Their Usage

> **Purpose:** Explain which AI models are used in the Functional Integration Mate PoC, where each one is called, why it was chosen for that specific role, and what alternatives exist with their technical constraints.
> **Audience:** Developers, architects, DevOps engineers managing the EC2 deployment.
> **Last updated:** 2026-05-06

---

## 1. Overview

The system uses **five distinct Ollama models** (plus optional cloud API models), each assigned to a specific role based on a balance of quality, speed, and memory footprint. No single model fits all tasks: a 14B-parameter LLM generating a 2,000-token document is overkill for a 200-token tag suggestion, and a tiny embedding model cannot replace a generative LLM.

```
┌─────────────────────────────────────────────────────────────────┐
│  UPLOAD KB DOCUMENT                                             │
│    └─ Docling parser                                            │
│         ├─ figures found ──► granite3.2-vision:2b  (caption)   │
│         ├─ chunks ──────────► llama3.1:8b / claude-haiku       │
│         │                     (situating annotation)            │
│         ├─ chunks ──────────► nomic-embed-text:v1.5            │
│         │                     (embedding → ChromaDB)            │
│         └─ sections ────────► qwen2.5:14b  (RAPTOR summary)    │
│                                qwen3:8b    (tag suggestion)     │
│                                                                 │
│  TRIGGER DOCUMENT GENERATION                                    │
│    ├─ qwen3:8b ──────────────► query expansion (2 variants)    │
│    ├─ nomic-embed-text:v1.5 ─► ChromaDB retrieval              │
│    ├─ qwen2.5:14b ───────────► document generation (default)   │
│    └─ gemma4:26b ────────────► document generation (premium)   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. Model Reference Table

| Role | Default Model | Config Var | RAM (Q4_K_M) | Speed (CPU) | GPU Needed? |
|---|---|---|---|---|---|
| Vector embeddings (RAG) | `nomic-embed-text:v1.5` | `EMBEDDER_MODEL_NAME` | ~274 MB | very fast | No |
| Tag suggestion / query expansion | `qwen3:8b` | `TAG_MODEL` | ~5 GB | ~8 tok/s | No |
| Document generation (default) | `qwen2.5:14b` | `OLLAMA_MODEL` | ~9 GB | ~4 tok/s | No |
| Document generation (premium) | `gemma4:26b` | `PREMIUM_MODEL` | ~17 GB | ~1.5 tok/s | Recommended |
| Vision / figure captioning | `granite3.2-vision:2b` | `VLM_MODEL_NAME` | ~2.4 GB | 8–15 s/fig | No |
| Contextual retrieval (offline) | `llama3.1:8b` | `CONTEXTUAL_MODEL_OLLAMA` | ~5 GB | ~6 tok/s | No |

---

## 3. Model Details

### 3.1 `nomic-embed-text:v1.5` — Vector Embedder

**Role:** Converts text chunks into dense vectors stored in ChromaDB for semantic retrieval.

**Where it is called:**
- `services/integration-agent/main.py` → ChromaDB collection initialization at startup
- `services/ingestion-platform/config.py` → same model for ingestion pipeline chunks

**Why this model:**
- Specifically designed for retrieval tasks with two separate task prefixes:
  - `search_document:` — used when *ingesting* documents into the KB
  - `search_query:` — used when *searching* at generation time
- The prefix distinction improves retrieval precision significantly compared to a single-mode embedder
- 274 MB footprint: always resident in memory, negligible cost
- Must remain consistent between integration-agent and ingestion-platform — if you change it, you must re-embed the entire ChromaDB collection from scratch

**Technical constraints:**
- Requires Ollama running with the model pulled: `ollama pull nomic-embed-text:v1.5`
- Cannot swap to a different embedding model without wiping ChromaDB and re-ingesting all documents (vectors are not compatible across models)

**Alternatives:**
| Model | RAM | Notes |
|---|---|---|
| `all-MiniLM-L6-v2` | ~90 MB | ChromaDB built-in default; no task prefixes; lower quality |
| `mxbai-embed-large:v1` | ~670 MB | Higher quality embeddings; better multilingual support |
| `nomic-embed-text:v1.5` (current) | ~274 MB | Best balance for this use case |
| `text-embedding-3-small` (OpenAI) | API only | Best quality; requires API key and sends data externally |

---

### 3.2 `qwen3:8b` — Fast Utility Model (TAG_MODEL)

**Role:** Handles short, frequent LLM calls that do not require the full power of the 14B document model.

**Where it is called:**
- `routers/kb.py` → auto-tag suggestion when a document is uploaded to the KB
- `routers/catalog.py` → on-demand tag suggestion for catalog entries
- `routers/wiki.py` → wiki entity relation extraction (when `WIKI_LLM_RELATION_EXTRACTION=true`)
- `services/retriever.py` → LLM-based query expansion: generates 2 alternative query phrasings to improve RAG recall

**Why this model:**
- Fast responses (200 token max, 60s timeout): tag suggestion and query expansion happen synchronously in the user-facing request path — a slow model would make the UI feel unresponsive
- Strong multilingual support: field names, tags, and queries often contain Italian, English, or mixed terminology
- Temperature set to 0.0: fully deterministic output for tags (reproducible results)
- `qwen3` thinking mode explicitly disabled via `think=false` in API calls to avoid token overhead on simple tasks (see `routers/kb.py`)

**Technical constraints:**
- ~5 GB RAM when loaded
- On a 32 GB EC2 instance running qwen2.5:14b (~9 GB) + nomic (~274 MB), qwen3:8b adds ~5 GB — total ~14.3 GB, well within limits

**Alternatives:**
| Model | RAM | Notes |
|---|---|---|
| `qwen3:8b` (current) | ~5 GB | Best multilingual, fast, thinking-capable |
| `llama3.2:3b` | ~2 GB | Faster, less RAM, weaker on non-English |
| `gemma3:4b` | ~3 GB | Good quality/size ratio; no explicit thinking mode |
| `qwen2.5:7b` | ~4.7 GB | Previous generation; qwen3:8b is strictly better |
| `claude-haiku-4-5` | API only | Fastest option if Anthropic key available; sends data externally |

---

### 3.3 `qwen2.5:14b` — Main Document Generation Model (OLLAMA_MODEL)

**Role:** Generates the full 16-section Integration Design document (~2,000 tokens output).

**Where it is called:**
- `services/agent_service.py` → `generate_integration_doc()` (main generation path, default profile)
- `services/summarizer_service.py` → RAPTOR-lite: generates section summaries during KB upload
- `services/fact_pack_service.py` → fact-pack extraction: structured JSON extraction from requirements before generation

**Why this model:**
- Best quality/RAM/speed balance on a CPU-only `t3.2xlarge` (8 vCPU, 32 GB RAM, no GPU):
  - 9 GB RAM leaves headroom for other services
  - ~4 tok/s on CPU → ~8 min/doc (acceptable for async background generation)
  - Significantly better instruction following and document structure than 7-8B models
- `num_ctx=8192` explicitly set: Ollama default context window is only 2,048 tokens (undocumented), which causes silent truncation of long prompts containing requirements + RAG context + template
- `temperature=0.2`: low randomness for consistent document structure; not 0.0 because some creativity in phrasing is desirable
- `num_predict=2000`: prevents runaway generation on slow CPU; residual `n/a` sections are filled by Claude API enrichment if `ANTHROPIC_API_KEY` is set

**Technical constraints:**
- ~9 GB RAM (Q4_K_M quantization)
- On CPU: ~4–5 tok/s → ~7–9 minutes per document
- Recommended minimum: 16 GB RAM (leaves room for OS + other services); 32 GB comfortable

**Alternatives:**
| Model | RAM | Speed (CPU) | Quality | Notes |
|---|---|---|---|---|
| `qwen2.5:14b` (current) | ~9 GB | ~4 tok/s | ★★★★☆ | Best for CPU-only instances |
| `qwen2.5:7b` | ~5 GB | ~7 tok/s | ★★★☆☆ | Faster, less RAM, weaker on complex docs |
| `llama3.1:8b` | ~5 GB | ~6 tok/s | ★★★☆☆ | Solid baseline; weaker on Italian |
| `qwen2.5:32b` | ~19 GB | ~1.5 tok/s | ★★★★★ | Best quality; **requires GPU** for practical use |
| `gemini-2.0-flash` | API only | very fast | ★★★★★ | Cloud fallback; requires `GEMINI_API_KEY` |
| `claude-sonnet-4-6` | API only | very fast | ★★★★★ | Best quality; requires `ANTHROPIC_API_KEY` |

> **Switching models:** Override `OLLAMA_MODEL` in `.env` or `docker-compose.yml`. The `ollama-init` service reads this variable and pulls the correct model at startup.

---

### 3.4 `gemma4:26b` — Premium Document Generation Model (PREMIUM_MODEL)

**Role:** High-quality document generation used when the user selects the **"High Quality"** profile in the LLM Settings UI.

**Where it is called:**
- `services/agent_service.py` → same `generate_integration_doc()` function, activated when `llm_profile in ("high_quality", "premium")`
- Parameters: `temperature=0.0`, `top_k=30`, `top_p=0.85`, `repeat_penalty=1.1` — more conservative than the default profile, optimised for deterministic, structured output

**Why this model:**
- Google Gemma 4 26B has strong instruction following and produces richer, more detailed document sections
- `temperature=0.0` + lower `top_k` = highly deterministic output suitable for compliance-critical documents
- Available in Ollama with good quantization (Q4_K_M ~17 GB)

**Technical constraints:**
- ~17 GB RAM on CPU — barely fits on a 32 GB instance alongside other services
- On CPU without GPU: ~1–2 tok/s → 20–40 min/doc (slow but functional for async use)
- **Strongly recommended to use a GPU instance** (e.g. `g4dn.xlarge` with T4 16 GB VRAM) for practical performance
- On GPU: ~15–25 tok/s → ~2–4 min/doc

**Alternatives:**
| Model | RAM | GPU VRAM | Notes |
|---|---|---|---|
| `gemma4:26b` (current) | ~17 GB | ~16 GB | Best quality Ollama model currently available |
| `qwen2.5:32b` | ~19 GB | ~20 GB | Slightly higher RAM; comparable quality |
| `llama3.3:70b` | ~40 GB | ~48 GB | Significantly better; requires A10/A100 |
| `claude-opus-4` | API only | — | Best available; requires `ANTHROPIC_API_KEY` |
| `gemini-2.5-pro` | API only | — | Excellent; requires `GEMINI_API_KEY` |

---

### 3.5 `granite3.2-vision:2b` — Vision Language Model (VLM_MODEL_NAME)

**Role:** Generates text captions for figures, diagrams, and tables found in PDF documents during KB ingestion, so visual content becomes searchable in the vector index.

**Where it is called:**
- `services/vision_service.py` → `caption_figure(image_bytes)` — called by Docling parser whenever it extracts an image chunk

**Why this model:**
- IBM Granite Vision is specifically tuned for enterprise documents: data flows, field mapping diagrams, architecture charts, tables
- 3–5× faster than LLaVA-7b (8–15 s/figure vs 25–40 s) with comparable quality on structured content
- 2.4 GB footprint: lightweight enough to coexist with the main LLM

**Fallback chain:**
```
granite3.2-vision:2b
  └─ fails / timeout
      └─ llava:7b (VLM_FALLBACK_MODEL_NAME) — if installed
          └─ fails
              └─ "[FIGURE: no caption available]"  (placeholder, never crashes)
```

> **Note:** `llava:7b` has been removed from this deployment to save 4.7 GB. The system degrades gracefully to the placeholder on Granite failure. Set `VLM_PULL_FALLBACK=false` in `.env` to prevent docker-compose from trying to pull it.

**Technical constraints:**
- Requires Ollama `multimodal` support (built-in from Ollama 0.1.26+)
- ~2.4 GB RAM
- Disabled entirely via `VISION_CAPTIONING_ENABLED=false` (all figures get the placeholder caption)

**Alternatives:**
| Model | RAM | Speed | Notes |
|---|---|---|---|
| `granite3.2-vision:2b` (current) | ~2.4 GB | 8–15 s/fig | Best for enterprise docs |
| `llava:7b` | ~4.7 GB | 25–40 s/fig | General-purpose; weaker on structured content |
| `llava:13b` | ~8 GB | 40–60 s/fig | Better quality; high RAM cost |
| `moondream2` | ~1.7 GB | 5–8 s/fig | Fastest; weaker on complex diagrams |
| `gpt-4o` (vision) | API only | ~2–5 s/fig | Best quality; requires OpenAI key |

---

### 3.6 `llama3.1:8b` — Contextual Retrieval (CONTEXTUAL_MODEL_OLLAMA)

**Role:** Adds a short "situating annotation" (50–100 tokens) to each text chunk *before* embedding. This annotation describes where the chunk sits in the document and what it is about, making the embedding semantically richer.

**Where it is called:**
- `services/contextual_retrieval_service.py` → `add_context_to_chunks()` — called during KB upload for every chunk, *only* when `contextual_provider="ollama"` (i.e., no `ANTHROPIC_API_KEY` available)

**Why this approach (and why this model):**
- Anthropic (Sept 2024) published research showing this technique improves RAG recall@20 by **+35% with embeddings alone, +49% with BM25 + reranker**
- The model sees the full document and each chunk and writes: *"This chunk is from section 3 of the PLM integration spec and describes the error handling strategy for failed sync operations."*
- Without this annotation, the embedding of a chunk like *"retry up to 3 times with exponential backoff"* has no context — it could match irrelevant documents about any kind of retry logic
- `llama3.1:8b` is used as the offline fallback because it is compact and already present on the instance for other purposes

**Provider hierarchy:**
```
ANTHROPIC_API_KEY set?
  YES → claude-haiku-4-5 (faster, uses prompt caching — one cache miss per document, 
                          then all chunks annotated from cache)
  NO  → llama3.1:8b via Ollama (offline, slower, no caching)
```

**Technical constraints:**
- Each chunk requires one LLM call → large documents (100+ chunks) take several minutes
- `contextual_max_tokens=120`: annotation is kept short to avoid bloating the stored chunk
- `CONTEXTUAL_RETRIEVAL_ENABLED=false` disables the feature entirely (faster KB uploads, lower RAG quality)

**Alternatives:**
| Provider / Model | Speed | Quality | Notes |
|---|---|---|---|
| `claude-haiku-4-5` (API) | ~0.5 s/chunk | ★★★★★ | Preferred; prompt caching minimises cost |
| `llama3.1:8b` (current Ollama) | ~3–5 s/chunk | ★★★☆☆ | Offline fallback |
| `qwen3:8b` | ~3 s/chunk | ★★★★☆ | Could replace llama3.1:8b via `CONTEXTUAL_MODEL_OLLAMA=qwen3:8b` |
| `gemma3:4b` | ~2 s/chunk | ★★★☆☆ | Faster, slightly weaker |

---

## 4. Cloud API Models (Optional)

When API keys are configured, cloud models replace or augment Ollama models for specific tasks. All cloud calls are **opt-in** — the system runs fully offline without any API key.

### 4.1 Claude API (Anthropic)

Set `ANTHROPIC_API_KEY` in `.env` to enable.

| Task | Model | Config Var | Benefit |
|---|---|---|---|
| Contextual retrieval annotation | `claude-haiku-4-5` | `CONTEXTUAL_MODEL_CLAUDE` | 10× faster than Ollama; prompt caching means only 1 expensive call per document |
| LLM judge (RAG reranking) | `claude-haiku-4-5` | `LLM_JUDGE_MODEL` | Replaces cross-encoder for final top-K selection; opt-in via `LLM_JUDGE_ENABLED=true` |
| Section enrichment (fill `n/a`) | `claude-sonnet-4-6` | hardcoded in `agent_service.py` | Fills residual empty sections after Ollama generation |
| HTML semantic extraction | `claude-sonnet-4-6` | `CLAUDE_EXTRACTION_MODEL` | Ingestion platform: extracts structured capabilities from HTML API docs |
| HTML relevance filtering | `claude-haiku-4-5-20251001` | `CLAUDE_FILTER_MODEL` | Ingestion platform: filters irrelevant HTML pages before extraction |

### 4.2 Gemini API (Google)

Set `GEMINI_API_KEY` in `.env` to enable.

| Task | Model | Config Var | Benefit |
|---|---|---|---|
| Document generation | `gemini-2.0-flash` | UI selectable | Fast, high quality cloud alternative to Ollama |
| Premium generation | `gemini-2.5-pro` | UI selectable | Best-in-class reasoning for complex integrations |

---

## 5. EC2 Instance Sizing Guide

The table below shows which Ollama models can coexist on a single instance at full quality.

### Current deployment: `t3.2xlarge` (8 vCPU, 32 GB RAM, no GPU)

| Resident models | RAM used | Headroom | Notes |
|---|---|---|---|
| nomic + qwen3:8b + qwen2.5:14b + granite3.2-vision:2b + llama3.1:8b | ~22 GB | ~10 GB | ✅ Current production config |
| + gemma4:26b (premium profile) | ~39 GB | ❌ OOM | Premium must evict qwen2.5:14b first |

> Ollama loads models on demand and evicts LRU models when RAM pressure increases. The premium and default generation models are never used simultaneously, so eviction is safe.

### Recommended upgrade: `g4dn.xlarge` (4 vCPU, 16 GB RAM, T4 16 GB VRAM)

| Model | Where it runs | RAM/VRAM |
|---|---|---|
| qwen2.5:14b | GPU | ~9 GB VRAM |
| gemma4:26b | GPU | ~16 GB VRAM (fits exactly) |
| nomic-embed-text | CPU | ~274 MB |
| granite3.2-vision:2b | GPU or CPU | ~2.4 GB |

With GPU, document generation drops from ~8 min to ~1.5–2 min.

---

## 6. Environment Variables Reference

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_MODEL` | `qwen2.5:14b` | Main document generation model |
| `OLLAMA_TIMEOUT_SECONDS` | `900` | httpx timeout for generation calls |
| `OLLAMA_NUM_PREDICT` | `2000` | Max output tokens (cap for CPU safety) |
| `OLLAMA_TEMPERATURE` | `0.2` | Sampling temperature |
| `OLLAMA_NUM_CTX` | `8192` | Context window (overrides Ollama default 2048) |
| `TAG_MODEL` | `qwen3:8b` | Model for tags, query expansion, wiki |
| `TAG_TIMEOUT_SECONDS` | `60` | Timeout for tag/expansion calls |
| `PREMIUM_MODEL` | `gemma4:26b` | Model for "High Quality" profile |
| `EMBEDDER_MODEL_NAME` | `nomic-embed-text:v1.5` | Embedding model |
| `EMBEDDER_PROVIDER` | `ollama` | `ollama` or `default` (ChromaDB MiniLM) |
| `VLM_MODEL_NAME` | `granite3.2-vision:2b` | Primary vision model |
| `VLM_FALLBACK_MODEL_NAME` | `llava:7b` | Fallback vision model |
| `VLM_FORCE_FALLBACK` | `false` | Skip primary and use fallback directly |
| `VLM_PULL_FALLBACK` | `false` | Whether ollama-init pulls the fallback VLM |
| `VISION_CAPTIONING_ENABLED` | `true` | Disable to skip all VLM calls |
| `CONTEXTUAL_RETRIEVAL_ENABLED` | `true` | Enable chunk situating annotations |
| `CONTEXTUAL_PROVIDER` | `claude` | `claude` or `ollama` |
| `CONTEXTUAL_MODEL_OLLAMA` | `llama3.1:8b` | Ollama model for contextual retrieval |
| `CONTEXTUAL_MODEL_CLAUDE` | `claude-haiku-4-5` | Claude model for contextual retrieval |
| `ANTHROPIC_API_KEY` | *(unset)* | Enables Claude API enrichment |
| `GEMINI_API_KEY` | *(unset)* | Enables Gemini API generation |

---

## 7. Related ADRs

| ADR | Topic |
|---|---|
| [ADR-046](adr/ADR-046-llm-profile-routing.md) | LLM profile routing (default / premium) |
| [ADR-049](adr/ADR-049-gemini-provider.md) | Gemini provider integration |
| [ADR-053](adr/ADR-053-parser-vlm-upgrade.md) | VLM upgrade to Granite-Vision |
| [ADR-054](adr/ADR-054-embedder-nomic.md) | Embedder upgrade to nomic-embed-text |
| [ADR-055](adr/ADR-055-reranker-rrf.md) | Reranker and RRF fusion pipeline |
| [ADR-056](adr/ADR-056-contextual-retrieval.md) | Contextual retrieval implementation |
| [ADR-027](adr/ADR-027-bm25-hybrid-retrieval.md) | BM25 hybrid retrieval (uses TAG_MODEL for expansion) |
| [ADR-031](adr/ADR-034-docling-vision-parser.md) | Docling parser + VLM integration |
| [ADR-032](adr/ADR-035-raptor-lite-summaries.md) | RAPTOR-lite summaries (uses OLLAMA_MODEL) |
