from app.infrastructure.llm.litellm_client import LiteLLMClient
from app.infrastructure.repository.pgvector_knowledge_repo import PgVectorKnowledgeRepository
from app.infrastructure.repository.redis_agent_repo import RedisAgentRepository
from app.application.services.knowledge_app_service import KnowledgeAppService
from app.application.services.chat_app_service import ChatAppService


from app.infrastructure.parser.git_parser import GitRepositoryParser

class Container:
    """
    依赖注入容器
    管理基础设施层组件的实例化，并完成应用服务的组装
    """

    def __init__(self):
        # 1. 实例化基础设施层组件
        self.llm_client = LiteLLMClient()
        self.knowledge_repo = PgVectorKnowledgeRepository()
        self.agent_repo = RedisAgentRepository()
        self.git_parser = GitRepositoryParser()

        # 2. 组装应用服务层
        # 知识管理服务
        self.knowledge_app_service = KnowledgeAppService(
            knowledge_repo=self.knowledge_repo, 
            use_model_reranker=True,
            git_parser=self.git_parser
        )

        # 对话应用服务
        self.chat_app_service = ChatAppService(
            llm_client=self.llm_client,
            agent_repo=self.agent_repo,
            knowledge_service=self.knowledge_app_service
        )


# 全局单例容器
_container = Container()


# 获取组件的 Provider 函数，供 FastAPI Depends 使用
def get_knowledge_service() -> KnowledgeAppService:
    return _container.knowledge_app_service


def get_chat_service() -> ChatAppService:
    return _container.chat_app_service


def get_agent_repo() -> RedisAgentRepository:
    return _container.agent_repo
