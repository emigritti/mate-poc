"""
OpenAPI Collector — Normalizer

Transforms a parsed OpenAPI/Swagger spec dict into a list of CanonicalCapability objects.
Maps HTTP operations → ENDPOINT, component schemas → SCHEMA.
"""
import logging
from typing import Any

from models.capability import CanonicalCapability, CapabilityKind, SourceTrace

logger = logging.getLogger(__name__)

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head"}


class OpenAPINormalizer:
    """
    Converts parsed OpenAPI spec to CanonicalCapability list.
    Handles both OpenAPI 3.x and Swagger 2.0 structures.
    """

    def normalize(self, spec: dict[str, Any], source_code: str) -> list[CanonicalCapability]:
        capabilities: list[CanonicalCapability] = []
        overview = self._extract_overview(spec, source_code)
        if overview:
            capabilities.append(overview)
        capabilities.extend(self._extract_endpoints(spec, source_code))
        capabilities.extend(self._extract_schemas(spec, source_code))
        return capabilities

    def _extract_overview(self, spec: dict, source_code: str) -> CanonicalCapability | None:
        info = spec.get("info", {})
        title = info.get("title", "")
        description = info.get("description", "")
        version = info.get("version", "")
        servers = [s.get("url", "") for s in spec.get("servers", [])]
        if not title:
            return None
        text_parts = [f"API: {title}"]
        if version:
            text_parts.append(f"Version: {version}")
        if description:
            text_parts.append(description)
        if servers:
            text_parts.append(f"Servers: {', '.join(servers)}")
        return CanonicalCapability(
            capability_id=f"{source_code}__overview",
            kind=CapabilityKind.OVERVIEW,
            name=title,
            description="\n".join(text_parts),
            source_code=source_code,
            source_trace=SourceTrace(origin_type="openapi", origin_pointer="info"),
            metadata={"version": version, "servers": servers},
        )

    # ── Endpoint extraction ───────────────────────────────────────────────────

    def _extract_endpoints(self, spec: dict, source_code: str) -> list[CanonicalCapability]:
        result = []
        paths: dict = spec.get("paths", {})
        for path, path_item in paths.items():
            if not isinstance(path_item, dict):
                continue
            for method, operation in path_item.items():
                if method.lower() not in HTTP_METHODS:
                    continue
                if not isinstance(operation, dict):
                    continue
                cap = self._operation_to_capability(
                    path=path,
                    method=method.upper(),
                    operation=operation,
                    source_code=source_code,
                )
                result.append(cap)
        return result

    def _operation_to_capability(
        self,
        path: str,
        method: str,
        operation: dict,
        source_code: str,
    ) -> CanonicalCapability:
        op_id = operation.get("operationId") or f"{method}_{path.replace('/', '_').strip('_')}"
        summary = operation.get("summary", "")
        description = operation.get("description", summary)
        tags = operation.get("tags", [])

        # Build a human-readable description for the chunk
        full_desc = f"{method} {path}"
        if summary:
            full_desc += f" — {summary}"
        if description and description != summary:
            full_desc += f"\n{description}"

        params = operation.get("parameters", [])
        if params:
            param_names = [p.get("name", "?") for p in params if isinstance(p, dict)]
            full_desc += f"\nParameters: {', '.join(param_names)}"

        responses = operation.get("responses", {})
        if responses:
            codes = list(responses.keys())
            full_desc += f"\nResponse codes: {', '.join(str(c) for c in codes)}"

        return CanonicalCapability(
            capability_id=f"{source_code}__endpoint__{op_id}",
            kind=CapabilityKind.ENDPOINT,
            name=op_id,
            description=full_desc,
            source_code=source_code,
            source_trace=SourceTrace(
                origin_type="openapi",
                origin_pointer=f"paths.{path}.{method.lower()}",
            ),
            metadata={"method": method, "path": path, "tags": tags},
        )

    # ── Schema extraction ─────────────────────────────────────────────────────

    def _extract_schemas(self, spec: dict, source_code: str) -> list[CanonicalCapability]:
        result = []
        # OpenAPI 3.x: components.schemas
        schemas = spec.get("components", {}).get("schemas", {})
        # Swagger 2.0: definitions
        if not schemas:
            schemas = spec.get("definitions", {})

        for schema_name, schema_def in schemas.items():
            if not isinstance(schema_def, dict):
                continue
            cap = self._schema_to_capability(schema_name, schema_def, source_code)
            result.append(cap)
        return result

    def _schema_to_capability(
        self,
        name: str,
        schema_def: dict,
        source_code: str,
    ) -> CanonicalCapability:
        props = schema_def.get("properties", {})
        required = schema_def.get("required", [])
        description = f"Schema: {name}"
        if props:
            prop_list = ", ".join(
                f"{k} ({'required' if k in required else 'optional'})"
                for k in props
            )
            description += f"\nFields: {prop_list}"

        return CanonicalCapability(
            capability_id=f"{source_code}__schema__{name}",
            kind=CapabilityKind.SCHEMA,
            name=name,
            description=description,
            source_code=source_code,
            source_trace=SourceTrace(
                origin_type="openapi",
                origin_pointer=f"components.schemas.{name}",
            ),
            metadata={"properties": list(props.keys()), "required": required},
        )
