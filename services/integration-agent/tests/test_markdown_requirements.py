"""
Unit tests — Markdown requirements parsing (routers/requirements.py).
CLAUDE.md §7: Business logic, edge cases, validation.

Coverage:
  _parse_markdown():
  - Valid frontmatter → correct source/target
  - Mandatory section heading → mandatory=True
  - Non-mandatory / Optional heading → mandatory=False
  - Mixed sections → correct mandatory flags per item
  - Bullet formats: 3-part (REQ-ID|Cat|Desc), 2-part (Cat|Desc), 1-part (Desc)
  - No frontmatter → fallback filename parsing ("erp-to-salsify.md")
  - No frontmatter, unparseable filename → source/target = "Unknown"
  - Empty body → empty list
  - Skips non-bullet lines in sections

  _parse_csv():
  - Mandatory column "true" / "yes" / "1" → mandatory=True
  - Absent Mandatory column → mandatory=False (default)

  Upload endpoint:
  - .md file accepted (200)
  - .md with text/plain MIME accepted (200)
  - Parsed mandatory flags visible via GET /requirements
"""

import io
import pytest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

# ── Parser unit tests (no HTTP) ───────────────────────────────────────────────

from routers.requirements import _parse_markdown, _parse_csv


_SAMPLE_MD = """\
---
source: ERP
target: Salsify
---

## Mandatory Requirements

- REQ-M01 | Product Collection | Sync daily articles from ERP

## Non-Mandatory Requirements

- REQ-O01 | Reporting | Generate weekly report
"""

_SAMPLE_MD_OPTIONAL_HEADING = """\
---
source: PLM
target: DAM
---

## Mandatory

- REQ-M01 | Sync | Transfer product data

## Optional

- REQ-O01 | Archive | Archive old assets
"""


class TestParseMarkdownFrontmatter:
    def test_extracts_source_from_frontmatter(self):
        reqs = _parse_markdown(_SAMPLE_MD)
        assert all(r.source_system == "ERP" for r in reqs)

    def test_extracts_target_from_frontmatter(self):
        reqs = _parse_markdown(_SAMPLE_MD)
        assert all(r.target_system == "Salsify" for r in reqs)

    def test_fallback_filename_dash_to(self):
        md = "## Mandatory\n- REQ-1 | Cat | Desc\n"
        reqs = _parse_markdown(md, filename="erp-to-salsify.md")
        assert reqs[0].source_system == "erp"
        assert reqs[0].target_system == "salsify"

    def test_fallback_filename_arrow(self):
        md = "## Mandatory\n- REQ-1 | Cat | Desc\n"
        reqs = _parse_markdown(md, filename="plm→dam.md")
        assert reqs[0].source_system == "plm"
        assert reqs[0].target_system == "dam"

    def test_fallback_unknown_when_no_separator(self):
        md = "## Mandatory\n- REQ-1 | Cat | Desc\n"
        reqs = _parse_markdown(md, filename="requirements.md")
        assert reqs[0].source_system == "Unknown"
        assert reqs[0].target_system == "Unknown"


class TestParseMarkdownMandatory:
    def test_mandatory_section_sets_flag_true(self):
        reqs = _parse_markdown(_SAMPLE_MD)
        mandatory_reqs = [r for r in reqs if r.req_id == "REQ-M01"]
        assert len(mandatory_reqs) == 1
        assert mandatory_reqs[0].mandatory is True

    def test_non_mandatory_section_sets_flag_false(self):
        reqs = _parse_markdown(_SAMPLE_MD)
        optional_reqs = [r for r in reqs if r.req_id == "REQ-O01"]
        assert len(optional_reqs) == 1
        assert optional_reqs[0].mandatory is False

    def test_optional_heading_sets_mandatory_false(self):
        reqs = _parse_markdown(_SAMPLE_MD_OPTIONAL_HEADING)
        optional_reqs = [r for r in reqs if r.req_id == "REQ-O01"]
        assert optional_reqs[0].mandatory is False

    def test_mandatory_heading_without_non_prefix_sets_true(self):
        reqs = _parse_markdown(_SAMPLE_MD_OPTIONAL_HEADING)
        mandatory_reqs = [r for r in reqs if r.req_id == "REQ-M01"]
        assert mandatory_reqs[0].mandatory is True

    def test_mixed_sections_correct_count(self):
        reqs = _parse_markdown(_SAMPLE_MD)
        assert sum(1 for r in reqs if r.mandatory) == 1
        assert sum(1 for r in reqs if not r.mandatory) == 1


class TestParseMarkdownBulletFormats:
    def test_three_part_bullet_uses_explicit_req_id(self):
        md = "---\nsource: A\ntarget: B\n---\n## Mandatory\n- REQ-X01 | Category | Some description\n"
        reqs = _parse_markdown(md)
        assert reqs[0].req_id == "REQ-X01"
        assert reqs[0].category == "Category"
        assert reqs[0].description == "Some description"

    def test_two_part_bullet_auto_generates_req_id(self):
        md = "---\nsource: A\ntarget: B\n---\n## Mandatory\n- Sync | Transfer product data\n"
        reqs = _parse_markdown(md)
        assert reqs[0].req_id.startswith("R-")
        assert reqs[0].category == "Sync"
        assert reqs[0].description == "Transfer product data"

    def test_one_part_bullet_sets_general_category(self):
        md = "---\nsource: A\ntarget: B\n---\n## Mandatory\n- Just a plain description\n"
        reqs = _parse_markdown(md)
        assert reqs[0].req_id.startswith("R-")
        assert reqs[0].category == "General"
        assert reqs[0].description == "Just a plain description"

    def test_non_bullet_lines_ignored(self):
        md = "---\nsource: A\ntarget: B\n---\n## Mandatory\nSome prose text.\nMore prose.\n- REQ-1 | Cat | Desc\n"
        reqs = _parse_markdown(md)
        assert len(reqs) == 1

    def test_empty_markdown_returns_empty_list(self):
        reqs = _parse_markdown("---\nsource: A\ntarget: B\n---\n")
        assert reqs == []


class TestParseCsvMandatoryColumn:
    def test_mandatory_true_string(self):
        csv_text = "ReqID,Source,Target,Category,Description,Mandatory\nR-1,ERP,Salsify,Sync,Desc,true\n"
        reqs = _parse_csv(csv_text)
        assert reqs[0].mandatory is True

    def test_mandatory_yes_string(self):
        csv_text = "ReqID,Source,Target,Category,Description,Mandatory\nR-1,ERP,Salsify,Sync,Desc,yes\n"
        reqs = _parse_csv(csv_text)
        assert reqs[0].mandatory is True

    def test_mandatory_1_string(self):
        csv_text = "ReqID,Source,Target,Category,Description,Mandatory\nR-1,ERP,Salsify,Sync,Desc,1\n"
        reqs = _parse_csv(csv_text)
        assert reqs[0].mandatory is True

    def test_mandatory_false_when_column_absent(self):
        csv_text = "ReqID,Source,Target,Category,Description\nR-1,ERP,Salsify,Sync,Desc\n"
        reqs = _parse_csv(csv_text)
        assert reqs[0].mandatory is False

    def test_mandatory_false_for_empty_value(self):
        csv_text = "ReqID,Source,Target,Category,Description,Mandatory\nR-1,ERP,Salsify,Sync,Desc,\n"
        reqs = _parse_csv(csv_text)
        assert reqs[0].mandatory is False


# ── Upload endpoint tests ─────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    with (
        patch("db.init_db",          new_callable=AsyncMock),
        patch("db.close_db",         new_callable=AsyncMock),
        patch("main._init_chromadb", new_callable=AsyncMock),
    ):
        from main import app
        with TestClient(app) as c:
            yield c


_SAMPLE_MD_BYTES = _SAMPLE_MD.encode("utf-8")


class TestUploadMarkdown:
    def test_md_file_returns_200(self, client):
        res = client.post(
            "/api/v1/requirements/upload",
            files={"file": ("reqs.md", io.BytesIO(_SAMPLE_MD_BYTES), "text/markdown")},
        )
        assert res.status_code == 200

    def test_md_file_parsed_count(self, client):
        res = client.post(
            "/api/v1/requirements/upload",
            files={"file": ("reqs.md", io.BytesIO(_SAMPLE_MD_BYTES), "text/markdown")},
        )
        assert res.json()["total_parsed"] == 2

    def test_md_file_with_plain_mime_accepted(self, client):
        # Browsers may send text/plain for .md — filename extension takes precedence
        res = client.post(
            "/api/v1/requirements/upload",
            files={"file": ("reqs.md", io.BytesIO(_SAMPLE_MD_BYTES), "text/plain")},
        )
        assert res.status_code == 200

    def test_md_preview_contains_one_pair(self, client):
        res = client.post(
            "/api/v1/requirements/upload",
            files={"file": ("reqs.md", io.BytesIO(_SAMPLE_MD_BYTES), "text/markdown")},
        )
        preview = res.json()["preview"]
        assert len(preview) == 1
        assert preview[0]["source"] == "ERP"
        assert preview[0]["target"] == "Salsify"

    def test_mandatory_flags_visible_in_get(self, client):
        client.post(
            "/api/v1/requirements/upload",
            files={"file": ("reqs.md", io.BytesIO(_SAMPLE_MD_BYTES), "text/markdown")},
        )
        reqs = client.get("/api/v1/requirements").json()["data"]
        mandatory_flags = {r["req_id"]: r["mandatory"] for r in reqs}
        assert mandatory_flags.get("REQ-M01") is True
        assert mandatory_flags.get("REQ-O01") is False

    def test_unsupported_file_type_still_rejected(self, client):
        res = client.post(
            "/api/v1/requirements/upload",
            files={"file": ("data.bin", io.BytesIO(b"\x00\x01"), "application/octet-stream")},
        )
        assert res.status_code == 415
