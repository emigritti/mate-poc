---
source: ERP
target: Salsify
---

# ERP → Salsify Integration Requirements

## Mandatory Requirements

- REQ-M01 | Product Collection | Sync daily created articles from ERP to PLM, initializing basic technical attributes (SKU, Name, Factory Cost).
- REQ-M02 | Image Collection | Automatically link high-res images uploaded to DAM with the corresponding Salsify SKU based on filename regex.
- REQ-M03 | Publish Workflow | Implement Maker-Checker rule: Editor modifies data, Approver must review and Approve to transition status to Published.

## Non-Mandatory Requirements

- REQ-O01 | Enrichment INIT | When a product is marked Ready for Enrichment in Salsify, create a shell product with tech specs locked.
- REQ-O02 | Assortment Management | Support dynamic categorization into Seasonal Collections based on launch date and pricing tier rules.
- REQ-O03 | Reporting | Generate a weekly synchronization status report showing success rate, error count, and pending items.
