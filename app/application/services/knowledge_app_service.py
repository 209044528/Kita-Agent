import hashlib
from langchain_text_splitters import RecursiveCharacterTextSplitter, MarkdownHeaderTextSplitter
from app.domain.knowledge.repository import IKnowledgeRepository, DocumentEntity
from typing import List
import httpx
from loguru import logger
from app.core.config import settings


from app.infrastructure.parser.git_parser import GitRepositoryParser


class KnowledgeAppService:
    def __init__(
        self, 
        knowledge_repo: IKnowledgeRepository, 
        use_model_reranker: bool = False,
        git_parser: GitRepositoryParser | None = None
    ):
        self.knowledge_repo = knowledge_repo
        self.use_model_reranker = use_model_reranker
        self.git_parser = git_parser or GitRepositoryParser()

        # 混合切分策略：先按 Markdown 标题切分，再细粒度切分
        self.markdown_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=[
                ("#", "Header 1"),
                ("##", "Header 2"),
                ("###", "Header 3"),
            ]
        )

        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=400,
            chunk_overlap=50,
            separators=["\n\n", "\n", "。", "！", "？", " ", ""]
        )

    def process_and_store_text(self, raw_text: str, tag: str, source_name: str) -> None:
        """
        处理原始文本：混合切分策略 -> 附加元数据 -> 向量化入库
        混合策略：先按 Markdown 标题层级切分，再进行细粒度切分
        """
        # 1. 混合文本切分
        # 第一步：尝试按 Markdown 标题切分
        try:
            md_chunks = self.markdown_splitter.split_text(raw_text)
            # 第二步：对每个 Markdown 块进行细粒度切分
            chunks = []
            for md_doc in md_chunks:
                # 保留 Markdown 标题元数据
                header_metadata = md_doc.metadata if hasattr(md_doc, 'metadata') else {}
                content = md_doc.page_content if hasattr(md_doc, 'page_content') else md_doc

                # 细粒度切分 (递归切分)
                sub_chunks = self.text_splitter.split_text(content)
                for sub_chunk in sub_chunks:
                    # 仅添加细粒度切分后的子块，不添加 md_chunks 父块
                    chunks.append((sub_chunk, header_metadata))
        except Exception as e:
            logger.warning(f"Markdown splitting failed or skipped: {str(e)}. Falling back to recursive splitting.")
            # 如果不是 Markdown 格式或切分失败，直接使用细粒度切分
            sub_chunks = self.text_splitter.split_text(raw_text)
            chunks = [(chunk, {}) for chunk in sub_chunks]

        # 2. 构建领域实体并注入元数据 (知识打标 + Markdown 标题信息 + 唯一哈希)
        documents = []
        for chunk_content, header_meta in chunks:
            # 生成内容的唯一 MD5 指纹作为 ID，用于幂等去重
            chunk_id = hashlib.md5(chunk_content.encode("utf-8")).hexdigest()
            
            metadata = {
                "knowledge_tag": tag,
                "source": source_name,
                "chunk_hash": chunk_id,
                **header_meta  # 合并 Markdown 标题元数据
            }
            doc = DocumentEntity(
                content=chunk_content,
                metadata=metadata,
                id=chunk_id
            )
            documents.append(doc)

        # 3. 持久化到向量数据库
        self.knowledge_repo.add_documents(documents)

    def retrieve_knowledge(self, user_query: str, tag: str = None, initial_top_k: int = 15, final_top_k: int = 3) -> str:
        """
        检索知识并组装成上下文字符串
        采用两阶段检索：粗排（扩大召回）+ 重排（精准筛选）

        Args:
            user_query: 用户查询
            tag: 知识标签过滤（可选）
            initial_top_k: 粗排阶段召回数量，默认 15
            final_top_k: 重排后最终返回数量，默认 3
        """
        filters = {"knowledge_tag": tag} if tag else None

        # 第一阶段：粗排 - 扩大召回范围
        docs = self.knowledge_repo.similarity_search(
            query=user_query,
            top_k=initial_top_k,
            filter_kwargs=filters
        )

        if not docs:
            return ""

        # 第二阶段：重排 - 使用远程 BGE-Reranker 服务
        if self.use_model_reranker:
            reranked_docs = self._rerank_with_model(user_query, docs, final_top_k)
        else:
            reranked_docs = docs[:final_top_k]

        # 提取文本内容进行拼接
        context = "\n---\n".join([doc.content for doc in reranked_docs])
        return context

    def _rerank_with_model(self, query: str, documents: List[DocumentEntity], top_k: int) -> List[DocumentEntity]:
        """
        使用远程 BGE-Reranker 服务进行重排

        通过 HTTP 请求调用独立部署的 Reranker 微服务
        服务地址由环境变量 RERANKER_API_URL 配置
        """
        try:
            # 构建请求数据
            payload = {
                "query": query,
                "documents": [doc.content for doc in documents],
                "return_documents": False
            }

            # 发送 HTTP POST 请求到 Reranker 服务
            with httpx.Client(timeout=30.0) as client:
                response = client.post(settings.RERANKER_API_URL, json=payload)
                response.raise_for_status()

            # 解析返回结果
            result = response.json()
            results = result.get("results", [])

            if not results or len(results) != len(documents):
                logger.warning(f"Reranker returned invalid results (len={len(results)} vs docs={len(documents)}), falling back to original order")
                return documents[:top_k]

            # 检查 API 是否返回了 index
            # 如果有 index，直接按 index 映射文档
            if "index" in results[0]:
                reranked_docs = []
                for item in results:
                    idx = item["index"]
                    if 0 <= idx < len(documents):
                        reranked_docs.append(documents[idx])
                return reranked_docs[:top_k]

            # 如果 API 只返回了分数且没有 index，假设分数列表与输入文档顺序一致
            # 优先匹配 "score" 或 "relevance_score" 字段
            scores = []
            for item in results:
                s = item.get("score")
                if s is None:
                    s = item.get("relevance_score", 0)
                scores.append(s)

            scored_docs = list(zip(scores, documents))
            scored_docs.sort(key=lambda x: x[0], reverse=True)

            return [doc for _, doc in scored_docs[:top_k]]
        except Exception as e:
            logger.error(f"Error calling reranker service at {settings.RERANKER_API_URL}: {str(e)}. Falling back to original order. Please check if the reranker service is running and accessible.")
            return documents[:top_k]

    def delete_knowledge_by_tag(self, tag: str) -> int:
        """
        根据标签删除知识库内容，返回删除的文档数量
        """
        return self.knowledge_repo.delete_by_tag(tag)

    def ingest_git_repo(self, repo_url: str, branch: str = "main", knowledge_tag: str = None) -> None:
        """
        解析 Git 仓库并向量化入库
        """
        # 1. 确定标签
        if not knowledge_tag:
            # 优先从 URL 中提取仓库名作为标签，而不是 URL 的最后一部分（可能是分支名）
            if "github.com" in repo_url:
                # 移除末尾斜杠和 .git
                clean_url = repo_url.rstrip("/").replace(".git", "")
                if "/tree/" in clean_url:
                    knowledge_tag = clean_url.split("/tree/")[0].split("/")[-1]
                elif "/blob/" in clean_url:
                    knowledge_tag = clean_url.split("/blob/")[0].split("/")[-1]
                else:
                    knowledge_tag = clean_url.split("/")[-1]
            else:
                knowledge_tag = repo_url.split("/")[-1].replace(".git", "")

        # 2. 调用解析器获取分块后的文档实体
        documents = self.git_parser.parse_repo(repo_url, branch)

        # 3. 注入统一标签并入库
        for doc in documents:
            doc.metadata["knowledge_tag"] = knowledge_tag
            # 这里的 ID 已在 GitParser 中生成（或者可以重新生成以保证幂等）
            if not doc.id:
                doc.id = hashlib.md5(doc.content.encode("utf-8")).hexdigest()

        if documents:
            self.knowledge_repo.add_documents(documents)
            logger.info(f"Git 仓库 {repo_url} 入库成功，标签: {knowledge_tag}")