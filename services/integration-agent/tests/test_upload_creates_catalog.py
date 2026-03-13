"""Tests that upload creates CatalogEntries with PENDING_TAG_REVIEW status."""
import io
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


CSV_CONTENT = (
    "ReqID,Source,Target,Category,Description\n"
    "REQ-101,ERP,PLM,Product Collection,Sync articles from ERP to PLM.\n"
    "REQ-102,PLM,PIM,Enrichment INIT,Create shell product in PIM.\n"
    "REQ-103,DAM,PIM,Image Collection,Link images to PIM SKU.\n"
)


def test_upload_creates_catalog_entries(client):
    import main
    main.catalog.clear()
    main.parsed_requirements.clear()

    resp = client.post(
        "/api/v1/requirements/upload",
        files={"file": ("reqs.csv", io.BytesIO(CSV_CONTENT.encode()), "text/csv")},
    )
    assert resp.status_code == 200

    # ERP→PLM (REQ-101), PLM→PIM (REQ-102), DAM→PIM (REQ-103) = 3 unique pairs
    assert len(main.catalog) == 3
    # All entries should be PENDING_TAG_REVIEW
    for entry in main.catalog.values():
        assert entry.status == "PENDING_TAG_REVIEW"


def test_upload_catalog_entry_count(client):
    """3 requirements across 3 unique source→target pairs = 3 entries."""
    import main
    main.catalog.clear()
    main.parsed_requirements.clear()

    resp = client.post(
        "/api/v1/requirements/upload",
        files={"file": ("reqs.csv", io.BytesIO(CSV_CONTENT.encode()), "text/csv")},
    )
    assert resp.status_code == 200
    # ERP→PLM (REQ-101), PLM→PIM (REQ-102), DAM→PIM (REQ-103) = 3 groups
    assert len(main.catalog) == 3
