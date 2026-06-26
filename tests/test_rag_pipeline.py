import unittest

from app.application.services.knowledge_app_service import KnowledgeAppService
from app.domain.knowledge.repository import DocumentEntity, IKnowledgeRepository


class FakeKnowledgeRepository(IKnowledgeRepository):
    def __init__(self):
        self.documents = []

    def add_documents(self, documents):
        self.documents.extend(documents)

    def similarity_search(self, query, top_k=5, filter_kwargs=None):
        return [doc for doc, _ in self.similarity_search_with_score(query, top_k, filter_kwargs)]

    def similarity_search_with_score(self, query, top_k=5, filter_kwargs=None):
        docs = self._filtered(filter_kwargs)
        scored = []
        for index, doc in enumerate(docs):
            if "Kita" in doc.content or "BLUE" in doc.content:
                scored.append((doc, 0.1 + index))
        return scored[:top_k]

    def keyword_search(self, query, top_k=5, filter_kwargs=None):
        docs = self._filtered(filter_kwargs)
        scored = []
        for doc in docs:
            score = sum(1 for token in query.split() if token and token in doc.content)
            if score:
                scored.append((doc, score))
        return scored[:top_k]

    def delete_by_tag(self, tag):
        before = len(self.documents)
        self.documents = [
            doc for doc in self.documents if doc.metadata.get("knowledge_tag") != tag
        ]
        return before - len(self.documents)

    def _filtered(self, filter_kwargs):
        docs = self.documents
        for key, value in (filter_kwargs or {}).items():
            docs = [doc for doc in docs if doc.metadata.get(key) == value]
        return docs


class RAGPipelineTest(unittest.TestCase):
    def test_retrieved_chunk_fusion_citations_and_permissions(self):
        repo = FakeKnowledgeRepository()
        service = KnowledgeAppService(repo, use_model_reranker=False)
        repo.add_documents(
            [
                DocumentEntity(
                    id="shared",
                    content="Kita secret marker BLUE-COMET-625",
                    metadata={
                        "knowledge_tag": "runtime",
                        "source": "manual.md",
                        "chunk_hash": "shared",
                        "knowledge_dir": "/ops",
                        "visibility": "private",
                        "owner_user_id": "user-1",
                    },
                ),
                DocumentEntity(
                    id="hidden",
                    content="Kita hidden marker BLUE-HIDDEN",
                    metadata={
                        "knowledge_tag": "runtime",
                        "source": "hidden.md",
                        "chunk_hash": "hidden",
                        "knowledge_dir": "/ops",
                        "visibility": "private",
                        "owner_user_id": "user-2",
                    },
                ),
                DocumentEntity(
                    id="public",
                    content="Public Kita guide",
                    metadata={
                        "knowledge_tag": "runtime",
                        "source": "public.md",
                        "chunk_hash": "public",
                        "knowledge_dir": "/public",
                        "visibility": "public",
                    },
                ),
            ]
        )

        chunks = service.retrieve_chunks(
            "Kita BLUE",
            tag="runtime",
            knowledge_dir="/ops",
            user_id="user-1",
            final_top_k=5,
        )

        self.assertEqual([chunk.id for chunk in chunks], ["shared"])
        self.assertIn("vector", chunks[0].channels)
        self.assertIn("keyword", chunks[0].channels)
        self.assertEqual(chunks[0].provenance["citation_index"], 1)

        context = service.format_retrieved_chunks(chunks)
        self.assertIn("[1] Kita secret marker BLUE-COMET-625", context)
        self.assertIn("source=manual.md", context)
        self.assertIn("chunk_id=shared", context)

        hidden = service.retrieve_chunks(
            "Kita BLUE",
            tag="runtime",
            knowledge_dir="/ops",
            user_id="user-3",
            final_top_k=5,
        )
        self.assertEqual(hidden, [])


if __name__ == "__main__":
    unittest.main()
