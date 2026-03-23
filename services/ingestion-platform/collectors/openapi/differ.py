"""
OpenAPI Collector — Differ

Computes content hash for change detection and classifies diff severity.
Hash is SHA-256 of canonical JSON (sorted keys, operation IDs extracted).

Change classification rules (from v3 architecture doc):
  - Endpoint removed → breaking
  - New endpoint added → minor
  - No changes → None severity
"""
import hashlib
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head"}


class OpenAPIDiffer:
    """
    Detects changes between two versions of an OpenAPI spec.
    Uses content hash for fast equality check.
    Uses operation_id set comparison for semantic diff classification.
    """

    def compute_hash(self, spec: dict[str, Any]) -> str:
        """
        Compute SHA-256 of the canonical (sorted-keys) JSON representation.
        Returns 64-char hex string.
        """
        canonical = json.dumps(spec, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def has_changed(self, hash_old: str, hash_new: str) -> bool:
        return hash_old != hash_new

    def extract_operation_ids(self, spec: dict[str, Any]) -> set[str]:
        """Extract all operationId values from a spec's paths."""
        ops: set[str] = set()
        for path, path_item in spec.get("paths", {}).items():
            if not isinstance(path_item, dict):
                continue
            for method, operation in path_item.items():
                if method.lower() not in HTTP_METHODS:
                    continue
                if not isinstance(operation, dict):
                    continue
                op_id = operation.get("operationId")
                if op_id:
                    ops.add(op_id)
                else:
                    ops.add(f"{method.upper()}_{path}")
        return ops

    def classify_changes(
        self,
        old_ops: set[str],
        new_ops: set[str],
    ) -> dict[str, Any]:
        """
        Compare two operation ID sets and classify the change severity.

        Returns:
            dict with keys: severity (None | "minor" | "breaking"), added (set), removed (set)
        """
        added = new_ops - old_ops
        removed = old_ops - new_ops

        if removed:
            severity = "breaking"
        elif added:
            severity = "minor"
        else:
            severity = None

        return {
            "severity": severity,
            "added": added,
            "removed": removed,
        }
