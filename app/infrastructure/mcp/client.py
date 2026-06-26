from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MCPServerConfig:
    name: str
    url: str


class MCPClientService:
    """Small MCP streamable-http client facade."""

    def __init__(self, servers: list[MCPServerConfig]):
        self.servers = {server.name: server for server in servers}

    @classmethod
    def from_config_string(cls, value: str) -> "MCPClientService":
        servers: list[MCPServerConfig] = []
        for item in filter(None, (part.strip() for part in value.split(","))):
            if "=" not in item:
                continue
            name, url = item.split("=", 1)
            servers.append(MCPServerConfig(name=name.strip(), url=url.strip()))
        return cls(servers)

    def list_servers(self) -> list[dict[str, str]]:
        return [{"name": server.name, "url": server.url} for server in self.servers.values()]

    async def list_tools(self, server_name: str) -> list[dict[str, Any]]:
        server = self._server(server_name)
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        async with streamablehttp_client(server.url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                return [
                    {
                        "name": tool.name,
                        "description": tool.description,
                        "inputSchema": tool.inputSchema,
                    }
                    for tool in result.tools
                ]

    async def call_tool(
        self, server_name: str, tool_name: str, arguments: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        server = self._server(server_name)
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        async with streamablehttp_client(server.url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments or {})
                content = [
                    getattr(item, "text", None) if hasattr(item, "text") else str(item)
                    for item in result.content
                ]
                return {"is_error": result.isError, "content": content}

    def _server(self, server_name: str) -> MCPServerConfig:
        server = self.servers.get(server_name)
        if not server:
            raise ValueError(f"MCP server not configured: {server_name}")
        return server
