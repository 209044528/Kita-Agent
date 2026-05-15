from typing import Optional
from app.domain.agent.tool import BaseTool, ToolParameter


class KnowledgeSearchTool(BaseTool):
    """知识库检索工具"""

    def __init__(self, knowledge_service):
        """
        Args:
            knowledge_service: KnowledgeAppService 实例
        """
        self._knowledge_service = knowledge_service

    @property
    def name(self) -> str:
        return "knowledge_search"

    @property
    def description(self) -> str:
        return "从知识库中检索相关信息"

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="query",
                type="string",
                description="检索关键词",
                required=True
            ),
            ToolParameter(
                name="tag",
                type="string",
                description="知识标签（可选）",
                required=False
            )
        ]

    def execute(self, query: str, tag: Optional[str] = None) -> str:
        """
        执行知识库检索

        Args:
            query: 检索关键词
            tag: 知识标签（可选）

        Returns:
            检索结果
        """
        if not self._knowledge_service:
            return "错误: 知识库服务未初始化，无法执行检索。"

        if not query or not query.strip():
            return "错误: 检索关键词不能为空。"

        try:
            result = self._knowledge_service.retrieve_knowledge(query, tag)
            if not result or result.strip() == "":
                return "未找到相关知识，请尝试其他关键词或直接回答用户问题。"
            return result
        except Exception as e:
            return f"知识库检索错误: {e}"
