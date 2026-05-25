from typing import List
from langchain_openai import OpenAIEmbeddings
from langchain_postgres import PGVector
from langchain_core.documents import Document as LangchainDocument
from langchain_ollama import OllamaEmbeddings

from app.core.config import settings
from app.domain.knowledge.repository import IKnowledgeRepository, DocumentEntity


class PgVectorKnowledgeRepository(IKnowledgeRepository):
    def __init__(self):
        self.embeddings = OllamaEmbeddings(
            base_url=settings.OLLAMA_BASE_URL,
            model=settings.OLLAMA_EMBEDDING_MODEL
        )
        # self.embeddings = OpenAIEmbeddings(
        #     model="text-embedding-3-small"
        # )

        # 初始化 LangChain 的 PGVector
        self.vector_store = PGVector(
            embeddings=self.embeddings,
            collection_name=settings.PG_VECTOR_COLLECTION_NAME,
            connection=settings.pg_database_url,
            use_jsonb=True,
        )

    def add_documents(self, documents: List[DocumentEntity]) -> None:
        # 将领域实体转换为 LangChain 文档格式，并提取唯一 ID
        lc_docs = []
        ids = []
        for doc in documents:
            lc_docs.append(LangchainDocument(page_content=doc.content, metadata=doc.metadata))
            ids.append(doc.id)
            
        # 使用 ids 参数调用 add_documents 以实现幂等去重 (Upsert)
        self.vector_store.add_documents(lc_docs, ids=ids)

    def similarity_search(self, query: str, top_k: int = 5, filter_kwargs: dict = None) -> List[DocumentEntity]:
        # 执行相似度检索
        lc_docs = self.vector_store.similarity_search(
            query=query,
            k=top_k,
            filter=filter_kwargs
        )
        # 将 LangChain 文档转换回领域实体，包含 ID
        return [
            DocumentEntity(content=doc.page_content, metadata=doc.metadata, id=getattr(doc, 'id', None))
            for doc in lc_docs
        ]

    def delete_by_tag(self, tag: str) -> int:
        from sqlalchemy import text

        # 直接使用 SQL 删除指定 tag 的文档
        with self.vector_store._make_sync_session() as session:
            result = session.execute(
                text(f"""
                    DELETE FROM langchain_pg_embedding
                    WHERE collection_id = (
                        SELECT uuid FROM langchain_pg_collection
                        WHERE name = :collection_name
                    )
                    AND cmetadata->>'knowledge_tag' = :tag
                """),
                {"collection_name": settings.PG_VECTOR_COLLECTION_NAME, "tag": tag}
            )
            session.commit()
            return result.rowcount