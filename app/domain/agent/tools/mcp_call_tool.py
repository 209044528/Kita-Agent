from __future__ import annotations

from typing import Any

from app.domain.agent.tool import BaseTool, ToolParameter
from app.infrastructure.mcp.client import MCPClientService


class MCPCallTool(BaseTool):
    """Proxy configured MCP client tools through the local ReAct tool registry."""

    def __init__(self, client: MCPClientService):
        self._client = client

    @property
    def name(self) -> str:
        return "mcp_call"

    @property
    def description(self) -> str:
        return "调用已配置的 MCP 服务端工具。适合意图路由命中外部系统能力时使用。"

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="server_name",
                type="string",
                description="MCP 服务名，例如 local、crm、ticket",
                required=True,
            ),
            ToolParameter(
                name="tool_name",
                type="string",
                description="MCP 工具名",
                required=True,
            ),
            ToolParameter(
                name="arguments",
                type="object",
                description="传给 MCP 工具的 JSON 参数",
                required=False,
                default={},
            ),
        ]

    def execute(self, **kwargs: Any) -> str:
        return "错误: mcp_call 是异步工具，请通过 async_execute 调用。"

    async def execute_async(self, run_context: Any = None, **kwargs: Any) -> str:
        server_name = str(kwargs.get("server_name") or "").strip()
        tool_name = str(kwargs.get("tool_name") or "").strip()
        arguments = kwargs.get("arguments") or {}
        if not server_name or not tool_name:
            return "错误: server_name 和 tool_name 不能为空。"
        if not isinstance(arguments, dict):
            return "错误: arguments 必须是 JSON object。"
        try:
            result = await self._client.call_tool(server_name, tool_name, arguments)
            return str(result.get("content") or result)
        except Exception as exc:
            return f"MCP 工具调用错误: {exc}"
