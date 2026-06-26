import re
from typing import List

from langchain_core.documents import Document as LangchainDocument
from langchain_ollama import OllamaEmbeddings
from langchain_postgres import PGVector

from app.core.config import settings
from app.domain.knowledge.repository import DocumentEntity, IKnowledgeRepository


class PgVectorKnowledgeRepository(IKnowledgeRepository):
    def __init__(self):
        self._vector_store = None

    @property
    def vector_store(self) -> PGVector:
        """Connect to embedding/database services only on first real use."""
        if self._vector_store is None:
            embeddings = OllamaEmbeddings(
                base_url=settings.OLLAMA_BASE_URL,
                model=settings.OLLAMA_EMBEDDING_MODEL,
            )
            self._vector_store = PGVector(
                embeddings=embeddings,
                collection_name=settings.PG_VECTOR_COLLECTION_NAME,
                connection=settings.pg_database_url,
                use_jsonb=True,
            )
        return self._vector_store

    def add_documents(self, documents: List[DocumentEntity]) -> None:
        lc_docs = []
        ids = []
        for doc in documents:
            lc_docs.append(LangchainDocument(page_content=doc.content, metadata=doc.metadata))
            ids.append(doc.id)
        self.vector_store.add_documents(lc_docs, ids=ids)

    def similarity_search(
        self, query: str, top_k: int = 5, filter_kwargs: dict | None = None
    ) -> List[DocumentEntity]:
        return [doc for doc, _ in self.similarity_search_with_score(query, top_k, filter_kwargs)]

    def similarity_search_with_score(
        self, query: str, top_k: int = 5, filter_kwargs: dict | None = None
    ) -> List[tuple[DocumentEntity, float]]:
        lc_results = self.vector_store.similarity_search_with_score(
            query=query,
            k=top_k,
            filter=filter_kwargs,
        )
        return [
            (
                DocumentEntity(
                    content=doc.page_content,
                    metadata=doc.metadata,
                    id=getattr(doc, "id", None) or doc.metadata.get("chunk_hash"),
                ),
                float(score),
            )
            for doc, score in lc_results
        ]

    def keyword_search(
        self, query: str, top_k: int = 5, filter_kwargs: dict | None = None
    ) -> List[tuple[DocumentEntity, float]]:
        """A lightweight lexical channel over the PGVector backing table."""
        from sqlalchemy import text

        terms = [
            token
            for token in re.findall(r"[\w\u4e00-\u9fff]{2,}", query.lower())
            if token.strip()
        ][:8]
        if not terms:
            return []

        where_parts = [
            "collection_id = (SELECT uuid FROM langchain_pg_collection WHERE name = :collection_name)"
        ]
        params = {"collection_name": settings.PG_VECTOR_COLLECTION_NAME, "limit": top_k}

        for key, value in (filter_kwargs or {}).items():
            if value is None:
                continue
            param_name = f"filter_{key}"
            where_parts.append(f"cmetadata->>'{key}' = :{param_name}")
            params[param_name] = value

        like_parts = []
        score_parts = []
        for index, term in enumerate(terms):
            param_name = f"term_{index}"
            params[param_name] = f"%{term}%"
            like_parts.append(f"lower(document) LIKE :{param_name}")
            score_parts.append(f"CASE WHEN lower(document) LIKE :{param_name} THEN 1 ELSE 0 END")
        where_parts.append("(" + " OR ".join(like_parts) + ")")

        sql = text(
            f"""
            SELECT document, cmetadata, custom_id, ({' + '.join(score_parts)}) AS keyword_score
            FROM langchain_pg_embedding
            WHERE {' AND '.join(where_parts)}
            ORDER BY keyword_score DESC, length(document) ASC
            LIMIT :limit
            """
        )
        with self.vector_store._make_sync_session() as session:
            rows = session.execute(sql, params).fetchall()

        results: List[tuple[DocumentEntity, float]] = []
        for document, metadata, custom_id, score in rows:
            metadata = metadata or {}
            results.append(
                (
                    DocumentEntity(
                        content=document,
                        metadata=metadata,
                        id=custom_id or metadata.get("chunk_hash"),
                    ),
                    float(score or 0),
                )
            )
        return results

    def delete_by_tag(self, tag: str) -> int:
        from sqlalchemy import text

        with self.vector_store._make_sync_session() as session:
            result = session.execute(
                text(
                    """
                    DELETE FROM langchain_pg_embedding
                    WHERE collection_id = (
                        SELECT uuid FROM langchain_pg_collection
                        WHERE name = :collection_name
                    )
                    AND cmetadata->>'knowledge_tag' = :tag
                    """
                ),
                {"collection_name": settings.PG_VECTOR_COLLECTION_NAME, "tag": tag},
            )
            session.commit()
            return result.rowcount
