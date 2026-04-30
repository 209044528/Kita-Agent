from langchain_text_splitters import RecursiveCharacterTextSplitter
from app.domain.knowledge.repository import IKnowledgeRepository, DocumentEntity


class KnowledgeAppService:
    def __init__(self, knowledge_repo: IKnowledgeRepository):
        self.knowledge_repo = knowledge_repo
        # 初始化文本分块器
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=100,
            separators=["\n\n", "\n", "。", "！", "？", " ", ""]
        )

    def process_and_store_text(self, raw_text: str, tag: str, source_name: str) -> None:
        """
        处理原始文本：切分 -> 附加元数据 -> 向量化入库
        """
        # 1. 文本切分
        chunks = self.text_splitter.split_text(raw_text)

        # 2. 构建领域实体并注入元数据 (知识打标)
        documents = []
        for chunk in chunks:
            doc = DocumentEntity(
                content=chunk,
                metadata={
                    "knowledge_tag": tag,
                    "source": source_name
                }
            )
            documents.append(doc)

        # 3. 持久化到向量数据库
        self.knowledge_repo.add_documents(documents)

    def retrieve_knowledge(self, user_query: str, tag: str = None) -> str:
        """
        检索知识并组装成上下文字符串
        """
        filters = {"knowledge_tag": tag} if tag else None

        docs = self.knowledge_repo.similarity_search(
            query=user_query,
            top_k=5,
            filter_kwargs=filters
        )

        # 提取文本内容进行拼接
        context = "\n---\n".join([doc.content for doc in docs])
        return context