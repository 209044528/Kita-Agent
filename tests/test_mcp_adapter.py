import unittest

from app.domain.agent.tool import BaseTool, ToolParameter, ToolRegistry
from app.infrastructure.mcp import create_mcp_server


class EchoTool(BaseTool):
    @property
    def name(self):
        return "echo"

    @property
    def description(self):
        return "Echo text"

    @property
    def parameters(self):
        return [ToolParameter(name="text", description="Text to echo")]

    def execute(self, text: str) -> str:
        return text


class MCPAdapterTest(unittest.IsolatedAsyncioTestCase):
    async def test_tool_discovery_and_call(self):
        registry = ToolRegistry()
        registry.register(EchoTool())
        server = create_mcp_server(registry)

        tools = await server.list_tools()
        self.assertEqual(tools[0].name, "echo")
        self.assertEqual(
            tools[0].inputSchema["properties"]["text"]["description"],
            "Text to echo",
        )
        result = await server.call_tool("echo", {"text": "hello"})
        self.assertEqual(result[0].text, "hello")


if __name__ == "__main__":
    unittest.main()
