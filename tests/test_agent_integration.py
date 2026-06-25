import tempfile
import unittest
from pathlib import Path

from app.domain.agent.entity import AgentEntity
from app.domain.agent.tool import BaseTool, ToolParameter, ToolRegistry
from app.infrastructure.observability import ObservabilityService


class FakeLLM:
    def __init__(self):
        self.replies = iter(
            [
                '{"tool":"lookup","arguments":{"query":"Kita"}}',
                '{"tool":"finish","arguments":{"answer":"Kita is ready."}}',
            ]
        )

    async def stream_chat(self, _messages, model=None, **_kwargs):
        yield next(self.replies)


class LookupTool(BaseTool):
    @property
    def name(self):
        return "lookup"

    @property
    def description(self):
        return "Lookup"

    @property
    def parameters(self):
        return [ToolParameter(name="query", description="query")]

    def execute(self, query: str) -> str:
        return f"found:{query}"


class AgentIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_structured_react_loop(self):
        with tempfile.TemporaryDirectory() as directory:
            observability = ObservabilityService(
                trace_path=str(Path(directory) / "traces.jsonl"),
                bad_case_path=str(Path(directory) / "bad.jsonl"),
            )
            registry = ToolRegistry(observability)
            registry.register(LookupTool())
            agent = AgentEntity(session_id="session-1")

            chunks = [
                chunk
                async for chunk in agent.stream_chat(
                    "Who is Kita?",
                    FakeLLM(),
                    tool_registry=registry,
                    observability=observability,
                )
            ]

            self.assertIn("Kita is ready.", "".join(chunks))
            self.assertEqual(agent.messages[-1]["content"], "Kita is ready.")
            event_types = [
                event["event_type"] for event in observability.read_traces()
            ]
            self.assertIn("tool_call", event_types)
            self.assertIn("agent_finished", event_types)


if __name__ == "__main__":
    unittest.main()
