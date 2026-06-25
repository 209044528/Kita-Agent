import tempfile
import unittest
from pathlib import Path

from app.domain.agent.tool import BaseTool, ToolParameter, ToolRegistry
from app.infrastructure.observability import ObservabilityService


class EchoTool(BaseTool):
    @property
    def name(self):
        return "echo"

    @property
    def description(self):
        return "Echo text"

    @property
    def parameters(self):
        return [ToolParameter(name="text", description="Text")]

    def execute(self, text: str) -> str:
        return text


class ToolRegistryTest(unittest.TestCase):
    def test_schema_and_validation(self):
        registry = ToolRegistry()
        registry.register(EchoTool())
        definition = registry.definitions()[0]
        self.assertEqual(definition["name"], "echo")
        self.assertEqual(definition["inputSchema"]["required"], ["text"])
        self.assertFalse(definition["inputSchema"]["additionalProperties"])
        self.assertIn("参数校验失败", registry.execute("echo", {}))

    def test_metrics_and_trace_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            observability = ObservabilityService(
                trace_path=str(Path(directory) / "traces.jsonl"),
                bad_case_path=str(Path(directory) / "bad.jsonl"),
            )
            registry = ToolRegistry(observability)
            registry.register(EchoTool())
            result = registry.execute(
                "echo", {"text": "hello"}, session_id="s1", trace_id="t1", step=1
            )
            self.assertEqual(result, "hello")
            self.assertEqual(observability.metrics()["tools"]["echo"]["calls"], 1)
            self.assertEqual(
                observability.read_traces(session_id="s1")[0]["event_type"],
                "tool_call",
            )


if __name__ == "__main__":
    unittest.main()
