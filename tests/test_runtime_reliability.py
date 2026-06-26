import asyncio
import tempfile
import unittest
from pathlib import Path

from app.application.services.document_parser_service import DocumentParserService
from app.core.config import settings
from app.core.exceptions import AuthenticationError, LLMError
from app.core.input_security import validate_git_url, validate_upload_name
from app.core.security import get_identity
from app.core.security import RequestIdentity
from app.core.task_manager import AgentTaskManager
from app.core.exceptions import SessionBusyError
from app.domain.agent.repository import ILLMClient
from app.domain.agent.tool import BaseTool, ToolParameter, ToolRegistry
from app.infrastructure.llm.routing_client import RoutingLLMClient


class SlowTool(BaseTool):
    @property
    def name(self):
        return "slow"

    @property
    def description(self):
        return "Slow tool"

    @property
    def parameters(self):
        return [ToolParameter(name="value", description="value")]

    def execute(self, value: str) -> str:
        return value

    async def execute_async(self, **kwargs):
        await asyncio.sleep(0.05)
        return kwargs["value"]


class FallbackDelegate(ILLMClient):
    async def stream_chat(self, messages, model=None, **kwargs):
        if model == "broken-model":
            raise LLMError("broken", error_type="provider_error")
        yield "ok"


class FakeRedis:
    def __init__(self):
        self.values = {}

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def setex(self, key, ttl, value):
        self.values[key] = value
        return True

    async def get(self, key):
        return self.values.get(key)

    async def exists(self, key):
        return int(key in self.values)

    async def delete(self, *keys):
        for key in keys:
            self.values.pop(key, None)

    async def eval(self, script, number_of_keys, key, task_id, *args):
        if self.values.get(key) != task_id:
            return 0
        if "expire" in script:
            return 1
        self.values.pop(key, None)
        return 1


class RuntimeReliabilityTest(unittest.IsolatedAsyncioTestCase):
    async def test_async_tool_timeout_is_structured(self):
        registry = ToolRegistry(timeout_seconds=0.01)
        registry.register(SlowTool())
        result = await registry.async_execute("slow", {"value": "hello"})
        self.assertIn("超过", result)

    async def test_model_fallback(self):
        old_model = settings.MODEL_NAME
        old_fallbacks = settings.MODEL_FALLBACKS
        try:
            settings.MODEL_NAME = "broken-model"
            settings.MODEL_FALLBACKS = "healthy-model"
            client = RoutingLLMClient(FallbackDelegate())
            result = [
                chunk
                async for chunk in client.stream_chat([{"role": "user", "content": "hi"}])
            ]
            self.assertEqual(result, ["ok"])
        finally:
            settings.MODEL_NAME = old_model
            settings.MODEL_FALLBACKS = old_fallbacks

    async def test_same_session_is_exclusive(self):
        manager = AgentTaskManager()
        manager.redis = FakeRedis()
        identity = RequestIdentity("user-1")
        async with manager.run("task-1", identity, "session-1"):
            with self.assertRaises(SessionBusyError):
                async with manager.run("task-2", identity, "session-1"):
                    pass

    def test_bearer_key_maps_to_user(self):
        old_enabled = settings.AUTH_ENABLED
        old_keys = settings.AUTH_API_KEYS
        try:
            settings.AUTH_ENABLED = True
            settings.AUTH_API_KEYS = "secret:user-1:admin"
            identity = get_identity("Bearer secret")
            self.assertEqual(identity.user_id, "user-1")
            self.assertTrue(identity.is_admin)
            with self.assertRaises(AuthenticationError):
                get_identity("Bearer invalid")
        finally:
            settings.AUTH_ENABLED = old_enabled
            settings.AUTH_API_KEYS = old_keys

    def test_unsafe_inputs_are_rejected(self):
        with self.assertRaises(Exception):
            validate_git_url("file:///etc/passwd")
        with self.assertRaises(Exception):
            validate_git_url("https://example.com/repo.git")
        with self.assertRaises(Exception):
            validate_upload_name("../../payload.exe")
        self.assertEqual(validate_upload_name("../../notes.md"), "notes.md")

    def test_markdown_upload_uses_text_parser(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "notes.md"
            path.write_text("# Hello\nUPLOAD-GREEN-731", encoding="utf-8")
            self.assertIn(
                "UPLOAD-GREEN-731",
                DocumentParserService.parse_document_to_text(str(path)),
            )


if __name__ == "__main__":
    unittest.main()
