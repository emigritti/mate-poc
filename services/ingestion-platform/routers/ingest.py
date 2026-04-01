"""
Ingestion Platform — Ingest Trigger Router

Endpoints for triggering ingestion runs (called by n8n or manually).
Each endpoint is async — long-running work runs in the background.
"""
import uuid
import logging
from datetime import datetime

import chromadb
from fastapi import APIRouter, BackgroundTasks, HTTPException, status

import state
from config import settings
from models.source import Source, SourceRun, SourceType, RunTrigger, RunStatus, SourceSnapshot
from collectors.openapi.fetcher import OpenAPIFetcher, FetchError
from collectors.openapi.parser import OpenAPIParser, OpenAPIParseError
from collectors.openapi.normalizer import OpenAPINormalizer
from collectors.openapi.chunker import OpenAPIChunker
from collectors.openapi.differ import OpenAPIDiffer
from collectors.html.crawler import HTMLCrawler
from collectors.html.cleaner import HTMLCleaner
from collectors.html.extractor import HTMLRelevanceFilter
from collectors.html.agent_extractor import HTMLAgentExtractor
from collectors.html.normalizer import HTMLNormalizer
from collectors.html.chunker import HTMLChunker
from services.indexing_service import IndexingService
from services.diff_service import DiffService
from services.claude_service import get_claude_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/ingest", tags=["ingest"])


async def _rebuild_agent_bm25(source_code: str) -> None:
    """Fire-and-forget: ask integration-agent to rebuild its BM25 index.

    Called after a successful ingest run so newly indexed chunks are
    immediately available for hybrid retrieval without an agent restart.
    Failures are logged but never propagate — ingestion success must not
    depend on the agent being reachable.
    """
    import httpx
    url = f"{settings.integration_agent_url}/api/v1/kb/rebuild-bm25"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url)
            if resp.status_code == 200:
                logger.info("[BM25] Agent BM25 rebuild triggered for source=%s: %s", source_code, resp.json())
            else:
                logger.warning("[BM25] Agent BM25 rebuild returned %d for source=%s", resp.status_code, source_code)
    except Exception as exc:
        logger.warning("[BM25] Failed to trigger BM25 rebuild for source=%s: %s", source_code, exc)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.utcnow()


async def _get_source_or_404(source_id: str) -> dict:
    doc = await state.sources_col.find_one({"id": source_id})
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Source '{source_id}' not found")
    return doc


def _source_from_doc(doc: dict) -> Source:
    from routers.sources import _doc_to_source
    return _doc_to_source(doc)


def _get_chroma_collection():
    client = chromadb.HttpClient(
        host=settings.chroma_host,
        port=settings.chroma_port,
    )
    return client.get_or_create_collection("kb_collection")


async def _start_run(source_id: str, trigger: RunTrigger, collector_type: SourceType) -> SourceRun:
    run_id = f"run_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{source_id[:8]}"
    run = SourceRun(
        id=run_id,
        source_id=source_id,
        trigger=trigger,
        collector_type=collector_type,
        status=RunStatus.RUNNING,
        started_at=_now(),
    )
    await state.runs_col.insert_one({**run.model_dump(), "_id": run_id})
    return run


async def _finish_run(run: SourceRun, chunks_created: int, changed: bool, errors: list[str]) -> None:
    run.status = RunStatus.FAILED if errors and not chunks_created else RunStatus.SUCCESS
    run.finished_at = _now()
    run.chunks_created = chunks_created
    run.changed = changed
    run.errors = errors
    await state.runs_col.replace_one({"id": run.id}, {**run.model_dump(), "_id": run.id})


async def _save_snapshot(
    source_id: str,
    content_hash: str,
    capabilities_count: int,
    diff_summary: str,
) -> None:
    snap_id = f"snap_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{source_id[:8]}"
    # Mark previous snapshot as not current
    await state.snapshots_col.replace_one(
        {"source_id": source_id, "is_current": True},
        {"$set": {"is_current": False}},
    )
    snap = SourceSnapshot(
        id=snap_id,
        source_id=source_id,
        content_hash=content_hash,
        capabilities_count=capabilities_count,
        is_current=True,
        diff_summary=diff_summary,
    )
    await state.snapshots_col.insert_one({**snap.model_dump(), "_id": snap_id})


# ── OpenAPI ingestion pipeline ────────────────────────────────────────────────

async def _run_openapi_ingestion(source_id: str, run: SourceRun) -> None:
    """Background task: fetch → parse → normalize → chunk → diff → index."""
    errors: list[str] = []
    chunks_created = 0
    changed = False

    try:
        # 1. Load source
        doc = await state.sources_col.find_one({"id": source_id})
        if not doc:
            await _finish_run(run, 0, False, [f"Source {source_id} not found"])
            return
        source = _source_from_doc(doc)
        url = source.entrypoints[0]

        # 2. Fetch previous snapshot hash for ETag+diff optimization
        prev_snap = await state.snapshots_col.find_one({"source_id": source_id, "is_current": True})
        prev_hash = prev_snap["content_hash"] if prev_snap else None

        # 3. Fetch spec
        fetcher = OpenAPIFetcher()
        try:
            fetch_result = await fetcher.fetch(url)
        except FetchError as exc:
            await _finish_run(run, 0, False, [str(exc)])
            return

        if not fetch_result.changed:
            await _finish_run(run, 0, False, [])
            return

        # 4. Parse
        parser = OpenAPIParser()
        try:
            spec = parser.parse(fetch_result.content)
        except OpenAPIParseError as exc:
            await _finish_run(run, 0, False, [f"Parse error: {exc}"])
            return

        # 5. Diff check
        differ = OpenAPIDiffer()
        new_hash = differ.compute_hash(spec)
        if prev_hash and not differ.has_changed(prev_hash, new_hash):
            await _finish_run(run, 0, False, [])
            return
        changed = True

        # 6. Normalize → capabilities
        normalizer = OpenAPINormalizer()
        caps = normalizer.normalize(spec, source_code=source.code)

        # 7. Chunk
        chunker = OpenAPIChunker()
        chunks = chunker.chunk(caps, source_code=source.code, tags=source.tags, spec_overview=spec)

        # 8. Index into shared ChromaDB
        kb_col = _get_chroma_collection()
        indexer = IndexingService(kb_collection=kb_col)
        # Delete old chunks for this source before re-indexing
        indexer.delete_source_chunks(source.code)
        chunks_created = indexer.upsert_chunks(chunks, snapshot_id=run.id)

        # 8b. Notify integration-agent to rebuild BM25 (includes new ingestion chunks)
        if chunks_created > 0:
            await _rebuild_agent_bm25(source.code)

        # 9. Diff summary (Claude Haiku if available)
        claude = get_claude_service(
            settings.anthropic_api_key,
            settings.claude_extraction_model,
            settings.claude_filter_model,
        )
        diff_svc = DiffService(claude_service=claude)
        new_ops = differ.extract_operation_ids(spec)
        old_ops = differ.extract_operation_ids({}) if not prev_snap else set()
        diff_summary = await diff_svc.summarize(source.code, old_ops, new_ops)

        # 10. Save snapshot
        await _save_snapshot(source_id, new_hash, len(caps), diff_summary)

    except Exception as exc:
        logger.exception("Unexpected error in OpenAPI ingestion for %s", source_id)
        errors.append(str(exc))

    await _finish_run(run, chunks_created, changed, errors)


# ── HTML ingestion pipeline ───────────────────────────────────────────────────

async def _run_html_ingestion(source_id: str, run: SourceRun) -> None:
    """Background task: crawl → clean → filter → extract → normalize → chunk → index."""
    from hashlib import sha256

    errors: list[str] = []
    chunks_created = 0
    changed = False

    try:
        # 1. Load source
        doc = await state.sources_col.find_one({"id": source_id})
        if not doc:
            await _finish_run(run, 0, False, [f"Source {source_id} not found"])
            return
        source = _source_from_doc(doc)

        # 2. Crawl entrypoints (httpx + BeautifulSoup BFS)
        crawler = HTMLCrawler()
        pages = await crawler.crawl(
            source.entrypoints,
            max_pages=settings.max_html_pages_per_crawl,
        )
        if not pages:
            await _finish_run(run, 0, False, ["No pages fetched from entrypoints"])
            return

        # 3. Claude services (gracefully absent when ANTHROPIC_API_KEY not set)
        claude = get_claude_service(
            settings.anthropic_api_key,
            settings.claude_extraction_model,
            settings.claude_filter_model,
        )
        relevance_filter = HTMLRelevanceFilter(claude_service=claude)
        agent_extractor = HTMLAgentExtractor(claude_service=claude)
        normalizer = HTMLNormalizer()
        cleaner = HTMLCleaner()

        # 4. Per-page pipeline: clean → relevance filter → extract → normalize
        all_capabilities = []
        for page in pages:
            clean_text = cleaner.clean(page.html)
            if not clean_text.strip():
                continue
            if not await relevance_filter.is_relevant(clean_text, page.url):
                logger.debug("Skipping irrelevant page: %s", page.url)
                continue
            raw_caps = await agent_extractor.extract(clean_text, page.url)
            caps = normalizer.normalize(raw_caps, source_code=source.code)
            all_capabilities.extend(caps)

        if not all_capabilities:
            logger.info("No capabilities extracted for source %s — crawl completed", source_id)
            await _finish_run(run, 0, True, [])
            return

        changed = True

        # 5. Hash-based dedup: skip re-index if content unchanged
        content_hash = sha256(
            "|".join(
                f"{c.capability_id}:{c.description}" for c in all_capabilities
            ).encode()
        ).hexdigest()
        prev_snap = await state.snapshots_col.find_one({"source_id": source_id, "is_current": True})
        if prev_snap and prev_snap.get("content_hash") == content_hash:
            await _finish_run(run, 0, False, [])
            return

        # 6. Chunk
        chunker = HTMLChunker()
        chunks = chunker.chunk(all_capabilities, source_code=source.code, tags=source.tags)

        # 7. Index into shared ChromaDB (delete old chunks first)
        kb_col = _get_chroma_collection()
        indexer = IndexingService(kb_collection=kb_col)
        indexer.delete_source_chunks(source.code)
        chunks_created = indexer.upsert_chunks(chunks, snapshot_id=run.id)

        # 7b. Notify integration-agent to rebuild BM25 (includes new ingestion chunks)
        if chunks_created > 0:
            await _rebuild_agent_bm25(source.code)

        # 8. Diff summary via Claude Haiku (best-effort)
        diff_svc = DiffService(claude_service=claude)
        diff_summary = await diff_svc.summarize(
            source.code,
            set(),
            {c.name for c in all_capabilities},
        )

        # 9. Persist snapshot
        await _save_snapshot(source_id, content_hash, len(all_capabilities), diff_summary)

    except Exception as exc:
        logger.exception("Unexpected error in HTML ingestion for %s", source_id)
        errors.append(str(exc))

    await _finish_run(run, chunks_created, changed, errors)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/openapi/{source_id}", status_code=status.HTTP_202_ACCEPTED)
async def trigger_openapi_ingest(
    source_id: str,
    background_tasks: BackgroundTasks,
) -> dict:
    """Trigger OpenAPI spec ingestion. Returns run_id immediately (async)."""
    await _get_source_or_404(source_id)
    run = await _start_run(source_id, RunTrigger.MANUAL, SourceType.OPENAPI)
    background_tasks.add_task(_run_openapi_ingestion, source_id, run)
    return {"run_id": run.id, "status": "accepted", "source_id": source_id}


@router.post("/mcp/{source_id}", status_code=status.HTTP_202_ACCEPTED)
async def trigger_mcp_ingest(
    source_id: str,
    background_tasks: BackgroundTasks,
) -> dict:
    """Trigger MCP server ingestion. Returns run_id immediately (Phase 3)."""
    await _get_source_or_404(source_id)
    run = await _start_run(source_id, RunTrigger.MANUAL, SourceType.MCP)
    # MCP ingestion logic implemented in Phase 3
    logger.info("MCP ingestion queued for source %s (run %s)", source_id, run.id)
    await _finish_run(run, 0, False, ["MCP collector not yet implemented — Phase 3"])
    return {"run_id": run.id, "status": "accepted", "source_id": source_id}


@router.post("/html/{source_id}", status_code=status.HTTP_202_ACCEPTED)
async def trigger_html_ingest(
    source_id: str,
    background_tasks: BackgroundTasks,
) -> dict:
    """Trigger HTML crawler ingestion. Returns run_id immediately (async background)."""
    await _get_source_or_404(source_id)
    run = await _start_run(source_id, RunTrigger.MANUAL, SourceType.HTML)
    background_tasks.add_task(_run_html_ingestion, source_id, run)
    return {"run_id": run.id, "status": "accepted", "source_id": source_id}
