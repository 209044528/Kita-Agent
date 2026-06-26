from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class DocumentEntity(BaseModel):
    """Knowledge document/chunk stored in the repository."""

    content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    id: Optional[str] = None


class RetrievedChunk(BaseModel):
    """Structured retrieval result produced by the RAG pipeline."""

    id: str
    content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    source: str = ""
    tag: str | None = None
    knowledge_dir: str | None = None
    channels: list[str] = Field(default_factory=list)
    score: float = 0.0
    vector_score: float | None = None
    keyword_score: float | None = None
    rerank_score: float | None = None
    provenance: Dict[str, Any] = Field(default_factory=dict)


class IKnowledgeRepository(ABC):
    """Storage abstraction for knowledge chunks."""

    @abstractmethod
    def add_documents(self, documents: List[DocumentEntity]) -> None:
        """Persist documents into the knowledge store."""
        raise NotImplementedError

    @abstractmethod
    def similarity_search(
        self, query: str, top_k: int = 5, filter_kwargs: dict | None = None
    ) -> List[DocumentEntity]:
        """Return vector-similar documents."""
        raise NotImplementedError

    def similarity_search_with_score(
        self, query: str, top_k: int = 5, filter_kwargs: dict | None = None
    ) -> List[tuple[DocumentEntity, float]]:
        """Return vector candidates and raw backend scores when available."""
        return [(doc, 1.0) for doc in self.similarity_search(query, top_k, filter_kwargs)]

    def keyword_search(
        self, query: str, top_k: int = 5, filter_kwargs: dict | None = None
    ) -> List[tuple[DocumentEntity, float]]:
        """Optional lexical retrieval channel. Repositories may override this."""
        return []

    @abstractmethod
    def delete_by_tag(self, tag: str) -> int:
        """Delete documents by tag and return the deleted row count."""
        raise NotImplementedError
