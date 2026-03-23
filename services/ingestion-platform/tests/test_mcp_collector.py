"""
TDD — MCP Collector Unit Tests (RED phase)

Tests MCP inspector → normalizer pipeline.
MCP SDK client is mocked — no real MCP server required.
"""
import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch


# ── Fixtures — simulated MCP SDK responses ───────────────────────────────────

def _make_tool(name: str, description: str, input_schema: dict | None = None):
    """Minimal MCP Tool-like object."""
    tool = MagicMock()
    tool.name = name
    tool.description = description
    tool.inputSchema = input_schema or {"type": "object", "properties": {}}
    return tool


def _make_resource(uri: str, name: str, description: str):
    resource = MagicMock()
    resource.uri = uri
    resource.name = name
    resource.description = description
    return resource


def _make_prompt(name: str, description: str):
    prompt = MagicMock()
    prompt.name = name
    prompt.description = description
    return prompt


JIRA_TOOLS = [
    _make_tool("create_issue", "Create a new Jira issue", {
        "type": "object",
        "required": ["project", "summary"],
        "properties": {
            "project": {"type": "string"},
            "summary": {"type": "string"},
            "description": {"type": "string"},
        }
    }),
    _make_tool("get_issue", "Get a Jira issue by key", {
        "type": "object",
        "required": ["issue_key"],
        "properties": {"issue_key": {"type": "string"}},
    }),
    _make_tool("list_issues", "List issues in a project", {
        "type": "object",
        "properties": {"project": {"type": "string"}, "status": {"type": "string"}},
    }),
]

JIRA_RESOURCES = [
    _make_resource("jira://projects", "Projects", "All available Jira projects"),
    _make_resource("jira://boards", "Boards", "All active sprint boards"),
]

JIRA_PROMPTS = [
    _make_prompt("create_sprint_report", "Generate a sprint report for a project"),
]


# ── MCP Normalizer tests ──────────────────────────────────────────────────────

class TestMCPNormalizer:
    def test_tools_produce_tool_capabilities(self):
        from collectors.mcp.normalizer import MCPNormalizer
        norm = MCPNormalizer()
        caps = norm.normalize_tools(JIRA_TOOLS, source_code="jira_mcp")
        assert len(caps) == 3
        assert all(c.kind.value == "tool" for c in caps)

    def test_tool_capability_has_source_trace(self):
        from collectors.mcp.normalizer import MCPNormalizer
        norm = MCPNormalizer()
        caps = norm.normalize_tools(JIRA_TOOLS, source_code="jira_mcp")
        for cap in caps:
            assert cap.source_trace.origin_type == "mcp"
            assert "tools." in cap.source_trace.origin_pointer

    def test_tool_names_preserved(self):
        from collectors.mcp.normalizer import MCPNormalizer
        norm = MCPNormalizer()
        caps = norm.normalize_tools(JIRA_TOOLS, source_code="jira_mcp")
        names = {c.name for c in caps}
        assert names == {"create_issue", "get_issue", "list_issues"}

    def test_resources_produce_resource_capabilities(self):
        from collectors.mcp.normalizer import MCPNormalizer
        norm = MCPNormalizer()
        caps = norm.normalize_resources(JIRA_RESOURCES, source_code="jira_mcp")
        assert len(caps) == 2
        assert all(c.kind.value == "resource" for c in caps)

    def test_resources_uri_in_source_trace(self):
        from collectors.mcp.normalizer import MCPNormalizer
        norm = MCPNormalizer()
        caps = norm.normalize_resources(JIRA_RESOURCES, source_code="jira_mcp")
        pointers = {c.source_trace.origin_pointer for c in caps}
        assert "resources.jira://projects" in pointers

    def test_prompts_produce_guide_step_capabilities(self):
        from collectors.mcp.normalizer import MCPNormalizer
        norm = MCPNormalizer()
        caps = norm.normalize_prompts(JIRA_PROMPTS, source_code="jira_mcp")
        assert len(caps) == 1
        assert caps[0].kind.value == "guide_step"

    def test_normalize_all_combines_all_types(self):
        from collectors.mcp.normalizer import MCPNormalizer
        norm = MCPNormalizer()
        caps = norm.normalize_all(
            tools=JIRA_TOOLS,
            resources=JIRA_RESOURCES,
            prompts=JIRA_PROMPTS,
            source_code="jira_mcp",
        )
        kinds = {c.kind.value for c in caps}
        assert "tool" in kinds
        assert "resource" in kinds
        assert "guide_step" in kinds

    def test_capability_ids_unique(self):
        from collectors.mcp.normalizer import MCPNormalizer
        norm = MCPNormalizer()
        caps = norm.normalize_all(
            tools=JIRA_TOOLS,
            resources=JIRA_RESOURCES,
            prompts=JIRA_PROMPTS,
            source_code="jira_mcp",
        )
        ids = [c.capability_id for c in caps]
        assert len(ids) == len(set(ids))

    def test_tool_input_schema_in_description(self):
        from collectors.mcp.normalizer import MCPNormalizer
        norm = MCPNormalizer()
        caps = norm.normalize_tools(JIRA_TOOLS[:1], source_code="jira_mcp")
        create_issue = caps[0]
        # Required fields should be mentioned in description
        assert "project" in create_issue.description or "summary" in create_issue.description

    def test_empty_tools_returns_empty_list(self):
        from collectors.mcp.normalizer import MCPNormalizer
        norm = MCPNormalizer()
        caps = norm.normalize_tools([], source_code="jira_mcp")
        assert caps == []


# ── MCP Chunker tests (via normalizer output) ─────────────────────────────────

class TestMCPChunking:
    def test_tool_chunks_have_mcp_source_type(self):
        from collectors.mcp.normalizer import MCPNormalizer
        from collectors.openapi.chunker import OpenAPIChunker
        from models.capability import CanonicalChunk
        norm = MCPNormalizer()
        caps = norm.normalize_tools(JIRA_TOOLS, source_code="jira_mcp")
        # Use the generic chunking pattern: one chunk per capability
        chunks = [
            CanonicalChunk(
                text=cap.description,
                index=i,
                source_code=cap.source_code,
                source_type="mcp",
                capability_kind=cap.kind.value,
                section_header=cap.name,
                tags=["jira"],
            )
            for i, cap in enumerate(caps)
        ]
        assert all(c.source_type == "mcp" for c in chunks)
        assert all(c.capability_kind == "tool" for c in chunks)

    def test_chunk_ids_follow_src_convention(self):
        from models.capability import CanonicalChunk
        chunk = CanonicalChunk(
            text="Tool: create_issue",
            index=0,
            source_code="jira_mcp",
            source_type="mcp",
            capability_kind="tool",
        )
        assert chunk.chunk_id() == "src_jira_mcp-chunk-0"


# ── MCPClient (async, mocked) ─────────────────────────────────────────────────

class TestMCPInspector:
    def test_inspector_returns_structured_result(self):
        from collectors.mcp.inspector import MCPInspectionResult
        result = MCPInspectionResult(
            tools=JIRA_TOOLS,
            resources=JIRA_RESOURCES,
            prompts=JIRA_PROMPTS,
        )
        assert len(result.tools) == 3
        assert len(result.resources) == 2
        assert len(result.prompts) == 1

    def test_inspection_result_total_count(self):
        from collectors.mcp.inspector import MCPInspectionResult
        result = MCPInspectionResult(tools=JIRA_TOOLS, resources=[], prompts=[])
        assert result.total_count == 3

    def test_inspection_result_empty(self):
        from collectors.mcp.inspector import MCPInspectionResult
        result = MCPInspectionResult(tools=[], resources=[], prompts=[])
        assert result.total_count == 0
