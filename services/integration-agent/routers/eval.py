"""
Eval Router — RAG Pipeline Evaluation Harness (ADR-053/056)

GET    /api/v1/eval/domains              list available domain names
POST   /api/v1/eval/run                  start an eval run → {job_id}
GET    /api/v1/eval/stream/{job_id}      SSE: per-question progress + final metrics
GET    /api/v1/eval/jobs/{job_id}        poll job status (alternative to SSE)
GET    /api/v1/eval/reports              list saved report labels + summary metrics
GET    /api/v1/eval/reports/{label}      get full report JSON
DELETE /api/v1/eval/reports/{label}      delete a report [token required]
GET    /api/v1/eval/compare              compare two saved reports ?a=label_a&b=label_b
"""
from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from routers.admin import require_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/eval", tags=["eval"])

# Paths relative to this file: routers/eval.py → service root → tests/eval
_SERVICE_ROOT = Path(__file__).parent.parent
_EVAL_BASE    = _SERVICE_ROOT / "tests" / "eval"
_DOMAINS_DIR  = _EVAL_BASE / "domains"
_REPORTS_DIR  = _EVAL_BASE / "reports"

# In-memory job store (process-scoped; lost on restart, which is fine for eval)
_jobs: dict[str, dict[str, Any]] = {}


# ── Request / response models ─────────────────────────────────────────────────

class EvalRunRequest(BaseModel):
    label: str
    domain: str | None = None    # "all" or single domain name
    domains: list[str] | None = None  # explicit list of domain names


# ── Helpers ───────────────────────────────────────────────────────────────────

def _list_domains() -> list[str]:
    if not _DOMAINS_DIR.exists():
        return []
    return sorted(p.stem for p in _DOMAINS_DIR.glob("*.yaml"))


def _save_report(label: str, metrics: dict) -> None:
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (_REPORTS_DIR / f"{label}.json").write_text(json.dumps(metrics, indent=2))


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/domains")
def list_domains():
    return _list_domains()


@router.post("/run")
def start_eval_run(body: EvalRunRequest):
    if not body.label.strip():
        raise HTTPException(400, "label must be a non-empty string")

    job_id = str(uuid.uuid4())[:8]
    q: queue.Queue = queue.Queue()
    _jobs[job_id] = {"status": "running", "queue": q, "result": None, "error": None}

    def _run():
        try:
            from tests.eval.run_rag_eval import load_golden_questions
            from tests.eval.runner import execute_pipeline

            questions = load_golden_questions(
                domain=body.domain,
                domains=body.domains,
            )
            if not questions:
                raise ValueError("No questions found — check domain names")

            q.put({"type": "start", "total": len(questions), "label": body.label})

            metrics = execute_pipeline(
                questions,
                on_progress=lambda p: q.put({"type": "progress", **p}),
            )

            _save_report(body.label, metrics)
            _jobs[job_id]["result"] = metrics
            _jobs[job_id]["status"] = "done"
            q.put({"type": "done", "metrics": metrics})

        except Exception as exc:
            logger.exception("[Eval] job %s failed", job_id)
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error"] = str(exc)
            q.put({"type": "error", "message": str(exc)})
        finally:
            q.put(None)  # SSE sentinel

    threading.Thread(target=_run, daemon=True).start()
    logger.info("[Eval] started job %s  label=%s", job_id, body.label)
    return {"job_id": job_id}


@router.get("/stream/{job_id}")
async def stream_eval(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, f"Job '{job_id}' not found")

    async def _generate():
        q = job["queue"]
        loop = asyncio.get_event_loop()
        while True:
            msg = await loop.run_in_executor(None, q.get)
            if msg is None:
                break
            yield f"data: {json.dumps(msg)}\n\n"

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, f"Job '{job_id}' not found")
    return {
        "job_id": job_id,
        "status": job["status"],
        "result": job["result"],
        "error": job["error"],
    }


@router.get("/reports")
def list_reports():
    if not _REPORTS_DIR.exists():
        return []
    reports = []
    for p in sorted(_REPORTS_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            data = json.loads(p.read_text())
            reports.append({"label": p.stem, "metrics": data})
        except Exception:
            pass
    return reports


@router.get("/reports/{label}")
def get_report(label: str):
    path = _REPORTS_DIR / f"{label}.json"
    if not path.exists():
        raise HTTPException(404, f"Report '{label}' not found")
    return json.loads(path.read_text())


@router.delete("/reports/{label}")
def delete_report(label: str, _=Depends(require_token)):
    path = _REPORTS_DIR / f"{label}.json"
    if not path.exists():
        raise HTTPException(404, f"Report '{label}' not found")
    path.unlink()
    return {"deleted": label}


@router.get("/compare")
def compare_reports(
    a: str = Query(..., description="Label of baseline run"),
    b: str = Query(..., description="Label of comparison run"),
):
    def _load(label: str) -> dict:
        p = _REPORTS_DIR / f"{label}.json"
        if not p.exists():
            raise HTTPException(404, f"Report '{label}' not found")
        return json.loads(p.read_text())

    ma, mb = _load(a), _load(b)
    diff: dict[str, Any] = {}
    for k in set(ma.keys()) & set(mb.keys()):
        va, vb = ma[k], mb[k]
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
            diff[k] = {
                "a": round(float(va), 4),
                "b": round(float(vb), 4),
                "delta": round(float(vb) - float(va), 4),
                "pct": round((float(vb) - float(va)) / float(va) * 100, 1) if va != 0 else None,
            }
    return {"label_a": a, "label_b": b, "metrics": diff}
