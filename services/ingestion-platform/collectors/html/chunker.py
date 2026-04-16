"""
HTML Collector — Chunker (ADR-045: UI Semantic Chunking)

Converts CanonicalCapability objects into CanonicalChunk objects for ChromaDB indexing.

For UI screens (kind=ui_screen, metadata contains ui_context):
  - 1 ui_flow_chunk        : full screen summary (page, role, fields, actions)
  - N validation_rule_chunk : one per validation rule
  - N state_transition_chunk: one per state transition

For all other capabilities:
  - 1 text chunk (unchanged behavior — backward compatible)

Global chunk index is monotonically incremented across all sub-chunks.
"""
import logging
from typing import Any

from models.capability import CanonicalCapability, CanonicalChunk

logger = logging.getLogger(__name__)


class HTMLChunker:
    """
    Produces typed CanonicalChunk objects per CanonicalCapability.
    UI screens generate multiple typed chunks; other capabilities generate one text chunk.
    """

    def chunk(
        self,
        capabilities: list[CanonicalCapability],
        source_code: str,
        tags: list[str],
    ) -> list[CanonicalChunk]:
        """
        Args:
            capabilities: Validated CanonicalCapability list from HTMLNormalizer.
            source_code: Source identifier (e.g. "payment_docs").
            tags: List of tags for RAG filtering.

        Returns:
            List of CanonicalChunk ready for IndexingService.upsert_chunks().
        """
        chunks: list[CanonicalChunk] = []
        idx = 0
        for cap in capabilities:
            ui_context = cap.metadata.get("ui_context") if cap.metadata else None
            if ui_context and isinstance(ui_context, dict):
                new_chunks = self._ui_chunks(cap, source_code, tags, start_idx=idx, ui_context=ui_context)
            else:
                new_chunks = [self._text_chunk(cap, source_code, tags, idx)]
            chunks.extend(new_chunks)
            idx += len(new_chunks)
        return chunks

    # ── UI screen: typed multi-chunk generation ───────────────────────────

    def _ui_chunks(
        self,
        cap: CanonicalCapability,
        source_code: str,
        tags: list[str],
        start_idx: int,
        ui_context: dict[str, Any],
    ) -> list[CanonicalChunk]:
        result: list[CanonicalChunk] = []
        idx = start_idx

        # 1. ui_flow_chunk — complete screen overview
        result.append(CanonicalChunk(
            text=self._ui_flow_text(cap, ui_context),
            index=idx,
            source_code=source_code,
            source_type="html",
            capability_kind=cap.kind.value,
            chunk_type="ui_flow_chunk",
            section_header=cap.name,
            page_url=cap.source_trace.page_url,
            tags=tags,
            confidence=cap.confidence,
        ))
        idx += 1

        # 2. validation_rule_chunk — one per rule
        for rule in ui_context.get("validations") or []:
            if not rule:
                continue
            result.append(CanonicalChunk(
                text=self._validation_text(cap, rule),
                index=idx,
                source_code=source_code,
                source_type="html",
                capability_kind=cap.kind.value,
                chunk_type="validation_rule_chunk",
                section_header=cap.name,
                page_url=cap.source_trace.page_url,
                tags=tags,
                confidence=cap.confidence,
            ))
            idx += 1

        # 3. state_transition_chunk — one per transition
        for transition in ui_context.get("state_transitions") or []:
            if not transition:
                continue
            result.append(CanonicalChunk(
                text=self._transition_text(cap, transition),
                index=idx,
                source_code=source_code,
                source_type="html",
                capability_kind=cap.kind.value,
                chunk_type="state_transition_chunk",
                section_header=cap.name,
                page_url=cap.source_trace.page_url,
                tags=tags,
                confidence=cap.confidence,
            ))
            idx += 1

        return result

    # ── Text builders ─────────────────────────────────────────────────────

    def _ui_flow_text(self, cap: CanonicalCapability, ui: dict[str, Any]) -> str:
        lines = [f"[UI_SCREEN] {ui.get('page', cap.name)}"]
        if ui.get("role"):
            lines.append(f"Role: {ui['role']}")
        fields = ui.get("fields") or []
        if fields:
            field_strs = []
            for f in fields:
                fstr = f"{f.get('name', '')} ({f.get('type', '')})"
                values = f.get("values")
                if values:
                    fstr += f": {', '.join(str(v) for v in values)}"
                field_strs.append(fstr)
            lines.append(f"Fields: {'; '.join(field_strs)}")
        actions = ui.get("actions") or []
        if actions:
            lines.append(f"Actions: {', '.join(actions)}")
        messages = ui.get("messages") or []
        if messages:
            lines.append(f"Messages: {'; '.join(messages)}")
        if cap.description:
            lines.append(cap.description)
        if cap.source_trace.page_url:
            lines.append(f"Source: {cap.source_trace.page_url}")
        return "\n".join(lines)

    def _validation_text(self, cap: CanonicalCapability, rule: str) -> str:
        lines = [f"[VALIDATION] {cap.name}", f"Rule: {rule}"]
        if cap.source_trace.page_url:
            lines.append(f"Source: {cap.source_trace.page_url}")
        return "\n".join(lines)

    def _transition_text(self, cap: CanonicalCapability, transition: str) -> str:
        lines = [f"[STATE_TRANSITION] {cap.name}", f"Transition: {transition}"]
        if cap.source_trace.page_url:
            lines.append(f"Source: {cap.source_trace.page_url}")
        return "\n".join(lines)

    # ── Fallback: regular single text chunk ───────────────────────────────

    def _text_chunk(
        self,
        cap: CanonicalCapability,
        source_code: str,
        tags: list[str],
        idx: int,
    ) -> CanonicalChunk:
        return CanonicalChunk(
            text=self._capability_to_text(cap),
            index=idx,
            source_code=source_code,
            source_type="html",
            capability_kind=cap.kind.value,
            chunk_type="text",
            section_header=cap.name,
            page_url=cap.source_trace.page_url,
            tags=tags,
            confidence=cap.confidence,
        )

    def _capability_to_text(self, cap: CanonicalCapability) -> str:
        lines = [f"[{cap.kind.value.upper()}] {cap.name}", cap.description]
        if cap.source_trace.page_url:
            lines.append(f"Source: {cap.source_trace.page_url}")
        if cap.source_trace.section:
            lines.append(f"Section: {cap.source_trace.section}")
        return "\n".join(filter(None, lines))
