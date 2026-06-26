from typing import Any, Optional

from app.domain.agent.tool import BaseTool, ToolParameter


class KnowledgeSearchTool(BaseTool):
    """Search the knowledge base and return cited chunks."""

    def __init__(self, knowledge_service):
        self._knowledge_service = knowledge_service

    @property
    def name(self) -> str:
        return "knowledge_search"

    @property
    def description(self) -> str:
        return "从知识库检索相关信息，返回带引用编号、来源和分数的片段。"

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(name="query", type="string", description="检索查询", required=True),
            ToolParameter(name="tag", type="string", description="知识标签（可选）", required=False),
            ToolParameter(
                name="knowledge_dir",
                type="string",
                description="知识库目录（可选）",
                required=False,
            ),
            ToolParameter(
                name="top_k",
                type="integer",
                description="最终返回片段数量，默认 3",
                required=False,
                default=3,
            ),
            ToolParameter(
                name="channels",
                type="array",
                description="检索通道，默认 ['vector','keyword']",
                required=False,
                default=["vector", "keyword"],
            ),
        ]

    def execute(
        self,
        query: str,
        tag: Optional[str] = None,
        knowledge_dir: Optional[str] = None,
        top_k: int = 3,
        channels: Optional[list[str]] = None,
        *,
        user_id: str = "anonymous",
        is_admin: bool = False,
    ) -> str:
        if not self._knowledge_service:
            return "错误: 知识库服务未初始化，无法执行检索。"
        if not query or not query.strip():
            return "错误: 检索查询不能为空。"

        try:
            result = self._knowledge_service.retrieve_knowledge(
                user_query=query,
                tag=tag,
                final_top_k=top_k or 3,
                user_id=user_id,
                is_admin=is_admin,
                knowledge_dir=knowledge_dir,
                channels=channels,
            )
            if not result.strip():
                return "未找到当前用户可访问的相关知识。"
            return result
        except Exception as e:
            return f"知识库检索错误: {e}"

    async def execute_async(self, run_context: Any = None, **kwargs: Any) -> str:
        if run_context:
            kwargs.setdefault("user_id", run_context.identity.user_id)
            kwargs.setdefault("is_admin", run_context.identity.is_admin)
            if getattr(run_context, "knowledge_dir", None) and not kwargs.get("knowledge_dir"):
                kwargs["knowledge_dir"] = run_context.knowledge_dir
        return self.execute(**kwargs)
