import tempfile
import unittest
from pathlib import Path

from app.application.services.ingestion_service import IngestionPipeline, IngestionRequest
from app.application.services.intent_service import IntentTreeService
from app.core.security import RequestIdentity
from app.domain.knowledge.repository import DocumentEntity
from app.infrastructure.llm.routing_client import RoutingLLMClient
from app.infrastructure.platform_store import PlatformStore


class FakeKnowledgeService:
    def __init__(self):
        self.indexed = []

    def build_documents_from_text(self, **kwargs):
        return [
            DocumentEntity(
                id="chunk-alpha",
                content=kwargs["raw_text"],
                metadata={
                    "document_id": "doc-alpha",
                    "chunk_hash": "chunk-alpha",
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

    def build_documents_from_git(self, **kwargs):
        return []

    def store_documents(self, documents):
        self.indexed.extend(documents)


class FakeDelegateLLM:
    async def stream_chat(self, messages, model=None, **kwargs):
        if model == "bad-model":
            raise RuntimeError("boom")
        yield f"model={model}"


class PlatformEvolutionTest(unittest.IsolatedAsyncioTestCase):
    def _store(self, directory: str) -> PlatformStore:
        return PlatformStore(str(Path(directory) / "platform.db"))

    def test_intent_route_query_mapping_kb_and_mcp(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory)
            service = IntentTreeService(store)
            identity = RequestIdentity("admin", "admin")

            service.upsert_query_mapping(
                source_term="工单",
                target_term="ticket",
                identity=identity,
            )
            service.upsert_node(
                {
                    "name": "售后知识库",
                    "kind": "KB",
                    "keywords": ["退款", "售后"],
                    "knowledge_tag": "support",
                    "knowledge_dir": "/support",
                    "priority": 10,
                },
                identity,
            )
            service.upsert_node(
                {
                    "name": "工单工具",
                    "kind": "MCP",
                    "keywords": ["工单", "ticket"],
                    "mcp_server": "local",
                    "mcp_tool": "create_ticket",
                    "priority": 5,
                },
                identity,
            )

            route = service.route("我要退款并创建工单", identity)

            self.assertIn("ticket", route.rewritten_query)
            self.assertEqual(route.knowledge_tag, "support")
            self.assertEqual(route.knowledge_dir, "/support")
            self.assertEqual(route.mcp_tools[0]["tool_name"], "create_ticket")

    def test_ingestion_pipeline_node_logs_and_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory)
            pipeline = IngestionPipeline(FakeKnowledgeService(), store)
            identity = RequestIdentity("user-1", "admin")
            request = IngestionRequest(
                kind="text",
                raw_text="Alpha platform document",
                tag="alpha",
                source_name="manual.md",
                knowledge_dir="/ops",
                visibility="public",
            )

            job_id = pipeline.submit(request, identity)
            pipeline.run(job_id, request, identity)

            job = store.get_ingest_job(job_id)
            self.assertEqual(job["status"], "succeeded")
            self.assertEqual(job["stats"]["chunk_count"], 1)
            self.assertEqual(
                [log["node_name"] for log in store.list_ingestion_node_logs(job_id)],
                ["validate", "parse_text", "chunk", "enrich", "index"],
            )
            bases = store.list_knowledge_bases(user_id="user-1", is_admin=False)
            self.assertEqual(bases[0]["tag"], "alpha")
            docs = store.list_knowledge_documents(user_id="user-1", is_admin=False)
            self.assertEqual(docs[0]["document_id"], "doc-alpha")
            chunks = store.list_knowledge_chunks(document_id="doc-alpha")
            self.assertEqual(chunks[0]["chunk_id"], "chunk-alpha")

    def test_trace_feedback_eval_dataset_and_model_health_store(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory)
            feedback_id = store.insert_trace_feedback(
                trace_id="trace-1",
                session_id="s1",
                user_id="user-1",
                rating=5,
                category="good",
                comment="works",
            )
            self.assertGreater(feedback_id, 0)
            self.assertEqual(store.read_trace_feedback(trace_id="trace-1")[0]["rating"], 5)

            dataset_id = store.create_eval_dataset(
                name="smoke", description="basic", created_by="admin"
            )
            case_id = store.add_eval_case(
                dataset_id=dataset_id,
                query="alpha?",
                expected_keywords=["alpha"],
                tag="alpha",
            )
            self.assertTrue(case_id.startswith("case_"))
            self.assertEqual(store.list_eval_cases(dataset_id)[0]["expected_keywords"], ["alpha"])

            store.upsert_model_config(
                model_name="good-model",
                provider="test",
                enabled=True,
                priority=10,
            )
            store.record_model_health(
                model_name="good-model",
                state="healthy",
                failures=0,
                success=True,
            )
            self.assertEqual(store.list_model_configs(enabled_only=True)[0]["model_name"], "good-model")
            self.assertEqual(store.list_model_health()[0]["state"], "healthy")

    async def test_routing_llm_uses_model_configs_and_records_health(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory)
            store.upsert_model_config(model_name="bad-model", enabled=True, priority=20)
            store.upsert_model_config(model_name="good-model", enabled=True, priority=10)
            client = RoutingLLMClient(FakeDelegateLLM(), platform_store=store)

            chunks = [
                chunk
                async for chunk in client.stream_chat(
                    [{"role": "user", "content": "hello"}]
                )
            ]

            self.assertEqual(chunks, ["model=good-model"])
            health = {item["model_name"]: item for item in store.list_model_health()}
            self.assertEqual(health["bad-model"]["state"], "degraded")
            self.assertEqual(health["good-model"]["state"], "healthy")


if __name__ == "__main__":
    unittest.main()
