from abc import ABC, abstractmethod
from typing import List, Dict, Any


class DocumentEntity:
    """领域层文档实体"""

    def __init__(self, content: str, metadata: Dict[str, Any] = None, id: str = None):
        self.content = content
        self.metadata = metadata or {}
        self.id = id


class IKnowledgeRepository(ABC):
    """知识库存储抽象接口"""

    @abstractmethod
    def add_documents(self, documents: List[DocumentEntity]) -> None:
        """将文档向量化并存入知识库"""
        pass

    @abstractmethod
    def similarity_search(self, query: str, top_k: int = 5, filter_kwargs: dict = None) -> List[DocumentEntity]:
        """根据 query 检索最相似的文档"""
        pass

    @abstractmethod
    def delete_by_tag(self, tag: str) -> int:
        """根据 tag 删除知识库中的文档，返回删除的文档数量"""
        pass