"""
Integration Agent — LLM Output Sanitization Guard
ADR-015: LLM output is ALWAYS treated as untrusted input (CLAUDE.md §10-11).

Two functions are exposed:
  - sanitize_llm_output()    : strict guard for machine-generated content.
  - sanitize_human_content() : lenient guard for HITL-edited markdown.

Quality gate (document-quality improvements #1 and #2):
  - assess_quality()         : non-destructive quality assessment (6 volume signals
                               + 3 structural validators).
  - enforce_quality_gate()   : raises QualityGateError or warns based on mode.

OWASP A03 / Agentic AI injection mitigations:
  1. Structural guard — LLM output MUST start with the expected heading.
  2. HTML strip via bleach allowlist — prevents stored XSS in the dashboard.
  3. Hard truncation — prevents resource exhaustion from runaway generation.
"""

import logging
import bleach
from dataclasses import dataclass, field
import re

logger = logging.getLogger(__name__)

# ── Allowlist ──────────────────────────────────────────────────────────────────
# Only elements that a standard markdown renderer produces are allowed.
# <script>, <iframe>, <object>, <embed>, event handlers — all stripped.
_ALLOWED_TAGS: list[str] = [
    "h1", "h2", "h3", "h4", "h5", "h6",
    "p", "br", "hr",
    "ul", "ol", "li",
    "strong", "em", "code", "pre", "blockquote",
    "table", "thead", "tbody", "tr", "th", "td",
    "a",
]
_ALLOWED_ATTRS: dict[str, list[str]] = {"a": ["href", "title"]}

# ── Constants ──────────────────────────────────────────────────────────────────
_MAX_CHARS: int = 50_000
_REQUIRED_PREFIX: str = "# Integration Design"
# Legacy map kept for backward compatibility with existing tests
_REQUIRED_PREFIX_BY_TYPE: dict[str, str] = {
    "integration": _REQUIRED_PREFIX,
    "functional":  _REQUIRED_PREFIX,   # legacy alias
    "technical":   _REQUIRED_PREFIX,   # legacy alias
}

# ── Quality thresholds (volume signals) ───────────────────────────────────────
# The integration_base_template.md has 16 ## sections; tolerate up to 6 missing.
_MIN_SECTION_COUNT: int = 10       # at least 10 ## headings expected
_MAX_NA_RATIO: float = 0.30        # max 30% of sections can be n/a
_MIN_WORD_COUNT: int = 300         # minimum meaningful word count
_MIN_MAPPING_TABLES: int = 1       # at least 1 Markdown pipe table (data mapping)

# Patterns for volume quality signals
_MERMAID_RE = re.compile(r"```mermaid", re.IGNORECASE)
_TABLE_SEP_RE = re.compile(r"^\|[\s\-|:]+\|", re.MULTILINE)   # separator row
_PLACEHOLDER_RE = re.compile(
    r"\[TODO\]|\[TBD\]|\[PLACEHOLDER\]|\[INSERT[^\]]*\]|\bTODO:|\[ADD HERE\]",
    re.IGNORECASE,
)

# ── Structural validation patterns (Point 2) ──────────────────────────────────

# Extracts full ```mermaid...``` blocks; DOTALL captures multiline body
_MERMAID_BLOCK_RE = re.compile(r"```mermaid\s*\n(.*?)```", re.IGNORECASE | re.DOTALL)

# Recognized Mermaid diagram type keywords (checked on first non-empty line of block)
_MERMAID_TYPE_RE = re.compile(
    r"^\s*(flowchart|graph|sequenceDiagram|classDiagram|stateDiagram(?:-v2)?|erDiagram|gantt|pie)\b",
    re.IGNORECASE,
)

# Flowchart edge/arrow detection
_FLOWCHART_ARROW_RE = re.compile(r"-->|---|==>|-\.->|==")

# SequenceDiagram interaction detection (->> solid, -->> dashed, -x/-x lost messages)
_SEQ_INTERACTION_RE = re.compile(r"->>|-->>|-x|--x")

# Template stub placeholder node detection — matches default names from the template stubs.
# Only the SHORT node IDs (Src, Int, Tgt) followed by `[` are checked for flowcharts;
# "Integration Layer" is NOT included because it is a valid real component label.
_MERMAID_STUB_RE = re.compile(
    r"""
    \b(?:
        Src\s*\[(?!")                        # flowchart: Src[...] stub (no double-quote = stub)
        | Int\s*\[(?!")                      # flowchart: Int[...] stub (double-quote = real label)
        | Tgt\s*\[(?!")                      # flowchart: Tgt[...] stub
        | participant\s+(?:Src|Int|Tgt)\b    # sequenceDiagram stub participant IDs
        | (?:Source|Target)\s+System         # generic names from template stub
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)

# Complete Markdown table: ≥1 header row + separator row + ≥1 data row
_TABLE_BLOCK_RE = re.compile(
    r"(?:\|[^\n]+\|\n)+\|[\s\-|:]+\|\n(?:\|[^\n]+\|\n?)+",
    re.MULTILINE,
)

# Column header keywords that identify a data mapping table
_MAPPING_HEADER_RE = re.compile(
    r"\b(?:source|src|target|tgt|field|mapping|transformation|transform|rule)\b",
    re.IGNORECASE,
)

# Section-to-required-artifact rules.
# Each entry: (section_keyword, artifact_label, check_fn)
# check_fn(section_body: str) -> bool — True = OK, False = artifact missing
_SECTION_ARTIFACT_RULES: list[tuple[str, str]] = [
    (
        "high-level architecture",
        "Mermaid flowchart/graph diagram",
        lambda body: bool(re.search(r"```mermaid[\s\S]*?(?:flowchart|graph)\b", body, re.IGNORECASE)),
    ),
    (
        "detailed flow",
        "Mermaid sequenceDiagram",
        lambda body: bool(re.search(r"```mermaid[\s\S]*?sequenceDiagram\b", body, re.IGNORECASE)),
    ),
    (
        "data mapping",
        "pipe table with source/target columns",
        lambda body: bool(re.search(r"^\|[\s\-|:]+\|", body, re.MULTILINE)),
    ),
]

# ── Quality gate threshold ─────────────────────────────────────────────────────
_QUALITY_GATE_MIN_SCORE: float = 0.60


# ── Exceptions ─────────────────────────────────────────────────────────────────
class LLMOutputValidationError(ValueError):
    """Raised when LLM output fails the structural guard."""


class QualityGateError(ValueError):
    """Raised when document quality is below the minimum threshold (block mode)."""


# ── Public API ─────────────────────────────────────────────────────────────────

def sanitize_llm_output(raw: str, doc_type: str = "integration") -> str:
    """
    Validate and sanitize LLM-generated markdown (strict mode).

    Strategy:
      1. Fast path  — output starts with the required heading: use as-is.
      2. Fallback   — LLM added a preamble: find the heading and strip before it.
      3. Hard fail  — required heading not found anywhere: reject.

    Args:
        raw:      Raw LLM output string.
        doc_type: "integration" (default). Legacy values "functional"/"technical" are accepted.

    Raises:
        LLMOutputValidationError: if the required prefix is absent entirely.

    Returns:
        Sanitized markdown string, truncated to _MAX_CHARS.
    """
    required_prefix = _REQUIRED_PREFIX_BY_TYPE.get(doc_type, _REQUIRED_PREFIX_BY_TYPE["functional"])

    if not raw or not raw.strip():
        raise LLMOutputValidationError("LLM returned empty output.")

    text = raw.strip()

    # Fast path — correct output
    if text.startswith(required_prefix):
        return _apply_bleach_and_truncate(text)

    # Fallback 1 — exact heading present but preceded by a preamble
    idx = text.find(required_prefix)
    if idx != -1:
        logger.warning(
            "[OutputGuard] Preamble detected (%d chars stripped) before '%s'.",
            idx,
            required_prefix,
        )
        return _apply_bleach_and_truncate(text[idx:])

    # Fallback 2 — model used a slightly different heading (case / extra words).
    # Matches: "# Integration Design", "# Integration Design Document",
    # "# PLM to SAP Integration Design", etc. — any H1 containing the key phrase.
    relaxed = re.search(r"^#[^#].*Integration\s+Design", text, re.MULTILINE | re.IGNORECASE)
    if relaxed:
        stripped_chars = relaxed.start()
        logger.warning(
            "[OutputGuard] Relaxed heading match '%s' at offset %d — preamble stripped.",
            text[relaxed.start(): relaxed.start() + 60].replace("\n", " "),
            stripped_chars,
        )
        return _apply_bleach_and_truncate(text[relaxed.start():])

    # Hard fail — no integration design heading found anywhere
    logger.error(
        "[OutputGuard] Structural guard hard-fail. First 300 chars: %r", text[:300]
    )
    raise LLMOutputValidationError(
        f"Output must contain '{required_prefix}'. "
        "Got: {!r}".format(text[:120])
    )


def sanitize_human_content(raw: str) -> str:
    """
    Sanitize human-edited markdown (lenient mode — no structural guard).

    Used for HITL reviewer edits in approve_doc().  The reviewer may
    legitimately change headings, so the structural guard is NOT applied.
    HTML stripping and truncation still protect against clipboard paste attacks.

    Returns:
        Sanitized markdown string, truncated to _MAX_CHARS.
    """
    if not raw:
        return ""
    return _apply_bleach_and_truncate(raw)


# ── Quality Assessment ─────────────────────────────────────────────────────────

@dataclass
class QualityReport:
    """Non-destructive quality assessment of an LLM-generated document."""
    section_count: int
    na_ratio: float
    word_count: int
    has_mermaid_diagram: bool
    mapping_table_count: int
    placeholder_count: int
    quality_score: float
    passed: bool
    issues: list[str] = field(default_factory=list)
    # Point 2 — structural validation sub-reports (empty list = no issues)
    mermaid_syntax_issues: list[str] = field(default_factory=list)
    table_structure_issues: list[str] = field(default_factory=list)
    section_artifact_issues: list[str] = field(default_factory=list)


# ── Structural validators (private) ───────────────────────────────────────────

def _validate_mermaid_blocks(content: str) -> list[str]:
    """
    Validate syntax and content of every ```mermaid block.

    Checks per block:
      - Recognized diagram type keyword on first non-empty line
      - Minimum content (>= 3 non-empty lines: type + 2 content lines)
      - No template stub placeholder nodes (Src/Int/Tgt, Source System, etc.)
      - Flowchart/graph: at least one arrow (-->, ---, etc.)
      - sequenceDiagram: at least one interaction (->>, etc.)

    Returns list of issue strings (empty = all blocks valid).
    """
    blocks = _MERMAID_BLOCK_RE.findall(content)
    if not blocks:
        return ["No Mermaid blocks found."]

    issues: list[str] = []
    for idx, block_body in enumerate(blocks, start=1):
        non_empty = [ln for ln in block_body.splitlines() if ln.strip()]

        if not non_empty:
            issues.append(f"Mermaid block #{idx} is empty.")
            continue

        # Diagram type recognition
        type_match = _MERMAID_TYPE_RE.match(non_empty[0])
        if not type_match:
            issues.append(
                f"Mermaid block #{idx}: unrecognized diagram type "
                f"'{non_empty[0].strip()[:40]}'."
            )
            diagram_type = ""
        else:
            diagram_type = type_match.group(1).lower()

        # Minimum content lines
        if len(non_empty) < 3:
            issues.append(
                f"Mermaid block #{idx}: too short ({len(non_empty)} non-empty line(s), "
                "minimum 3 expected)."
            )

        # Template stub placeholder detection
        if _MERMAID_STUB_RE.search(block_body):
            issues.append(
                f"Mermaid block #{idx}: contains template placeholder nodes "
                "(Src/Int/Tgt or generic 'Source System'/'Target System' names) — "
                "replace with real system names."
            )

        # Type-specific checks
        is_flowchart = diagram_type in ("flowchart", "graph")
        is_sequence = diagram_type == "sequencediagram"

        if is_flowchart and not _FLOWCHART_ARROW_RE.search(block_body):
            issues.append(
                f"Mermaid block #{idx} (flowchart): no edge/arrow found "
                "(-->, ---, ==>, etc. required)."
            )
        if is_sequence and not _SEQ_INTERACTION_RE.search(block_body):
            issues.append(
                f"Mermaid block #{idx} (sequenceDiagram): no interaction arrow found "
                "(->> or equivalent required)."
            )

    return issues


def _validate_mapping_tables(content: str) -> list[str]:
    """
    Validate that at least one complete data mapping table exists and is populated.

    A data mapping table must have:
      - A header row with source/target/field/transformation keywords
      - At least one data row with non-empty, non-n/a cell values

    Fenced code blocks are stripped first to prevent | chars inside Mermaid
    diagrams being misidentified as table rows.

    Returns list of issue strings (empty = table is valid).
    """
    # Strip fenced code blocks to avoid false positives from | inside Mermaid
    stripped = re.sub(r"```[\s\S]*?```", "", content)
    tables = _TABLE_BLOCK_RE.findall(stripped)

    if not tables:
        return [
            "No complete Markdown pipe table found "
            "(header + separator row + at least one data row required)."
        ]

    mapping_found = False
    issues: list[str] = []

    for table_text in tables:
        lines = [ln for ln in table_text.splitlines() if ln.strip().startswith("|")]
        # Find separator row index
        sep_idx = next(
            (i for i, ln in enumerate(lines) if re.match(r"^\|[\s\-|:]+\|", ln.strip())),
            None,
        )
        if sep_idx is None:
            continue

        header_text = " ".join(lines[:sep_idx])
        if not _MAPPING_HEADER_RE.search(header_text):
            continue  # not a mapping table — skip, no issue raised for non-mapping tables

        mapping_found = True
        data_rows = lines[sep_idx + 1:]
        _EMPTY_CELL = re.compile(r"^(?:n/?a|-+|—+|)$", re.IGNORECASE)

        has_real_data = any(
            any(not _EMPTY_CELL.match(cell.strip()) for cell in row.split("|") if cell.strip())
            for row in data_rows
        )
        if not has_real_data:
            issues.append(
                "Data mapping table found but all data rows are empty or n/a — "
                "populate source, target, and transformation values."
            )
        break  # only the first mapping table is validated

    if not mapping_found:
        issues.append(
            "No data mapping table found — table header must include "
            "source/target/field/transformation column keywords."
        )

    return issues


def _validate_section_artifacts(content: str) -> list[str]:
    """
    Verify that key template sections contain their required artifact types.

    Sections checked (from _SECTION_ARTIFACT_RULES):
      - "High-Level Architecture" → must contain a Mermaid flowchart/graph
      - "Detailed Flow"           → must contain a Mermaid sequenceDiagram
      - "Data Mapping"            → must contain a pipe table

    Sections absent from the document are skipped (Signal 1 handles that).

    Returns list of issue strings (empty = all required artifacts present).
    """
    # Split document into sections using lookahead so ## stays at chunk start
    parts = re.split(r"(?=^## )", content, flags=re.MULTILINE)
    sections: dict[str, str] = {}
    for part in parts:
        if part.strip().startswith("## "):
            title = part.split("\n", 1)[0].strip().lower()
            sections[title] = part

    issues: list[str] = []
    for section_keyword, artifact_label, check_fn in _SECTION_ARTIFACT_RULES:
        # Find the first section whose title contains the keyword
        body = next(
            (body for title, body in sections.items() if section_keyword in title),
            None,
        )
        if body is None:
            continue  # absent section — handled by section_count signal
        if not check_fn(body):
            issues.append(
                f"Section '{section_keyword}' is missing required {artifact_label}."
            )

    return issues


def assess_quality(content: str) -> QualityReport:
    """
    Assess LLM output quality without modifying content.

    Volume signals (6 — affect quality_score):
      1. section_count      — number of ## level-2 headings (min: _MIN_SECTION_COUNT)
      2. na_ratio           — fraction of n/a vs section_count (max: _MAX_NA_RATIO)
      3. word_count         — total word count (min: _MIN_WORD_COUNT)
      4. has_mermaid_diagram — at least one ```mermaid block required
      5. mapping_table_count — at least _MIN_MAPPING_TABLES pipe tables required
      6. placeholder_count  — zero [TODO]/[TBD]/[PLACEHOLDER] markers allowed

    Structural validators (3 — affect passed/issues but NOT quality_score):
      7. _validate_mermaid_blocks()    — diagram type, stub nodes, arrows/interactions
      8. _validate_mapping_tables()    — mapping table header keywords + populated data rows
      9. _validate_section_artifacts() — required artifacts present in correct sections

    Call AFTER sanitize_llm_output() — content is already stripped of HTML.
    Returns a QualityReport with .passed and .issues (always list[str], never None).
    """
    issues: list[str] = []

    # ── Signal 1: section count ────────────────────────────────────────────────
    section_count = len(re.findall(r"^## ", content, re.MULTILINE))
    if section_count < _MIN_SECTION_COUNT:
        issues.append(
            f"Too few sections: {section_count} (expected >= {_MIN_SECTION_COUNT})."
        )

    # ── Signal 2: n/a ratio ────────────────────────────────────────────────────
    na_count = len(re.findall(r"\bn/a\b", content, re.IGNORECASE))
    na_ratio = (na_count / section_count) if section_count > 0 else 1.0
    if na_ratio > _MAX_NA_RATIO:
        issues.append(
            f"High n/a ratio: {na_ratio:.0%} of sections lack real content "
            f"(max allowed: {_MAX_NA_RATIO:.0%})."
        )

    # ── Signal 3: word count ───────────────────────────────────────────────────
    word_count = len(content.split())
    if word_count < _MIN_WORD_COUNT:
        issues.append(
            f"Document too short: {word_count} words (expected >= {_MIN_WORD_COUNT})."
        )

    # ── Signal 4: Mermaid diagram ──────────────────────────────────────────────
    has_mermaid_diagram = bool(_MERMAID_RE.search(content))
    if not has_mermaid_diagram:
        issues.append("Missing Mermaid diagram — at least one ```mermaid block required.")

    # ── Signal 5: mapping/data tables ─────────────────────────────────────────
    mapping_table_count = len(_TABLE_SEP_RE.findall(content))
    if mapping_table_count < _MIN_MAPPING_TABLES:
        issues.append(
            f"No data mapping table found — at least {_MIN_MAPPING_TABLES} Markdown "
            "pipe table(s) required."
        )

    # ── Signal 6: placeholder markers ─────────────────────────────────────────
    placeholder_count = len(_PLACEHOLDER_RE.findall(content))
    if placeholder_count > 0:
        issues.append(
            f"Document contains {placeholder_count} unfilled placeholder(s) "
            "([TODO]/[TBD]/[PLACEHOLDER]/TODO: etc.)."
        )

    # ── Composite score (volume signals only) ─────────────────────────────────
    section_score     = min(1.0, section_count / _MIN_SECTION_COUNT)
    na_score          = max(0.0, 1.0 - na_ratio / _MAX_NA_RATIO) if _MAX_NA_RATIO > 0 else 0.0
    word_score        = min(1.0, word_count / _MIN_WORD_COUNT)
    diagram_score     = 1.0 if has_mermaid_diagram else 0.0
    table_score       = min(1.0, mapping_table_count / _MIN_MAPPING_TABLES)
    placeholder_score = 1.0 if placeholder_count == 0 else max(0.0, 1.0 - placeholder_count * 0.25)
    quality_score = round(
        (section_score + na_score + word_score + diagram_score + table_score + placeholder_score) / 6,
        2,
    )

    # ── Structural validation (Point 2 — do NOT affect quality_score) ─────────
    mermaid_syntax_issues   = _validate_mermaid_blocks(content)
    table_structure_issues  = _validate_mapping_tables(content)
    section_artifact_issues = _validate_section_artifacts(content)

    issues.extend(mermaid_syntax_issues)
    issues.extend(table_structure_issues)
    issues.extend(section_artifact_issues)

    return QualityReport(
        section_count=section_count,
        na_ratio=round(na_ratio, 2),
        word_count=word_count,
        has_mermaid_diagram=has_mermaid_diagram,
        mapping_table_count=mapping_table_count,
        placeholder_count=placeholder_count,
        quality_score=quality_score,
        passed=len(issues) == 0,
        issues=issues,
        mermaid_syntax_issues=mermaid_syntax_issues,
        table_structure_issues=table_structure_issues,
        section_artifact_issues=section_artifact_issues,
    )


def enforce_quality_gate(
    report: QualityReport,
    min_score: float = _QUALITY_GATE_MIN_SCORE,
    mode: str = "warn",
) -> None:
    """
    Enforce quality gate before HITL dispatch.

    Args:
        report:    QualityReport from assess_quality().
        min_score: Minimum composite score required to pass (default 0.60).
        mode:      "block" → raises QualityGateError on failure.
                   "warn"  → logs warning, allows document through (default).

    Raises:
        QualityGateError: only when mode="block" and quality is insufficient.
    """
    failed = not report.passed or report.quality_score < min_score
    if not failed:
        return

    issue_summary = "; ".join(report.issues) if report.issues else "score below threshold"
    msg = (
        f"Quality gate failed — score={report.quality_score:.2f} "
        f"(min={min_score:.2f}): {issue_summary}"
    )
    if mode == "block":
        raise QualityGateError(msg)
    else:
        logger.warning("[QualityGate] %s (mode=warn — document forwarded to HITL)", msg)


# ── Internal ───────────────────────────────────────────────────────────────────

def _apply_bleach_and_truncate(text: str) -> str:
    if len(text) > _MAX_CHARS:
        logger.warning(
            "[OutputGuard] Content truncated from %d to %d chars.", len(text), _MAX_CHARS
        )
        text = text[:_MAX_CHARS]

    return bleach.clean(
        text,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRS,
        strip=True,        # strip disallowed tags rather than escaping them
    )
