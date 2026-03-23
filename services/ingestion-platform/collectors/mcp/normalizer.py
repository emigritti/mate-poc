"""
MCP Collector — Normalizer

Converts MCP SDK objects (Tool, Resource, Prompt) into CanonicalCapability objects.

Mapping:
  MCP Tool    → CapabilityKind.TOOL
  MCP Resource → CapabilityKind.RESOURCE
  MCP Prompt  → CapabilityKind.GUIDE_STEP
"""
import json
import logging
from typing import Any

from models.capability import CanonicalCapability, CapabilityKind, SourceTrace

logger = logging.getLogger(__name__)


class MCPNormalizer:
    """
    Converts MCP inspection results to CanonicalCapability objects.
    Works with real mcp SDK objects or duck-typed mocks (for testing).
    """

    def normalize_tools(self, tools: list[Any], source_code: str) -> list[CanonicalCapability]:
        return [self._tool_to_capability(t, source_code) for t in tools]

    def normalize_resources(self, resources: list[Any], source_code: str) -> list[CanonicalCapability]:
        return [self._resource_to_capability(r, source_code) for r in resources]

    def normalize_prompts(self, prompts: list[Any], source_code: str) -> list[CanonicalCapability]:
        return [self._prompt_to_capability(p, source_code) for p in prompts]

    def normalize_all(
        self,
        tools: list[Any],
        resources: list[Any],
        prompts: list[Any],
        source_code: str,
    ) -> list[CanonicalCapability]:
        capabilities: list[CanonicalCapability] = []
        capabilities.extend(self.normalize_tools(tools, source_code))
        capabilities.extend(self.normalize_resources(resources, source_code))
        capabilities.extend(self.normalize_prompts(prompts, source_code))
        return capabilities

    # ── Private ───────────────────────────────────────────────────────────────

    def _tool_to_capability(self, tool: Any, source_code: str) -> CanonicalCapability:
        name = getattr(tool, "name", "unknown_tool")
        description = getattr(tool, "description", "") or ""
        input_schema = getattr(tool, "inputSchema", {}) or {}

        # Enrich description with schema info (parameters → visible in RAG)
        full_desc = f"Tool: {name}"
        if description:
            full_desc += f"\n{description}"

        if isinstance(input_schema, dict):
            props = input_schema.get("properties", {})
            required = input_schema.get("required", [])
            if props:
                param_list = ", ".join(
                    f"{k} ({'required' if k in required else 'optional'})"
                    for k in props
                )
                full_desc += f"\nParameters: {param_list}"

        return CanonicalCapability(
            capability_id=f"{source_code}__tool__{name}",
            kind=CapabilityKind.TOOL,
            name=name,
            description=full_desc,
            source_code=source_code,
            source_trace=SourceTrace(
                origin_type="mcp",
                origin_pointer=f"tools.{name}",
            ),
            metadata={"input_schema": input_schema},
        )

    def _resource_to_capability(self, resource: Any, source_code: str) -> CanonicalCapability:
        uri = str(getattr(resource, "uri", ""))
        name = getattr(resource, "name", uri) or uri
        description = getattr(resource, "description", "") or ""

        full_desc = f"Resource: {name}"
        if uri and uri != name:
            full_desc += f"\nURI: {uri}"
        if description:
            full_desc += f"\n{description}"

        return CanonicalCapability(
            capability_id=f"{source_code}__resource__{uri.replace('://', '_').replace('/', '_')}",
            kind=CapabilityKind.RESOURCE,
            name=name,
            description=full_desc,
            source_code=source_code,
            source_trace=SourceTrace(
                origin_type="mcp",
                origin_pointer=f"resources.{uri}",
            ),
            metadata={"uri": uri},
        )

    def _prompt_to_capability(self, prompt: Any, source_code: str) -> CanonicalCapability:
        name = getattr(prompt, "name", "unknown_prompt")
        description = getattr(prompt, "description", "") or ""

        full_desc = f"Prompt template: {name}"
        if description:
            full_desc += f"\n{description}"

        return CanonicalCapability(
            capability_id=f"{source_code}__prompt__{name}",
            kind=CapabilityKind.GUIDE_STEP,
            name=name,
            description=full_desc,
            source_code=source_code,
            source_trace=SourceTrace(
                origin_type="mcp",
                origin_pointer=f"prompts.{name}",
            ),
        )
