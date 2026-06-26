import unittest
from contextlib import asynccontextmanager

from fastapi.testclient import TestClient

import main
from app.core.container import get_chat_service, get_task_manager
from app.core.rate_limit import rate_limit_by_ip
from app.domain.agent.events import AgentStreamEvent


class FakeChatService:
    async def do_stream_chat(self, **kwargs):
        yield AgentStreamEvent(event="progress", content="thinking")
        yield AgentStreamEvent(event="content", content="answer")


class FakeTaskManager:
    def new_task_id(self):
        return "task-test"

    @asynccontextmanager
    async def run(self, task_id, identity, session_id):
        yield

    async def cancel(self, task_id, identity):
        return True


async def bypass_rate_limit():
    return None


class SSEProtocolTest(unittest.TestCase):
    def setUp(self):
        main.app.dependency_overrides[get_chat_service] = lambda: FakeChatService()
        main.app.dependency_overrides[get_task_manager] = lambda: FakeTaskManager()
        main.app.dependency_overrides[rate_limit_by_ip] = bypass_rate_limit
        self.client = TestClient(main.app)

    def tearDown(self):
        main.app.dependency_overrides.clear()

    def test_stream_has_typed_events_and_task_id(self):
        response = self.client.post(
            "/api/v1/chat/stream",
            json={"session_id": "session-1", "user_input": "hello"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["x-task-id"], "task-test")
        self.assertIn("event: meta", response.text)
        self.assertIn("event: progress", response.text)
        self.assertIn("event: content", response.text)
        self.assertIn("event: done", response.text)


if __name__ == "__main__":
    unittest.main()
