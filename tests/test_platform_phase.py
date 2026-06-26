import tempfile
import unittest
from pathlib import Path

from app.application.services.chat_app_service import ChatAppService
from app.application.services.ingestion_service import IngestionPipeline, IngestionRequest
from app.core.config import settings
from app.core.security import RequestIdentity
from app.domain.agent.entity import AgentEntity
from app.domain.agent.repository import IAgentRepository
from app.domain.knowledge.repository import DocumentEntity
from app.evaluation.rag import RAGEvaluationCase, evaluate_rag
from app.infrastructure.mcp.client import MCPClientService
from app.infrastructure.observability import ObservabilityService
from app.infrastructure.platform_store import PlatformStore


class FakeKnowledgeService:
    def __init__(self):
        self.stored = []
        self.git = []
        self.documents = []

    def process_and_store_text(self, **kwargs):
        self.stored.append(kwargs)
        documents = self.build_documents_from_text(**kwargs)
        self.store_documents(documents)
        return documents

    def build_documents_from_text(self, **kwargs):
        self.stored.append(kwargs)
        return [
            DocumentEntity(
                id="chunk-1",
                content=kwargs["raw_text"],
                metadata={
                    "document_id": "doc-1",
                    "chunk_hash": "chunk-1",
                    "chunk_index": 0,
                    "knowledge_tag": kwargs["tag"],
                    "source": kwargs["source_name"],
                    "source_name": kwargs["source_name"],
                    "source_type": "text",
                    "owner_user_id": kwargs.get("user_id", "anonymous"),
                    "visibility": kwargs.get("visibility", "public"),
                    "allowed_user_ids": kwargs.get("allowed_user_ids", []),
                    "knowledge_dir": kwargs.get("knowledge_dir") or "",
                },
            )
        ]

    def store_documents(self, documents):
        self.documents.extend(documents)

    def ingest_git_repo(self, **kwargs):
        self.git.append(kwargs)


class FakeLLM:
    async def stream_chat(self, messages, model=None, **kwargs):
        text = messages[-1]["content"]
        if "压缩" in text:
            yield "用户喜欢简洁回答；当前任务是平台化。"
        elif "标题" in text:
            yield "平台化"
        else:
            yield '{"tool":"finish","arguments":{"answer":"ok"}}'


class MemoryRepo(IAgentRepository):
    def __init__(self, agent):
        self.agent = agent
        self.saved = None

    def get(self, session_id, user_id="anonymous"):
        return self.agent

    def save(self, agent, user_id="anonymous"):
        self.saved = agent

    def delete(self, session_id, user_id="anonymous"):
        pass

    def list_sessions(self, user_id="anonymous"):
        return [self.agent.session_id]

    def save_prompt(self, session_id, prompt, user_id="anonymous"):
        pass

    def get_prompt(self, session_id, user_id="anonymous"):
        return None


class PlatformPhaseTest(unittest.IsolatedAsyncioTestCase):
    def test_ingestion_job_persists_status(self):
        with tempfile.TemporaryDirectory() as directory:
            store = PlatformStore(str(Path(directory) / "platform.db"))
            knowledge = FakeKnowledgeService()
            pipeline = IngestionPipeline(knowledge, store)
            identity = RequestIdentity("user-1", "admin")
            request = IngestionRequest(
                kind="text",
                raw_text="Kita platform ingestion",
                tag="platform",
                source_name="unit",
            )

            job_id = pipeline.submit(request, identity)
            self.assertEqual(store.get_ingest_job(job_id)["status"], "queued")
            pipeline.run(job_id, request, identity)

            job = store.get_ingest_job(job_id)
            self.assertEqual(job["status"], "succeeded")
            self.assertTrue(job["stats"]["stored"])
            self.assertEqual(knowledge.stored[0]["user_id"], "user-1")

    def test_observability_writes_sqlite_trace(self):
        with tempfile.TemporaryDirectory() as directory:
            store = PlatformStore(str(Path(directory) / "platform.db"))
            obs = ObservabilityService(
                trace_path=str(Path(directory) / "traces.jsonl"),
                bad_case_path=str(Path(directory) / "bad.jsonl"),
                platform_store=store,
            )
            trace_id = obs.start_trace("s1", "hello", "model")
            obs.finish_trace(trace_id, "s1", "answer", 1, True)
            obs.record_bad_case(
                category="unit",
                session_id="s1",
                trace_id=trace_id,
                input_text="bad",
                detail="detail",
            )

            events = obs.read_trace_events(session_id="s1")
            self.assertEqual([e["event_type"] for e in events], ["agent_started", "agent_finished"])
            self.assertEqual(obs.trace_summary()["bad_cases"], 1)
            self.assertEqual(obs.read_bad_cases()[0]["category"], "unit")

    async def test_conversation_summary_memory(self):
        old_trigger = settings.SUMMARY_TRIGGER_MESSAGES
        old_keep = settings.SUMMARY_KEEP_RECENT_MESSAGES
        try:
            settings.SUMMARY_TRIGGER_MESSAGES = 4
            settings.SUMMARY_KEEP_RECENT_MESSAGES = 2
            agent = AgentEntity(
                session_id="s1",
                owner_user_id="user-1",
                messages=[
                    {"role": "system", "content": "sys"},
                    {"role": "user", "content": "u1"},
                    {"role": "assistant", "content": "a1"},
                    {"role": "user", "content": "u2"},
                    {"role": "assistant", "content": "a2"},
                ],
            )
            service = ChatAppService(FakeLLM(), MemoryRepo(agent), knowledge_service=None)
            chunks = [
                event.content
                async for event in service.do_stream_chat(
                    "s1", "继续", identity=RequestIdentity("user-1", "admin")
                )
                if event.content
            ]
            self.assertIn("ok", "".join(chunks))
            self.assertIn("平台化", service.agent_repo.saved.conversation_summary)
            non_system = [
                m for m in service.agent_repo.saved.messages if m.get("role") != "system"
            ]
            self.assertLessEqual(len(non_system), settings.SUMMARY_KEEP_RECENT_MESSAGES)
        finally:
            settings.SUMMARY_TRIGGER_MESSAGES = old_trigger
            settings.SUMMARY_KEEP_RECENT_MESSAGES = old_keep

    def test_mcp_client_config_parsing(self):
        client = MCPClientService.from_config_string(
            "local=http://localhost:8000/mcp/, other=http://127.0.0.1:9000/mcp/"
        )
        self.assertEqual([s["name"] for s in client.list_servers()], ["local", "other"])

    def test_evaluation_suite_metrics(self):
        cases = [
            RAGEvaluationCase(query="q1", expected_keywords=["alpha", "beta"]),
            RAGEvaluationCase(query="q2", expected_keywords=["gamma"], must_not_contain=["secret"]),
        ]

        def retrieve(query, tag=None):
            if query == "q1":
                return "[1] alpha\n---\n[2] beta"
            return "gamma"

        report = evaluate_rag(cases, retrieve)
        self.assertEqual(report.total, 2)
        self.assertEqual(report.hit_rate, 1.0)
        self.assertEqual(report.keyword_recall, 1.0)
        self.assertGreater(report.average_latency_ms, 0)


if __name__ == "__main__":
    unittest.main()
