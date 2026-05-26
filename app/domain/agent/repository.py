from abc import ABC, abstractmethod
from typing import List, Optional, TYPE_CHECKING, AsyncGenerator

if TYPE_CHECKING:
    from app.domain.agent.entity import AgentEntity


class ILLMClient(ABC):
    @abstractmethod
    async def stream_chat(self, messages: list, model: str = None, **kwargs) -> AsyncGenerator[str, None]:
        pass


class IAgentRepository(ABC):
    """Agent 会话仓储抽象接口"""

    @abstractmethod
    def get(self, session_id: str) -> Optional["AgentEntity"]:
        pass

    @abstractmethod
    def save(self, agent: "AgentEntity") -> None:
        pass

    @abstractmethod
    def delete(self, session_id: str) -> None:
        pass

    @abstractmethod
    def list_sessions(self) -> List[str]:
        pass

    @abstractmethod
    def save_prompt(self, session_id: str, prompt: str) -> None:
        pass

    @abstractmethod
    def get_prompt(self, session_id: str) -> Optional[str]:
        pass