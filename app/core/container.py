from __future__ import annotations

from app.application.services.chat_app_service import ChatAppService
from app.application.services.ingestion_service import IngestionPipeline
from app.application.services.intent_service import IntentTreeService
from app.application.services.knowledge_app_service import KnowledgeAppService
from app.core.config import settings
from app.infrastructure.llm.litellm_client import LiteLLMClient
from app.infrastructure.llm.routing_client import RoutingLLMClient
from app.infrastructure.observability import ObservabilityService
from app.infrastructure.mcp.client import MCPClientService
from app.infrastructure.platform_store import PlatformStore
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
        self._platform_store: PlatformStore | None = None
        self._ingestion_pipeline: IngestionPipeline | None = None
        self._mcp_client: MCPClientService | None = None
        self._intent_service: IntentTreeService | None = None
        self.observability = ObservabilityService(
            trace_path=settings.TRACE_PATH,
            bad_case_path=settings.BAD_CASE_PATH,
            platform_store=self.get_platform_store(),
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
            self._llm_client = RoutingLLMClient(
                LiteLLMClient(),
                platform_store=self.get_platform_store(),
            )
            self._chat_service = ChatAppService(
                llm_client=self._llm_client,
                agent_repo=self.get_agent_repo(),
                knowledge_service=self.get_knowledge_service(),
                observability=self.observability,
                task_manager=self.get_task_manager(),
                intent_service=self.get_intent_service(),
                mcp_client=self.get_mcp_client(),
            )
        return self._chat_service

    def get_task_manager(self) -> AgentTaskManager:
        if self._task_manager is None:
            self._task_manager = AgentTaskManager()
        return self._task_manager

    def get_platform_store(self) -> PlatformStore:
        if self._platform_store is None:
            self._platform_store = PlatformStore(settings.PLATFORM_DB_PATH)
        return self._platform_store

    def get_ingestion_pipeline(self) -> IngestionPipeline:
        if self._ingestion_pipeline is None:
            self._ingestion_pipeline = IngestionPipeline(
                self.get_knowledge_service(), self.get_platform_store()
            )
        return self._ingestion_pipeline

    def get_mcp_client(self) -> MCPClientService:
        if self._mcp_client is None:
            self._mcp_client = MCPClientService.from_config_string(
                settings.MCP_CLIENT_SERVERS
            )
        return self._mcp_client

    def get_intent_service(self) -> IntentTreeService:
        if self._intent_service is None:
            self._intent_service = IntentTreeService(self.get_platform_store())
        return self._intent_service


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


def get_platform_store() -> PlatformStore:
    return _container.get_platform_store()


def get_ingestion_pipeline() -> IngestionPipeline:
    return _container.get_ingestion_pipeline()


def get_mcp_client() -> MCPClientService:
    return _container.get_mcp_client()


def get_intent_service() -> IntentTreeService:
    return _container.get_intent_service()
