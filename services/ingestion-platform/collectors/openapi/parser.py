"""
OpenAPI Collector — Parser

Detects and parses OpenAPI 3.x / Swagger 2.0 specs from raw string.
Supports JSON and YAML formats. Validates presence of required fields.
"""
import json
import logging
from typing import Any

import yaml

logger = logging.getLogger(__name__)


class OpenAPIParseError(Exception):
    """Raised when the spec cannot be parsed or is missing required fields."""


class OpenAPIParser:
    """
    Parses raw OpenAPI/Swagger spec string into a Python dict.
    Detects format (JSON/YAML) automatically.
    Validates that 'paths' key is present (minimum viable spec).
    """

    def parse(self, raw: str) -> dict[str, Any]:
        """
        Parse raw spec string.

        Args:
            raw: Raw spec content (JSON or YAML string).

        Returns:
            Parsed spec as dict.

        Raises:
            OpenAPIParseError: If parsing fails or spec is structurally invalid.
        """
        spec = self._decode(raw)
        self._validate(spec)
        return spec

    def _decode(self, raw: str) -> dict[str, Any]:
        # Try JSON first (faster and more common)
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            pass
        # Fallback to YAML
        try:
            parsed = yaml.safe_load(raw)
            if not isinstance(parsed, dict):
                raise OpenAPIParseError("Parsed YAML is not a dictionary")
            return parsed
        except yaml.YAMLError as exc:
            raise OpenAPIParseError(f"Failed to parse spec as JSON or YAML: {exc}") from exc

    def _validate(self, spec: dict[str, Any]) -> None:
        if "paths" not in spec:
            raise OpenAPIParseError(
                "Spec is missing required 'paths' field. "
                "Ensure it is a valid OpenAPI 3.x or Swagger 2.0 document."
            )
        is_openapi3 = "openapi" in spec
        is_swagger2 = "swagger" in spec
        if not (is_openapi3 or is_swagger2):
            logger.warning("Spec missing 'openapi' or 'swagger' version field; proceeding anyway")
