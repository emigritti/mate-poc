"""
MCP Collector — Inspector

Connects to an MCP server and retrieves its capabilities (tools, resources, prompts).
Uses the Python MCP SDK (mcp package) with SSE transport for HTTP servers.

Lazy-imports mcp to allow the service to start even if the mcp package is not installed.
Graceful degradation: returns empty MCPInspectionResult on any connection error.
"""
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class MCPInspectionResult:
    """Structured result from inspecting an MCP server."""
    tools: list[Any] = field(default_factory=list)
    resources: list[Any] = field(default_factory=list)
    prompts: list[Any] = field(default_factory=list)

    @property
    def total_count(self) -> int:
        return len(self.tools) + len(self.resources) + len(self.prompts)


class MCPInspector:
    """
    Connects to an MCP server via SSE (HTTP) or stdio transport.
    Retrieves all exposed tools, resources, and prompts.
    """

    async def inspect(self, server_url: str, timeout_seconds: int = 30) -> MCPInspectionResult:
        """
        Connect to MCP server and retrieve all capabilities.

        Args:
            server_url: MCP server SSE endpoint URL (e.g. http://mcp-server/sse)
            timeout_seconds: Connection + listing timeout.

        Returns:
            MCPInspectionResult — empty on error (graceful degradation).
        """
        try:
            return await self._inspect_via_sse(server_url, timeout_seconds)
        except Exception as exc:
            logger.warning("MCP inspection failed for %s: %s", server_url, exc)
            return MCPInspectionResult()

    async def _inspect_via_sse(self, server_url: str, timeout_seconds: int) -> MCPInspectionResult:
        try:
            from mcp import ClientSession
            from mcp.client.sse import sse_client
        except ImportError:
            logger.error("mcp package not installed. Run: pip install mcp")
            return MCPInspectionResult()

        tools_list: list[Any] = []
        resources_list: list[Any] = []
        prompts_list: list[Any] = []

        async with sse_client(server_url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                try:
                    tools_result = await session.list_tools()
                    tools_list = list(tools_result.tools)
                    logger.info("MCP %s — found %d tools", server_url, len(tools_list))
                except Exception as exc:
                    logger.warning("list_tools failed: %s", exc)

                try:
                    resources_result = await session.list_resources()
                    resources_list = list(resources_result.resources)
                    logger.info("MCP %s — found %d resources", server_url, len(resources_list))
                except Exception as exc:
                    logger.warning("list_resources failed: %s", exc)

                try:
                    prompts_result = await session.list_prompts()
                    prompts_list = list(prompts_result.prompts)
                    logger.info("MCP %s — found %d prompts", server_url, len(prompts_list))
                except Exception as exc:
                    logger.warning("list_prompts failed: %s", exc)

        return MCPInspectionResult(
            tools=tools_list,
            resources=resources_list,
            prompts=prompts_list,
        )
