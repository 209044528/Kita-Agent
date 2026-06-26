from __future__ import annotations

from app.application.services.chat_app_service import ChatAppService
from app.application.services.knowledge_app_service import KnowledgeAppService
from app.core.config import settings
from app.infrastructure.llm.litellm_client import LiteLLMClient
from app.infrastructure.llm.routing_client import RoutingLLMClient
from app.infrastructure.observability import ObservabilityService
from app.infrastructure.parser.git_parser import GitRepositoryParser
from app.infrastructure.repository.pgvector_knowledge_repo import (
    PgVectorKnowledgeRepository,
)
from app.infrastructure.repository.redis_agent_repo import RedisAgentRepository
from app.core.task_manager import AgentTaskManager


class Container:
    """Lazy dependency container.

    Importing the FastAPI app no longer connects to PostgreSQL, Redis, or Ollama.
    External dependencies are initialized only when their service is requested.
    """

    def __init__(self):
        self._llm_client: RoutingLLMClient | None = None
        self._knowledge_repo: PgVectorKnowledgeRepository | None = None
        self._agent_repo: RedisAgentRepository | None = None
        self._git_parser: GitRepositoryParser | None = None
        self._knowledge_service: KnowledgeAppService | None = None
        self._chat_service: ChatAppService | None = None
        self._task_manager: AgentTaskManager | None = None
        self.observability = ObservabilityService(
            trace_path=settings.TRACE_PATH,
            bad_case_path=settings.BAD_CASE_PATH,
            enabled=settings.OBSERVABILITY_ENABLED,
        )

    def get_agent_repo(self) -> RedisAgentRepository:
        if self._agent_repo is None:
            self._agent_repo = RedisAgentRepository()
        return self._agent_repo

    def get_knowledge_service(self) -> KnowledgeAppService:
        if self._knowledge_service is None:
            self._knowledge_repo = PgVectorKnowledgeRepository()
            self._git_parser = GitRepositoryParser()
            self._knowledge_service = KnowledgeAppService(
                knowledge_repo=self._knowledge_repo,
                use_model_reranker=True,
                git_parser=self._git_parser,
            )
        return self._knowledge_service

    def get_chat_service(self) -> ChatAppService:
        if self._chat_service is None:
            self._llm_client = RoutingLLMClient(LiteLLMClient())
            self._chat_service = ChatAppService(
                llm_client=self._llm_client,
                agent_repo=self.get_agent_repo(),
                knowledge_service=self.get_knowledge_service(),
                observability=self.observability,
                task_manager=self.get_task_manager(),
            )
        return self._chat_service

    def get_task_manager(self) -> AgentTaskManager:
        if self._task_manager is None:
            self._task_manager = AgentTaskManager()
        return self._task_manager


_container = Container()


def get_knowledge_service() -> KnowledgeAppService:
    return _container.get_knowledge_service()


def get_chat_service() -> ChatAppService:
    return _container.get_chat_service()


def get_agent_repo() -> RedisAgentRepository:
    return _container.get_agent_repo()


def get_tool_registry():
    return _container.get_chat_service().tool_registry


def get_observability() -> ObservabilityService:
    return _container.observability


def get_task_manager() -> AgentTaskManager:
    return _container.get_task_manager()
